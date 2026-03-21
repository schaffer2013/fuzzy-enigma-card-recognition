from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import cv2
import numpy

from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .catalog.scryfall_sync import REQUEST_HEADERS
from .models import Candidate
from .normalize import CropRegion, normalize_card
from .utils.geometry import quad_from_bbox

ART_MATCH_CACHE_DIR = Path("data") / "cache" / "art_match_refs"
ART_MATCH_MATCH_THRESHOLD = 0.81
ART_MATCH_SCORE_WINDOW = 0.1
ART_MATCH_MARGIN_THRESHOLD = 0.03


@dataclass(frozen=True)
class ArtRerankResult:
    candidates: list[Candidate]
    debug: dict


@dataclass(frozen=True)
class _ReferenceImage:
    image_array: object
    width: int
    height: int
    path: str | None = None

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.image_array.shape


def rerank_candidates_by_art(
    candidates: list[Candidate],
    *,
    observed_crop: CropRegion | None,
    catalog: LocalCatalogIndex | None,
    progress_callback: Callable[[str], None] | None = None,
) -> ArtRerankResult:
    if not candidates or catalog is None:
        return ArtRerankResult(candidates=candidates, debug={"used": False, "reason": "missing_inputs"})
    if observed_crop is None or getattr(observed_crop, "image_array", None) is None:
        return ArtRerankResult(candidates=candidates, debug={"used": False, "reason": "missing_observed_crop"})
    if not _should_apply_art_tiebreak(candidates):
        return ArtRerankResult(candidates=candidates, debug={"used": False, "reason": "not_needed"})

    observed_fingerprint = _compute_art_fingerprint(observed_crop.image_array)
    if observed_fingerprint is None:
        return ArtRerankResult(candidates=candidates, debug={"used": False, "reason": "unhashable_observed"})

    comparison_indices = _candidate_indices_for_art_compare(candidates)
    if not comparison_indices:
        return ArtRerankResult(candidates=candidates, debug={"used": False, "reason": "not_needed"})

    comparisons: list[dict] = []
    similarity_by_index: dict[int, float] = {}
    for index in comparison_indices:
        candidate = candidates[index]
        record = _lookup_record_for_candidate(catalog, candidate)
        if record is None or not record.image_uri:
            continue
        similarity = _reference_similarity_for_record(
            record,
            observed_fingerprint=observed_fingerprint,
            progress_callback=progress_callback,
        )
        if similarity is None:
            continue
        similarity_by_index[index] = similarity
        comparisons.append(
            {
                "candidate": candidate.name,
                "set_code": candidate.set_code,
                "collector_number": candidate.collector_number,
                "similarity": round(similarity, 4),
            }
        )

    if not similarity_by_index:
        return ArtRerankResult(
            candidates=candidates,
            debug={
                "used": False,
                "comparisons": comparisons,
                "observed_crop_label": observed_crop.label,
                "reason": "no_reference_match",
            },
        )

    strongest = sorted(similarity_by_index.values(), reverse=True)
    strongest_similarity = strongest[0]
    runner_up_similarity = strongest[1] if len(strongest) > 1 else 0.0
    if strongest_similarity < ART_MATCH_MATCH_THRESHOLD or (strongest_similarity - runner_up_similarity) < ART_MATCH_MARGIN_THRESHOLD:
        return ArtRerankResult(
            candidates=candidates,
            debug={
                "used": False,
                "comparisons": comparisons,
                "observed_crop_label": observed_crop.label,
                "observed_fingerprint": {
                    "gray_dhash_prefix": observed_fingerprint["gray_dhash"][:24],
                    "edge_dhash_prefix": observed_fingerprint["edge_dhash"][:24],
                    "mean_bgr": observed_fingerprint["mean_bgr"],
                },
                "reason": "not_distinctive",
            },
        )

    updated: list[Candidate] = []
    for index, candidate in enumerate(candidates):
        updated_candidate = candidate
        if index in similarity_by_index:
            similarity = similarity_by_index[index]
            score_delta = round((similarity - 0.5) * 0.22, 4)
            notes = list(candidate.notes or [])
            if similarity >= ART_MATCH_MATCH_THRESHOLD:
                notes.append("art_match")
            else:
                notes.append("art_match_weak")
            updated_candidate = replace(
                candidate,
                score=max(0.0, min(1.0, round(candidate.score + score_delta, 4))),
                notes=notes,
            )
            for comparison in comparisons:
                if (
                    comparison["set_code"] == candidate.set_code
                    and comparison["collector_number"] == candidate.collector_number
                ):
                    comparison["score_delta"] = score_delta
                    break
        updated.append(updated_candidate)

    updated.sort(key=lambda candidate: (-candidate.score, candidate.name, candidate.set_code or "", candidate.collector_number or ""))
    return ArtRerankResult(
        candidates=updated,
        debug={
            "used": bool(comparisons),
            "comparisons": comparisons,
            "observed_crop_label": observed_crop.label,
            "observed_fingerprint": {
                "gray_dhash_prefix": observed_fingerprint["gray_dhash"][:24],
                "edge_dhash_prefix": observed_fingerprint["edge_dhash"][:24],
                "mean_bgr": observed_fingerprint["mean_bgr"],
            },
            "reason": "applied" if comparisons else "no_reference_match",
        },
    )


