from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import cv2
import numpy

from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .models import Candidate
from .normalize import CropRegion, normalize_card
from .roi import roi_group_bboxes
from .utils.geometry import quad_from_bbox
from .catalog.scryfall_sync import REQUEST_HEADERS

SET_SYMBOL_CACHE_DIR = Path("data") / "cache" / "set_symbol_refs"
SET_SYMBOL_MATCH_THRESHOLD = 0.84
SET_SYMBOL_CONFIDENCE_THRESHOLD = 0.92
SET_SYMBOL_TOP_CANDIDATES = 3


@dataclass(frozen=True)
class SetSymbolRerankResult:
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


def rerank_candidates_by_set_symbol(
    candidates: list[Candidate],
    *,
    observed_crop: CropRegion | None,
    catalog: LocalCatalogIndex | None,
    progress_callback: Callable[[str], None] | None = None,
) -> SetSymbolRerankResult:
    if not candidates or catalog is None:
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "missing_inputs"})
    if observed_crop is None or getattr(observed_crop, "image_array", None) is None:
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "missing_observed_crop"})
    if not _should_apply_tiebreak(candidates):
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "not_needed"})

    observed_hash = _compute_average_hash(observed_crop.image_array)
    if observed_hash is None:
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "unhashable_observed"})

    updated: list[Candidate] = []
    comparisons: list[dict] = []
    compared = 0

    for candidate in candidates:
        updated_candidate = candidate
        if compared < SET_SYMBOL_TOP_CANDIDATES:
            record = _lookup_record_for_candidate(catalog, candidate)
            if record is not None and record.set_code and record.image_uri:
                similarity = _reference_similarity_for_record(
                    record,
                    observed_hash=observed_hash,
                    progress_callback=progress_callback,
                )
                if similarity is not None:
                    compared += 1
                    score_delta = round((similarity - 0.5) * 0.18, 4)
                    notes = list(candidate.notes or [])
                    if similarity >= SET_SYMBOL_MATCH_THRESHOLD:
                        notes.append("set_symbol_match")
                    else:
                        notes.append("set_symbol_weak")
                    updated_candidate = replace(
                        candidate,
                        score=max(0.0, min(1.0, round(candidate.score + score_delta, 4))),
                        notes=notes,
                    )
                    comparisons.append(
                        {
                            "candidate": candidate.name,
                            "set_code": candidate.set_code,
                            "collector_number": candidate.collector_number,
                            "similarity": round(similarity, 4),
                            "score_delta": score_delta,
                        }
                    )
        updated.append(updated_candidate)

    updated.sort(key=lambda candidate: (-candidate.score, candidate.name, candidate.set_code or "", candidate.collector_number or ""))
    return SetSymbolRerankResult(
        candidates=updated,
        debug={
            "used": bool(comparisons),
            "comparisons": comparisons,
            "observed_crop_label": observed_crop.label,
            "reason": "applied" if comparisons else "no_reference_match",
        },
    )


def should_skip_secondary_ocr(candidates: list[Candidate], confidence: float) -> bool:
    if not candidates:
        return False
    best = candidates[0]
    return (
        confidence >= SET_SYMBOL_CONFIDENCE_THRESHOLD
        and bool(best.notes)
        and "set_symbol_match" in best.notes
    )


def _should_apply_tiebreak(candidates: list[Candidate]) -> bool:
    if len(candidates) < 2:
        return False
    first, second = candidates[0], candidates[1]
    if first.name != second.name:
        return False
    return abs(first.score - second.score) <= 0.08


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
    observed_hash: str,
    progress_callback: Callable[[str], None] | None = None,
) -> float | None:
    reference_hash = _load_or_compute_reference_hash(record, progress_callback=progress_callback)
    if reference_hash is None:
        return None
    return _hash_similarity(observed_hash, reference_hash)


def _load_or_compute_reference_hash(
    record: CatalogRecord,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> str | None:
    if not record.set_code or not record.image_uri:
        return None

    SET_SYMBOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = SET_SYMBOL_CACHE_DIR / f"{record.set_code.lower()}.json"
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("hash"), str):
            return payload["hash"]

    if progress_callback is not None:
        progress_callback(f"Comparing set symbol for set {record.set_code}...")

    image = _download_reference_image(record.image_uri)
    if image is None:
        return None
    normalized = normalize_card(
        image,
        (0, 0, image.width, image.height),
        quad=quad_from_bbox((0, 0, image.width, image.height)),
        roi_groups=["set_symbol"],
    )
    crop = next(iter(normalized.crops.values()), None)
    if crop is None or getattr(crop, "image_array", None) is None:
        return None

    reference_hash = _compute_average_hash(crop.image_array)
    if reference_hash is None:
        return None

    cache_path.write_text(
        json.dumps({"hash": reference_hash, "image_uri": record.image_uri}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return reference_hash


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


def _compute_average_hash(image_array, size: int = 8) -> str | None:
    try:
        grayscale = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(grayscale, (size, size), interpolation=cv2.INTER_AREA)
    except Exception:
        return None
    mean_value = float(resized.mean())
    bits = "".join("1" if value >= mean_value else "0" for value in resized.flatten())
    return f"{int(bits, 2):0{size * size // 4}x}"


def _hash_similarity(left_hash: str, right_hash: str) -> float:
    max_bits = min(len(left_hash), len(right_hash)) * 4
    xor_value = int(left_hash, 16) ^ int(right_hash, 16)
    differing_bits = xor_value.bit_count()
    return round(max(0.0, 1.0 - (differing_bits / max_bits)), 4)
