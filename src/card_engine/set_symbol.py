from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

import cv2
import numpy

from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .models import Candidate
from .normalize import CropRegion, normalize_card
from .roi import roi_group_signature
from .utils.geometry import quad_from_bbox
from .catalog.scryfall_sync import REQUEST_HEADERS

SET_SYMBOL_CACHE_DIR = Path("data") / "cache" / "set_symbol_refs"
SET_SYMBOL_MATCH_THRESHOLD = 0.84
SET_SYMBOL_CONFIDENCE_THRESHOLD = 0.92
SET_SYMBOL_SCORE_WINDOW = 0.12
PRIMARY_EXACT_SKIP_CONFIDENCE_THRESHOLD = 0.9
PRIMARY_EXACT_MARGIN_SKIP_THRESHOLD = 0.16
SUPPORTED_FUZZY_SKIP_CONFIDENCE_THRESHOLD = 0.94
SETTLED_NAME_SKIP_CONFIDENCE_THRESHOLD = 0.88
SETTLED_NAME_DIFFERENT_NAME_MARGIN_THRESHOLD = 0.18
SECONDARY_SKIP_SUPPORT_NOTES = {
    "type_line_match",
    "lower_text_match",
    "set_symbol_match",
    "art_match",
}


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
    observed_fingerprint: dict[str, float | str] | None = None,
    catalog: LocalCatalogIndex | None,
    progress_callback: Callable[[str], None] | None = None,
    max_comparisons: int | None = None,
    deadline: float | None = None,
    download_timeout_seconds: float = 10.0,
) -> SetSymbolRerankResult:
    if not candidates or catalog is None:
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "missing_inputs"})
    if observed_crop is None or getattr(observed_crop, "image_array", None) is None:
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "missing_observed_crop"})
    if not _should_apply_tiebreak(candidates):
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "not_needed"})

    observed_fingerprint = observed_fingerprint or _compute_symbol_fingerprint(observed_crop.image_array)
    if observed_fingerprint is None:
        return SetSymbolRerankResult(candidates=candidates, debug={"used": False, "reason": "unhashable_observed"})

    updated: list[Candidate] = []
    comparisons: list[dict] = []
    comparison_indices = set(_candidate_indices_for_symbol_compare(candidates, max_comparisons=max_comparisons))
    deadline_exceeded = False

    for index, candidate in enumerate(candidates):
        updated_candidate = candidate
        if index in comparison_indices:
            if deadline is not None and time.monotonic() >= deadline:
                deadline_exceeded = True
            else:
                record = _lookup_record_for_candidate(catalog, candidate)
                if record is not None and record.set_code and record.image_uri:
                    similarity = _call_with_supported_kwargs(
                        _reference_similarity_for_record,
                        record,
                        observed_fingerprint=observed_fingerprint,
                        progress_callback=progress_callback,
                        download_timeout_seconds=download_timeout_seconds,
                    )
                    if similarity is not None:
                        score_delta = round((similarity - 0.5) * 0.24, 4)
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
            "observed_fingerprint": {
                "binary_mask_prefix": observed_fingerprint["binary_mask"][:24],
                "dhash_prefix": observed_fingerprint["gray_dhash"][:24],
            },
            "reason": _comparison_reason(comparisons, deadline_exceeded),
        },
    )