def _should_apply_art_tiebreak(candidates: list[Candidate]) -> bool:
    if len(candidates) < 2:
        return False
    first, second = candidates[0], candidates[1]
    if first.name != second.name:
        return False
    return abs(first.score - second.score) <= 0.1


def _candidate_indices_for_art_compare(candidates: list[Candidate]) -> list[int]:
    if not candidates:
        return []
    best = candidates[0]
    indices: list[int] = []
    for index, candidate in enumerate(candidates):
        if candidate.name != best.name:
            continue
        if (best.score - candidate.score) > ART_MATCH_SCORE_WINDOW:
            continue
        indices.append(index)
    if len(indices) < 2:
        return []
    return indices


def _lookup_record_for_candidate(catalog: LocalCatalogIndex, candidate: Candidate) -> CatalogRecord | None:
    for record in catalog.records:
        if record.name != candidate.name:
            continue
        if record.set_code != candidate.set_code:
            continue
        if record.collector_number != candidate.collector_number:
            continue
        return record
    return None


def _reference_similarity_for_record(
    record: CatalogRecord,
    *,
    observed_fingerprint: dict[str, float | str | list[float]],
    progress_callback: Callable[[str], None] | None = None,
) -> float | None:
    reference_fingerprint = _load_or_compute_reference_fingerprint(record, progress_callback=progress_callback)
    if reference_fingerprint is None:
        return None
    return _fingerprint_similarity(observed_fingerprint, reference_fingerprint)


def _load_or_compute_reference_fingerprint(
    record: CatalogRecord,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, float | str | list[float]] | None:
    if not record.image_uri:
        return None

    ART_MATCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = ART_MATCH_CACHE_DIR / _reference_cache_name(record)
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if _is_valid_fingerprint(payload):
            return payload

    if progress_callback is not None:
        progress_callback(f"Comparing art region for {record.set_code or '?'} {record.collector_number or ''}...")

    image = _download_reference_image(record.image_uri)
    if image is None:
        return None
    normalized = normalize_card(
        image,
        (0, 0, image.width, image.height),
        quad=quad_from_bbox((0, 0, image.width, image.height)),
        roi_groups=["art_match"],
    )
    crop = next(iter(normalized.crops.values()), None)
    if crop is None or getattr(crop, "image_array", None) is None:
        return None

    reference_fingerprint = _compute_art_fingerprint(crop.image_array)
    if reference_fingerprint is None:
        return None

    cache_path.write_text(
        json.dumps(reference_fingerprint, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return reference_fingerprint


def _download_reference_image(image_uri: str) -> _ReferenceImage | None:
    request = Request(image_uri, headers=REQUEST_HEADERS)
    try:
        with urlopen(request) as response:
            payload = response.read()
    except Exception:
        return None

    buffer = numpy.frombuffer(payload, dtype=numpy.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None:
        return None
    height, width = decoded.shape[:2]
    return _ReferenceImage(image_array=decoded, width=width, height=height, path=image_uri)


def _compute_art_fingerprint(image_array) -> dict[str, float | str | list[float]] | None:
    processed = _preprocess_art_image(image_array)
    if processed is None:
        return None

    grayscale, hsv = processed
    edges = cv2.Canny(grayscale, 60, 140)
    histogram = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256])
    histogram = cv2.normalize(histogram, histogram).flatten()
    mean_bgr = cv2.mean(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR))[:3]
    return {
        "gray_dhash": _compute_difference_hash(grayscale, size=18),
        "edge_dhash": _compute_difference_hash(edges, size=18),
        "hsv_histogram": [round(float(value), 6) for value in histogram.tolist()],
        "mean_bgr": [round(float(value), 2) for value in mean_bgr],
    }


def _preprocess_art_image(image_array) -> tuple[object, object] | None:
    try:
        height, width = image_array.shape[:2]
    except Exception:
        return None

    inset_x = max(1, int(round(width * 0.03)))
    inset_y = max(1, int(round(height * 0.03)))
    cropped = image_array[inset_y : height - inset_y, inset_x : width - inset_x]
    if cropped is None or getattr(cropped, "size", 0) == 0:
        cropped = image_array

    try:
        resized = cv2.resize(cropped, (128, 96), interpolation=cv2.INTER_AREA)
        grayscale = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    except Exception:
        return None
    return grayscale, hsv


def _compute_difference_hash(image_array, size: int = 18) -> str | None:
    try:
        resized = cv2.resize(image_array, (size + 1, size), interpolation=cv2.INTER_AREA)
    except Exception:
        return None
    differences = resized[:, 1:] >= resized[:, :-1]
    bits = "".join("1" if value else "0" for value in differences.flatten())
    return f"{int(bits, 2):0{size * size // 4}x}"


def _hash_similarity(left_hash: str, right_hash: str) -> float:
    max_bits = min(len(left_hash), len(right_hash)) * 4
    xor_value = int(left_hash, 16) ^ int(right_hash, 16)
    differing_bits = xor_value.bit_count()
    return round(max(0.0, 1.0 - (differing_bits / max_bits)), 4)


def _histogram_similarity(left_histogram: list[float], right_histogram: list[float]) -> float:
    left = numpy.array(left_histogram, dtype=numpy.float32)
    right = numpy.array(right_histogram, dtype=numpy.float32)
    denominator = float(numpy.linalg.norm(left) * numpy.linalg.norm(right))
    if denominator == 0.0:
        return 0.0
    similarity = float(numpy.dot(left, right) / denominator)
    return round(max(0.0, min(1.0, similarity)), 4)


def _mean_color_similarity(left_mean: list[float], right_mean: list[float]) -> float:
    left = numpy.array(left_mean, dtype=numpy.float32)
    right = numpy.array(right_mean, dtype=numpy.float32)
    distance = float(numpy.linalg.norm(left - right))
    return round(max(0.0, 1.0 - (distance / 255.0)), 4)


def _fingerprint_similarity(
    observed_fingerprint: dict[str, float | str | list[float]],
    reference_fingerprint: dict[str, float | str | list[float]],
) -> float:
    gray_similarity = _hash_similarity(
        str(observed_fingerprint["gray_dhash"]),
        str(reference_fingerprint["gray_dhash"]),
    )
    edge_similarity = _hash_similarity(
        str(observed_fingerprint["edge_dhash"]),
        str(reference_fingerprint["edge_dhash"]),
    )
    histogram_similarity = _histogram_similarity(
        list(observed_fingerprint["hsv_histogram"]),
        list(reference_fingerprint["hsv_histogram"]),
    )
    mean_similarity = _mean_color_similarity(
        list(observed_fingerprint["mean_bgr"]),
        list(reference_fingerprint["mean_bgr"]),
    )
    similarity = (
        (gray_similarity * 0.22)
        + (edge_similarity * 0.18)
        + (histogram_similarity * 0.45)
        + (mean_similarity * 0.15)
    )
    return round(similarity, 4)


def _reference_cache_name(record: CatalogRecord) -> str:
    raw_key = "|".join(
        [
            record.set_code or "unknown",
            record.collector_number or "unknown",
            record.image_uri or "",
        ]
    )
    digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:12]
    safe_collector = "".join(character if character.isalnum() else "-" for character in (record.collector_number or "unknown"))
    return f"{(record.set_code or 'unknown').lower()}-{safe_collector.lower()}-{digest}.json"


def _is_valid_fingerprint(payload: object) -> bool:
    return isinstance(payload, dict) and all(
        key in payload
        for key in ("gray_dhash", "edge_dhash", "hsv_histogram", "mean_bgr")
    )