def should_skip_secondary_ocr(candidates: list[Candidate], confidence: float) -> bool:
    if not candidates:
        return False
    best = candidates[0]
    notes = set(best.notes or [])
    if (
        len(candidates) == 1
        and "exact" in notes
        and "noisy_title_ocr" not in notes
        and confidence >= PRIMARY_EXACT_SKIP_CONFIDENCE_THRESHOLD
    ):
        return True

    if (
        len(candidates) == 1
        and confidence >= SUPPORTED_FUZZY_SKIP_CONFIDENCE_THRESHOLD
        and bool(notes & SECONDARY_SKIP_SUPPORT_NOTES)
    ):
        return True

    runner_up = candidates[1] if len(candidates) > 1 else None
    if (
        runner_up is not None
        and best.name != runner_up.name
        and "exact" in notes
        and "noisy_title_ocr" not in notes
        and (best.score - runner_up.score) >= PRIMARY_EXACT_MARGIN_SKIP_THRESHOLD
        and confidence >= PRIMARY_EXACT_SKIP_CONFIDENCE_THRESHOLD
    ):
        return True

    strongest_different_name = next((candidate for candidate in candidates[1:] if candidate.name != best.name), None)
    if (
        strongest_different_name is not None
        and confidence >= SETTLED_NAME_SKIP_CONFIDENCE_THRESHOLD
        and (best.score - strongest_different_name.score) >= SETTLED_NAME_DIFFERENT_NAME_MARGIN_THRESHOLD
        and bool(notes & SECONDARY_SKIP_SUPPORT_NOTES)
    ):
        return True

    return (
        confidence >= SET_SYMBOL_CONFIDENCE_THRESHOLD
        and bool(notes)
        and ("set_symbol_match" in notes or "art_match" in notes)
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
    observed_fingerprint: dict[str, float | str],
    progress_callback: Callable[[str], None] | None = None,
    download_timeout_seconds: float = 10.0,
) -> float | None:
    reference_fingerprint = _load_or_compute_reference_hash(
        record,
        progress_callback=progress_callback,
        download_timeout_seconds=download_timeout_seconds,
    )
    if reference_fingerprint is None:
        return None
    return _fingerprint_similarity(observed_fingerprint, reference_fingerprint)


def _load_or_compute_reference_hash(
    record: CatalogRecord,
    *,
    progress_callback: Callable[[str], None] | None = None,
    download_timeout_seconds: float = 10.0,
) -> dict[str, float | str] | None:
    if not record.set_code or not record.image_uri:
        return None

    SET_SYMBOL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _refresh_reference_cache_if_needed()
    cache_path = SET_SYMBOL_CACHE_DIR / _reference_cache_name(record)
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        cached_fingerprint = _cached_fingerprint(
            payload,
        )
        if cached_fingerprint is not None:
            return cached_fingerprint

    _notify(progress_callback, f"Comparing set symbol for {record.set_code} {record.collector_number or ''}...")

    image = _download_reference_image(record.image_uri, download_timeout_seconds=download_timeout_seconds)
    if image is None:
        return None
    normalized = _call_with_supported_kwargs(
        normalize_card,
        image,
        (0, 0, image.width, image.height),
        quad=quad_from_bbox((0, 0, image.width, image.height)),
        roi_groups=["set_symbol"],
    )
    crop = next(iter(normalized.crops.values()), None)
    if crop is None or getattr(crop, "image_array", None) is None:
        return None

    reference_hash = _compute_symbol_fingerprint(crop.image_array)
    if reference_hash is None:
        return None

    cache_path.write_text(
        json.dumps(
            _cache_payload(
                reference_hash,
            ),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return reference_hash


def _download_reference_image(image_uri: str, *, download_timeout_seconds: float = 10.0) -> _ReferenceImage | None:
    request = Request(image_uri, headers=REQUEST_HEADERS)
    try:
        with urlopen(request, timeout=download_timeout_seconds) as response:
            payload = response.read()
    except Exception:
        return None

    buffer = numpy.frombuffer(payload, dtype=numpy.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None:
        return None
    height, width = decoded.shape[:2]
    return _ReferenceImage(image_array=decoded, width=width, height=height, path=image_uri)


def _compute_symbol_fingerprint(image_array) -> dict[str, float | str] | None:
    processed = _preprocess_symbol_image(image_array)
    if processed is None:
        return None
    grayscale, binary_mask = processed
    edge_mask = cv2.Canny(grayscale, 40, 120)
    return {
        "gray_dhash": _compute_difference_hash(grayscale, size=16),
        "edge_ahash": _compute_average_hash(edge_mask, size=16),
        "binary_mask": _pack_binary_mask(binary_mask),
        "foreground_ratio": round(float(binary_mask.mean() / 255.0), 4),
    }


def compute_symbol_fingerprint(image_array) -> dict[str, float | str] | None:
    return _compute_symbol_fingerprint(image_array)


def _refresh_reference_cache_if_needed(
) -> None:
    manifest_path = SET_SYMBOL_CACHE_DIR / "_cache_meta.json"
    current_meta = {
        "roi_signature": _call_with_supported_kwargs(
            _current_roi_signature,
        )
    }
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    if payload == current_meta:
        return
    for cache_file in SET_SYMBOL_CACHE_DIR.glob("*.json"):
        cache_file.unlink(missing_ok=True)
    manifest_path.write_text(json.dumps(current_meta, indent=2, sort_keys=True), encoding="utf-8")


def _current_roi_signature(
) -> str:
    return roi_group_signature("set_symbol")


def _cache_payload(
    fingerprint: dict[str, float | str],
) -> dict[str, object]:
    return {
        "fingerprint": fingerprint,
        "roi_signature": _call_with_supported_kwargs(
            _current_roi_signature,
        ),
    }


def _cached_fingerprint(
    payload: object,
) -> dict[str, float | str] | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("roi_signature") != _call_with_supported_kwargs(
        _current_roi_signature,
    ):
        return None
    fingerprint = payload.get("fingerprint")
    return fingerprint if _is_valid_fingerprint(fingerprint) else None


def _compute_average_hash(image_array, size: int = 16) -> str | None:
    try:
        if image_array.ndim == 3:
            grayscale = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
        else:
            grayscale = image_array
        resized = cv2.resize(grayscale, (size, size), interpolation=cv2.INTER_AREA)
    except Exception:
        return None
    mean_value = float(resized.mean())
    bits = "".join("1" if value >= mean_value else "0" for value in resized.flatten())
    return f"{int(bits, 2):0{size * size // 4}x}"


def _compute_difference_hash(image_array, size: int = 16) -> str | None:
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


def _fingerprint_similarity(
    observed_fingerprint: dict[str, float | str],
    reference_fingerprint: dict[str, float | str],
) -> float:
    binary_similarity = _hash_similarity(
        str(observed_fingerprint["binary_mask"]),
        str(reference_fingerprint["binary_mask"]),
    )
    gray_similarity = _hash_similarity(
        str(observed_fingerprint["gray_dhash"]),
        str(reference_fingerprint["gray_dhash"]),
    )
    edge_similarity = _hash_similarity(
        str(observed_fingerprint["edge_ahash"]),
        str(reference_fingerprint["edge_ahash"]),
    )
    foreground_similarity = max(
        0.0,
        1.0 - abs(float(observed_fingerprint["foreground_ratio"]) - float(reference_fingerprint["foreground_ratio"])),
    )
    similarity = (
        (binary_similarity * 0.5)
        + (gray_similarity * 0.2)
        + (edge_similarity * 0.2)
        + (foreground_similarity * 0.1)
    )
    return round(similarity, 4)


def _preprocess_symbol_image(image_array) -> tuple[object, object] | None:
    try:
        grayscale = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
    except Exception:
        return None

    height, width = grayscale.shape[:2]
    inset_x = max(1, int(round(width * 0.12)))
    inset_y = max(1, int(round(height * 0.08)))
    cropped = grayscale[inset_y : height - inset_y, inset_x : width - inset_x]
    if cropped.size == 0:
        cropped = grayscale

    normalized = cv2.equalizeHist(cropped)
    normalized = cv2.GaussianBlur(normalized, (3, 3), 0)
    normalized = cv2.resize(normalized, (48, 48), interpolation=cv2.INTER_CUBIC)
    _threshold, threshold_mask = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary_mask = _select_symbol_mask(threshold_mask)
    return _tighten_symbol_focus(normalized, binary_mask)


def _select_symbol_mask(threshold_mask) -> object:
    candidates = [threshold_mask, cv2.bitwise_not(threshold_mask)]
    return max(candidates, key=_mask_quality_score)


def _mask_quality_score(binary_mask) -> float:
    cleaned = _clean_symbol_mask(binary_mask)
    coords = cv2.findNonZero(cleaned)
    if coords is None:
        return 0.0

    x, y, width, height = cv2.boundingRect(coords)
    total_area = max(1, cleaned.shape[0] * cleaned.shape[1])
    foreground_ratio = float(cleaned.mean() / 255.0)
    bbox_ratio = float((width * height) / total_area)

    foreground_score = 1.0 - min(abs(foreground_ratio - 0.18) / 0.18, 1.0)
    bbox_score = 1.0 - min(abs(bbox_ratio - 0.35) / 0.35, 1.0)
    center_x = x + (width / 2.0)
    center_y = y + (height / 2.0)
    center_distance = abs(center_x - (cleaned.shape[1] / 2.0)) + abs(center_y - (cleaned.shape[0] / 2.0))
    max_center_distance = max(1.0, cleaned.shape[0] + cleaned.shape[1])
    center_score = 1.0 - min(center_distance / max_center_distance, 1.0)

    return (foreground_score * 0.45) + (bbox_score * 0.35) + (center_score * 0.20)


def _clean_symbol_mask(binary_mask):
    kernel = numpy.ones((3, 3), dtype=numpy.uint8)
    cleaned = cv2.morphologyEx(binary_mask, cv2.MORPH_OPEN, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel)
    return cleaned


def _tighten_symbol_focus(grayscale, binary_mask) -> tuple[object, object]:
    cleaned = _clean_symbol_mask(binary_mask)
    coords = cv2.findNonZero(cleaned)
    if coords is None:
        return grayscale, cleaned

    x, y, width, height = cv2.boundingRect(coords)
    pad = max(2, int(round(max(width, height) * 0.18)))
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(cleaned.shape[1], x + width + pad)
    bottom = min(cleaned.shape[0], y + height + pad)

    cropped_gray = grayscale[top:bottom, left:right]
    cropped_mask = cleaned[top:bottom, left:right]
    if cropped_gray.size == 0 or cropped_mask.size == 0:
        return grayscale, cleaned

    resized_gray = cv2.resize(cropped_gray, (48, 48), interpolation=cv2.INTER_CUBIC)
    resized_mask = cv2.resize(cropped_mask, (48, 48), interpolation=cv2.INTER_NEAREST)
    return resized_gray, resized_mask


def _pack_binary_mask(binary_mask) -> str:
    flattened = (binary_mask.flatten() > 0).astype(numpy.uint8)
    bits = "".join("1" if value else "0" for value in flattened)
    return f"{int(bits, 2):0{len(bits) // 4}x}"


def _candidate_indices_for_symbol_compare(
    candidates: list[Candidate],
    *,
    max_comparisons: int | None = None,
) -> list[int]:
    if not candidates:
        return []
    best = candidates[0]
    indices: list[int] = []
    for index, candidate in enumerate(candidates):
        if candidate.name != best.name:
            continue
        if (best.score - candidate.score) > SET_SYMBOL_SCORE_WINDOW:
            continue
        indices.append(index)
        if max_comparisons is not None and max_comparisons > 0 and len(indices) >= max_comparisons:
            break
    if len(indices) < 2:
        return []
    return indices


def _notify(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is None:
        return
    try:
        callback(message)
    except UnicodeEncodeError:
        callback(str(message).encode("ascii", "replace").decode("ascii"))


def _call_with_supported_kwargs(function, *args, **kwargs):
    signature = inspect.signature(function)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return function(*args, **kwargs)

    supported_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return function(*args, **supported_kwargs)


def _comparison_reason(comparisons: list[dict], deadline_exceeded: bool) -> str:
    if deadline_exceeded and comparisons:
        return "deadline_exceeded_partial"
    if deadline_exceeded:
        return "deadline_exceeded"
    if comparisons:
        return "applied"
    return "no_reference_match"


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
        for key in ("gray_dhash", "edge_ahash", "binary_mask", "foreground_ratio")
    )
