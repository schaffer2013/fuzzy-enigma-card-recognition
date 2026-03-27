from pathlib import Path
from functools import lru_cache
from typing import Any
import inspect
import re
import time

from .art_match import (
    art_fingerprint_similarity,
    compute_art_fingerprint,
    rerank_candidates_by_art,
)
from .catalog.maintenance import ensure_catalog_ready
from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .config import EngineConfig, load_engine_config
from .detector import detect_card
from .fixture_cache import persist_saved_detection
from .matcher import _title_queries_for_roi, match_candidates
from .models import Candidate, RecognitionResult, VisualPoolCandidate
from .normalize import CropRegion, normalize_card
from .ocr import run_ocr
from .operational_modes import (
    CandidatePool,
    ExpectedCard,
    apply_expected_mode_bias,
    resolve_operational_mode,
    score_confirmation_against_expected,
)
from .roi import resolve_roi_groups_for_layout
from .scorer import score_candidates
from .set_symbol import rerank_candidates_by_set_symbol, should_skip_secondary_ocr
from .utils.image_io import load_image

TITLE_FIRST_ROIS = {"planar_title", "standard", "adventure", "transform_back"}
VISUAL_ONLY_ROIS = {"set_symbol", "art_match"}
ROTATED_TITLE_ROIS = {
    "planar_title": (90, 270, 0),
    "split_full": (90, 270, 0),
}


def recognize_card(
    image: Any,
    *,
    mode: str | None = None,
    candidate_pool: CandidatePool | LocalCatalogIndex | None = None,
    visual_pool_candidates: list[VisualPoolCandidate] | None = None,
    expected_card: ExpectedCard | None = None,
    progress_callback=None,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    catalog: LocalCatalogIndex | None = None,
    skip_secondary_ocr: bool = False,
) -> RecognitionResult:
    start_time = time.monotonic()
    stage_timings: dict[str, float] = {}
    _notify(progress_callback, "Preparing image input...")
    prepared_image = _timed_call(stage_timings, "prepare_image_input", _prepare_image_input, image)
    config = config or load_engine_config()
    candidate_pool_limit = max(config.candidate_count * 4, config.candidate_count)
    if catalog is None:
        full_catalog = _timed_call(stage_timings, "load_catalog", _load_catalog, config.catalog_path)
    else:
        full_catalog = catalog
        stage_timings["load_catalog"] = 0.0
    resolved_mode = resolve_operational_mode(
        full_catalog,
        mode=mode,
        candidate_pool=candidate_pool,
        expected_card=expected_card,
    )
    catalog = resolved_mode.catalog
    skip_secondary_ocr = skip_secondary_ocr or resolved_mode.skip_secondary_ocr
    _notify(progress_callback, "Detecting card bounds...")
    detection = _timed_call(stage_timings, "detect_card", detect_card, prepared_image)
    _persist_saved_detection(prepared_image, detection)
    layout_hint = getattr(prepared_image, "layout_hint", getattr(prepared_image, "layout", "normal"))
    tried_rois = resolve_roi_groups_for_layout(
        layout_hint,
        enabled_groups=config.enabled_roi_groups,
        cycle_order=config.roi_cycle_order,
    )
    _notify(progress_callback, "Normalizing card image...")
    normalized = _timed_call(
        stage_timings,
        "normalize_card",
        normalize_card,
        prepared_image,
        detection.bbox,
        quad=detection.quad,
        roi_groups=tried_rois,
        expand_long_factor=config.roi_expand_long_factor,
        expand_short_factor=config.roi_expand_short_factor,
    )

    results_by_roi: dict[str, dict] = {}
    title_rois = [roi_group for roi_group in tried_rois if roi_group in TITLE_FIRST_ROIS]
    secondary_rois = [roi_group for roi_group in tried_rois if roi_group not in TITLE_FIRST_ROIS and roi_group not in VISUAL_ONLY_ROIS]
    set_symbol_debug = {"used": False, "reason": "not_attempted"}
    art_match_debug = {"used": False, "reason": "not_attempted"}
    expectation_debug = {"used": False, "reason": "not_applicable"}
    confirmation_debug = {"used": False, "reason": "not_applicable"}
    visual_small_pool_debug = {"used": False, "reason": "not_applicable"}
    set_symbol_crop = _first_crop_for_group(normalized.crops, "set_symbol")
    art_match_crop = _first_crop_for_group(normalized.crops, "art_match")
    visual_deadline = _resolve_visual_deadline(deadline, config)
    if visual_pool_candidates and art_match_crop is not None and not _deadline_exceeded(deadline):
        visual_small_pool_result = _timed_call(
            stage_timings,
            "small_pool_visual_compare",
            _match_visual_small_pool_candidates,
            visual_pool_candidates,
            art_match_crop=art_match_crop,
            catalog=catalog,
        )
        visual_small_pool_debug = visual_small_pool_result["debug"]
        winner = visual_small_pool_result["winner"]
        if winner is not None:
            _notify(progress_callback, f"Recognition complete: {winner.name}")
            stage_timings["total"] = round(time.monotonic() - start_time, 4)
            return RecognitionResult(
                bbox=detection.bbox,
                best_name=winner.name,
                confidence=visual_small_pool_result["confidence"],
                ocr_lines=[],
                top_k_candidates=visual_small_pool_result["candidates"][: config.candidate_count],
                active_roi="art_match",
                tried_rois=tried_rois,
                debug={
                    "image": {
                        "source": str(getattr(prepared_image, "path", "")) or type(prepared_image).__name__,
                        "shape": getattr(prepared_image, "shape", None),
                    },
                    "detection": detection.debug,
                    "normalization": {
                        "crop_count": len(normalized.crops),
                        **normalized.debug_outputs,
                    },
                    "ocr": {
                        "active_roi": None,
                        "results_by_roi": results_by_roi,
                    },
                    "set_symbol": set_symbol_debug,
                    "art_match": art_match_debug,
                    "expectation": expectation_debug,
                    "confirmation": confirmation_debug,
                    "small_pool_visual": visual_small_pool_debug,
                    "mode": {
                        "requested": resolved_mode.requested_mode,
                        "effective": resolved_mode.effective_mode,
                        "candidate_count": len(catalog.records),
                        "has_expected_card": expected_card is not None,
                        "has_candidate_pool": candidate_pool is not None,
                        "implementation_note": resolved_mode.implementation_note,
                    },
                    "timings": stage_timings,
                },
            )
    elif visual_pool_candidates and art_match_crop is None:
        visual_small_pool_debug = {"used": False, "reason": "missing_observed_crop"}

    ocr_results = []
    for roi_group in title_rois:
        _notify(progress_callback, f"Running OCR for ROI: {roi_group}...")
        ocr_start = time.monotonic()
        result = _run_ocr_for_roi_group(
            normalized.normalized_image,
            roi_group=roi_group,
            crop_region=_first_crop_for_group(normalized.crops, roi_group),
        )
        _record_duration(stage_timings, "title_ocr", ocr_start)
        ocr_results.append(result)
        results_by_roi[roi_group] = {
            "line_count": len(result.lines),
            "lines": result.lines,
            "confidence": result.confidence,
            "debug": result.debug,
        }

    active_roi = _best_title_roi_name(title_rois, results_by_roi, layout_hint=layout_hint) or (title_rois[0] if title_rois else None)
    active_index = title_rois.index(active_roi) if active_roi in title_rois else 0
    ocr = ocr_results[active_index] if ocr_results else run_ocr(normalized.normalized_image, roi_label=None)
    title_match_lines = list(ocr.lines)
    _notify(progress_callback, "Matching OCR text against catalog...")
    candidates = _timed_call(
        stage_timings,
        "match_candidates_primary",
        match_candidates,
        title_match_lines,
        limit=candidate_pool_limit,
        catalog=catalog,
        results_by_roi=results_by_roi,
        layout_hint=layout_hint,
        config=config,
    )
    if candidates and set_symbol_crop is not None and not _deadline_exceeded(deadline):
        _notify(progress_callback, "Comparing set symbol against top candidates...")
        set_symbol_result = _timed_call_supported_kwargs(
            stage_timings,
            "set_symbol_compare",
            rerank_candidates_by_set_symbol,
            candidates,
            observed_crop=set_symbol_crop,
            catalog=catalog,
            progress_callback=progress_callback,
            max_comparisons=config.max_visual_tiebreak_candidates,
            deadline=visual_deadline,
            download_timeout_seconds=config.reference_download_timeout_seconds,
        )
        candidates = set_symbol_result.candidates
        set_symbol_debug = set_symbol_result.debug
    elif candidates and set_symbol_crop is not None:
        set_symbol_debug = {"used": False, "reason": "deadline_exceeded"}
    if candidates and art_match_crop is not None and not _deadline_exceeded(deadline):
        _notify(progress_callback, "Comparing art region against top candidates...")
        art_match_result = _timed_call_supported_kwargs(
            stage_timings,
            "art_match_compare",
            rerank_candidates_by_art,
            candidates,
            observed_crop=art_match_crop,
            catalog=catalog,
            progress_callback=progress_callback,
            max_comparisons=config.max_visual_tiebreak_candidates,
            deadline=visual_deadline,
            download_timeout_seconds=config.reference_download_timeout_seconds,
        )
        candidates = art_match_result.candidates
        art_match_debug = art_match_result.debug
    elif candidates and art_match_crop is not None:
        art_match_debug = {"used": False, "reason": "deadline_exceeded"}
    candidates, expectation_debug = apply_expected_mode_bias(
        candidates,
        mode=resolved_mode.requested_mode,
        expected_card=expected_card,
    )
    _notify(progress_callback, "Scoring candidates...")
    if resolved_mode.requested_mode == "confirmation":
        best_name, confidence, confirmation_debug = _timed_call_supported_kwargs(
            stage_timings,
            "score_candidates_primary",
            score_confirmation_against_expected,
            candidates,
            expected_card=expected_card,
        )
    else:
        best_name, confidence = _timed_call(stage_timings, "score_candidates_primary", score_candidates, candidates)

    force_split_full_secondary = bool(
        secondary_rois
        and "split_full" in secondary_rois
        and _should_use_split_full_fallback(
            layout_hint=layout_hint,
            results_by_roi=results_by_roi,
            candidates=candidates,
            confidence=confidence,
        )
    )
    if (
        secondary_rois
        and not _deadline_exceeded(deadline)
        and (
            force_split_full_secondary
            or (
                not skip_secondary_ocr
                and not should_skip_secondary_ocr(candidates, confidence)
            )
        )
    ):
        secondary_rois = _refine_secondary_rois_for_context(
            secondary_rois,
            layout_hint=layout_hint,
            results_by_roi=results_by_roi,
            candidates=candidates,
            confidence=confidence,
        )
        if skip_secondary_ocr and force_split_full_secondary:
            secondary_rois = [roi_name for roi_name in secondary_rois if roi_name == "split_full"]
        secondary_candidates = candidates
        for roi_group in secondary_rois:
            if _deadline_exceeded(deadline):
                break
            _notify(progress_callback, f"Running OCR for ROI: {roi_group}...")
            ocr_start = time.monotonic()
            result = _run_ocr_for_roi_group(
                normalized.normalized_image,
                roi_group=roi_group,
                crop_region=_first_crop_for_group(normalized.crops, roi_group),
            )
            _record_duration(stage_timings, "secondary_ocr", ocr_start)
            results_by_roi[roi_group] = {
                "line_count": len(result.lines),
                "lines": result.lines,
                "confidence": result.confidence,
                "debug": result.debug,
            }
            active_roi = (
                _best_title_roi_name(tried_rois, results_by_roi, layout_hint=layout_hint)
                or next((roi for roi in tried_rois if results_by_roi.get(roi, {}).get("lines")), active_roi)
                or active_roi
            )
            ocr = (
                OCR_like(results_by_roi[active_roi])
                if active_roi and active_roi in results_by_roi
                else ocr
            )
            _notify(progress_callback, "Re-ranking with secondary OCR signals...")
            secondary_catalog_records = _catalog_records_for_candidates(catalog, secondary_candidates)
            if (layout_hint or "").lower() == "split" and roi_group == "split_full":
                split_full_records = _catalog_records_for_split_full_recovery(catalog, results_by_roi)
                if split_full_records:
                    secondary_catalog_records = split_full_records
            secondary_candidates = _timed_call(
                stage_timings,
                "match_candidates_secondary",
                match_candidates,
                title_match_lines,
                limit=candidate_pool_limit,
                catalog=catalog,
                results_by_roi=results_by_roi,
                layout_hint=layout_hint,
                config=config,
                candidate_records=secondary_catalog_records or None,
            )
            if set_symbol_crop is not None and not _deadline_exceeded(deadline):
                set_symbol_result = _timed_call_supported_kwargs(
                    stage_timings,
                    "set_symbol_compare",
                    rerank_candidates_by_set_symbol,
                    secondary_candidates,
                    observed_crop=set_symbol_crop,
                    catalog=catalog,
                    progress_callback=progress_callback,
                    max_comparisons=config.max_visual_tiebreak_candidates,
                    deadline=visual_deadline,
                    download_timeout_seconds=config.reference_download_timeout_seconds,
                )
                secondary_candidates = set_symbol_result.candidates
                set_symbol_debug = set_symbol_result.debug
            if art_match_crop is not None and not _deadline_exceeded(deadline):
                art_match_result = _timed_call_supported_kwargs(
                    stage_timings,
                    "art_match_compare",
                    rerank_candidates_by_art,
                    secondary_candidates,
                    observed_crop=art_match_crop,
                    catalog=catalog,
                    progress_callback=progress_callback,
                    max_comparisons=config.max_visual_tiebreak_candidates,
                    deadline=visual_deadline,
                    download_timeout_seconds=config.reference_download_timeout_seconds,
                )
                secondary_candidates = art_match_result.candidates
                art_match_debug = art_match_result.debug
            secondary_candidates, expectation_debug = apply_expected_mode_bias(
                secondary_candidates,
                mode=resolved_mode.requested_mode,
                expected_card=expected_card,
            )
            _notify(progress_callback, "Scoring candidates...")
            if resolved_mode.requested_mode == "confirmation":
                best_name, confidence, confirmation_debug = _timed_call_supported_kwargs(
                    stage_timings,
                    "score_candidates_secondary",
                    score_confirmation_against_expected,
                    secondary_candidates,
                    expected_card=expected_card,
                )
            else:
                best_name, confidence = _timed_call(
                    stage_timings,
                    "score_candidates_secondary",
                    score_candidates,
                    secondary_candidates,
                )
            candidates = secondary_candidates
            if should_skip_secondary_ocr(candidates, confidence):
                break
    elif secondary_rois:
        if skip_secondary_ocr and not force_split_full_secondary:
            _notify(progress_callback, "Skipping secondary OCR for constrained candidate pool...")
        else:
            _notify(progress_callback, "Skipping secondary OCR after confident title and visual tie-break match...")
    _notify(progress_callback, f"Recognition complete: {best_name or 'no match'}")
    stage_timings["total"] = round(time.monotonic() - start_time, 4)

    return RecognitionResult(
        bbox=detection.bbox,
        best_name=best_name,
        confidence=confidence,
        ocr_lines=ocr.lines,
        top_k_candidates=candidates[: config.candidate_count],
        active_roi=active_roi,
        tried_rois=tried_rois,
        debug={
            "image": {
                "source": str(getattr(prepared_image, "path", "")) or type(prepared_image).__name__,
                "shape": getattr(prepared_image, "shape", None),
            },
            "detection": detection.debug,
            "normalization": {
                "crop_count": len(normalized.crops),
                **normalized.debug_outputs,
            },
            "ocr": {
                "active_roi": active_roi,
                "results_by_roi": results_by_roi,
                **ocr.debug,
            },
            "set_symbol": set_symbol_debug,
            "art_match": art_match_debug,
            "expectation": expectation_debug,
            "confirmation": confirmation_debug,
            "small_pool_visual": visual_small_pool_debug,
            "mode": {
                "requested": resolved_mode.requested_mode,
                "effective": resolved_mode.effective_mode,
                "candidate_count": len(catalog.records),
                "has_expected_card": expected_card is not None,
                "has_candidate_pool": candidate_pool is not None,
                "implementation_note": resolved_mode.implementation_note,
            },
            "timings": stage_timings,
        },
    )


def _prepare_image_input(image: Any) -> Any:
    if isinstance(image, (str, Path)):
        return load_image(image)

    return image


def _catalog_records_for_candidates(
    catalog: LocalCatalogIndex,
    candidates: list[Candidate],
) -> list[CatalogRecord]:
    records: list[CatalogRecord] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for candidate in candidates:
        record = catalog.find_record(
            name=candidate.name,
            set_code=candidate.set_code,
            collector_number=candidate.collector_number,
        )
        if record is None:
            continue
        key = (record.name, record.set_code, record.collector_number)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def _catalog_records_for_split_full_recovery(
    catalog: LocalCatalogIndex,
    results_by_roi: dict[str, dict],
) -> list[CatalogRecord]:
    split_full_lines = results_by_roi.get("split_full", {}).get("lines") or []
    if not split_full_lines:
        return []
    records: list[CatalogRecord] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for query in _title_queries_for_roi("split_full", split_full_lines, layout_hint="split"):
        for record in catalog.exact_lookup(query):
            key = (record.name, record.set_code, record.collector_number)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def _first_crop_for_group(crops: dict[str, Any], group_name: str):
    for crop_name, crop_region in crops.items():
        if crop_name.partition(":")[0] == group_name:
            return crop_region
    return None


def _run_ocr_for_roi_group(image: Any, *, roi_group: str, crop_region: CropRegion | None):
    rotations = ROTATED_TITLE_ROIS.get(roi_group, (0,))
    best_result = None
    attempts: list[dict[str, Any]] = []
    for rotation_degrees in rotations:
        active_crop = _rotated_crop_region(crop_region, rotation_degrees)
        result = run_ocr(
            image,
            roi_label=roi_group,
            crop_region=active_crop,
        )
        result.debug["rotation_degrees"] = rotation_degrees
        attempts.append(
            {
                "rotation_degrees": rotation_degrees,
                "line_count": len(result.lines),
                "confidence": result.confidence,
                "outcome": result.debug.get("outcome"),
            }
        )
        if best_result is None or _ocr_result_sort_key(result) > _ocr_result_sort_key(best_result):
            best_result = result
    if best_result is None:
        return run_ocr(image, roi_label=roi_group, crop_region=crop_region)
    best_result.debug["rotation_attempts"] = attempts
    return best_result


def _rotated_crop_region(crop_region: CropRegion | None, rotation_degrees: int) -> CropRegion | None:
    if crop_region is None or rotation_degrees == 0:
        return crop_region
    image_array = getattr(crop_region, "image_array", None)
    if image_array is None:
        return crop_region
    if rotation_degrees == 90:
        rotated = image_array.transpose(1, 0, 2)[::-1, :, :]
    elif rotation_degrees == 270:
        rotated = image_array.transpose(1, 0, 2)[:, ::-1, :]
    elif rotation_degrees == 180:
        rotated = image_array[::-1, ::-1, :]
    else:
        return crop_region
    return CropRegion(
        label=crop_region.label,
        bbox=crop_region.bbox,
        shape=getattr(rotated, "shape", crop_region.shape),
        image_array=rotated,
    )


def _ocr_result_sort_key(result) -> tuple[int, float, int]:
    return (len(result.lines), result.confidence, sum(len(line) for line in result.lines))


@lru_cache(maxsize=4)
def _load_catalog(db_path: str) -> LocalCatalogIndex:
    ensure_catalog_ready(db_path=db_path)
    return LocalCatalogIndex.from_sqlite(db_path)


def _notify(callback, message: str) -> None:
    if callback is not None:
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


def _timed_call(stage_timings: dict[str, float], stage_name: str, function, *args, **kwargs):
    started_at = time.monotonic()
    try:
        return function(*args, **kwargs)
    finally:
        _record_duration(stage_timings, stage_name, started_at)


def _timed_call_supported_kwargs(stage_timings: dict[str, float], stage_name: str, function, *args, **kwargs):
    started_at = time.monotonic()
    try:
        return _call_with_supported_kwargs(function, *args, **kwargs)
    finally:
        _record_duration(stage_timings, stage_name, started_at)


def _record_duration(stage_timings: dict[str, float], stage_name: str, started_at: float) -> None:
    elapsed = round(time.monotonic() - started_at, 4)
    stage_timings[stage_name] = round(stage_timings.get(stage_name, 0.0) + elapsed, 4)


def _deadline_exceeded(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _resolve_visual_deadline(deadline: float | None, config: EngineConfig) -> float | None:
    per_card_cap = max(0.0, config.max_visual_tiebreak_seconds_per_card)
    if per_card_cap <= 0:
        return deadline
    capped_deadline = time.monotonic() + per_card_cap
    if deadline is None:
        return capped_deadline
    return min(deadline, capped_deadline)


class OCR_like:
    def __init__(self, payload: dict[str, Any]):
        self.lines = payload.get("lines", [])
        self.confidence = payload.get("confidence", 0.0)
        self.debug = payload.get("debug", {})


def _best_title_roi_name(
    roi_names: list[str],
    results_by_roi: dict[str, dict],
    *,
    layout_hint: str | None,
) -> str | None:
    title_like_rois = {"planar_title", "standard", "split_full", "split_left", "split_right", "adventure", "transform_back"}
    best_name = None
    best_key = None
    for roi_name in roi_names:
        if roi_name not in title_like_rois:
            continue
        payload = results_by_roi.get(roi_name, {})
        lines = payload.get("lines") or []
        if not lines:
            continue
        confidence = float(payload.get("confidence") or 0.0)
        key = _title_roi_quality_key(
            roi_name,
            lines=lines,
            confidence=confidence,
            layout_hint=layout_hint,
        )
        if best_key is None or key > best_key:
            best_key = key
            best_name = roi_name
    return best_name


def _title_roi_quality_key(
    roi_name: str,
    *,
    lines: list[str],
    confidence: float,
    layout_hint: str | None,
) -> tuple[float, float, float]:
    line_count = len(lines)
    total_chars = sum(len(line.strip()) for line in lines)
    penalty = max(0, line_count - 2) * 0.18
    if (layout_hint or "").lower() == "split" and roi_name == "split_full":
        penalty = max(0, line_count - 3) * 0.05
    return (
        round(confidence - penalty, 4),
        float(total_chars),
        -float(line_count),
    )


def _refine_secondary_rois_for_context(
    secondary_rois: list[str],
    *,
    layout_hint: str | None,
    results_by_roi: dict[str, dict],
    candidates: list[Candidate],
    confidence: float,
) -> list[str]:
    refined = list(secondary_rois)
    if "split_full" in refined and not _should_use_split_full_fallback(
        layout_hint=layout_hint,
        results_by_roi=results_by_roi,
        candidates=candidates,
        confidence=confidence,
    ):
        refined = [roi_name for roi_name in refined if roi_name != "split_full"]
    return refined


def _should_use_split_full_fallback(
    *,
    layout_hint: str | None,
    results_by_roi: dict[str, dict],
    candidates: list[Candidate],
    confidence: float,
) -> bool:
    if (layout_hint or "").lower() != "split":
        return False

    title_payload = results_by_roi.get("planar_title") or results_by_roi.get("standard") or {}
    title_lines = title_payload.get("lines") or []
    title_confidence = float(title_payload.get("confidence") or 0.0)
    if not title_lines:
        return True

    top_candidate = candidates[0] if candidates else None
    runner_up = candidates[1] if len(candidates) > 1 else None
    top_notes = set(getattr(top_candidate, "notes", []) or [])
    top_score = float(getattr(top_candidate, "score", 0.0) or 0.0)
    runner_up_score = float(getattr(runner_up, "score", 0.0) or 0.0)
    score_gap = round(top_score - runner_up_score, 4)
    title_quality = _title_roi_quality_key(
        "planar_title",
        lines=title_lines,
        confidence=title_confidence,
        layout_hint=layout_hint,
    )

    if _has_robust_split_title_read(
        title_lines,
        title_confidence=title_confidence,
        candidate=top_candidate,
        candidates=candidates,
    ):
        return False
    if "exact" in top_notes and confidence >= 0.88 and score_gap >= 0.08:
        return False
    if title_quality >= (0.82, 6.0, -2.0) and "exact" in top_notes:
        return False
    if confidence >= 0.94 and score_gap >= 0.12:
        return False
    return True


def _has_robust_split_title_read(
    title_lines: list[str],
    *,
    title_confidence: float,
    candidate: Candidate | None,
    candidates: list[Candidate],
) -> bool:
    if title_confidence < 0.88:
        return False

    observed_tokens = _split_title_tokens(title_lines)
    expected_tokens = set()
    if candidate is not None:
        notes = set(getattr(candidate, "notes", []) or [])
        if "exact" in notes:
            expected_tokens |= _split_title_tokens([candidate.name])
        elif (
            candidate.set_code is not None
            and "catalog_unavailable" not in notes
            and "title_only" not in notes
            and candidates
            and all(entry.name == candidate.name for entry in candidates)
        ):
            expected_tokens |= _split_title_tokens([candidate.name])

    if not observed_tokens or not expected_tokens:
        return False

    matched = observed_tokens & expected_tokens
    coverage = len(matched) / len(expected_tokens)
    return coverage >= 0.75


def _split_title_tokens(lines: list[str]) -> set[str]:
    tokens: set[str] = set()
    for line in lines:
        for token in re.findall(r"[a-z]+", line.lower()):
            if len(token) >= 3:
                tokens.add(token)
    return tokens


def _persist_saved_detection(image: Any, detection) -> None:
    image_path = getattr(image, "path", None)
    image_hash = getattr(image, "content_hash", None)
    if image_path is None or detection.bbox is None:
        return
    persist_saved_detection(
        image_path,
        image_sha256=image_hash,
        bbox=detection.bbox,
        quad=detection.quad,
    )


VISUAL_SMALL_POOL_MATCH_THRESHOLD = 0.92
VISUAL_SMALL_POOL_MARGIN_THRESHOLD = 0.06


def _match_visual_small_pool_candidates(
    visual_pool_candidates: list[VisualPoolCandidate],
    *,
    art_match_crop,
    catalog: LocalCatalogIndex,
) -> dict[str, Any]:
    observed_fingerprint = compute_art_fingerprint(getattr(art_match_crop, "image_array", None))
    if observed_fingerprint is None:
        return {
            "winner": None,
            "confidence": 0.0,
            "candidates": [],
            "debug": {"used": False, "reason": "unhashable_observed"},
        }

    scored: list[tuple[VisualPoolCandidate, float]] = []
    for candidate in visual_pool_candidates:
        fingerprint = candidate.observed_art_fingerprint
        if not isinstance(fingerprint, dict) or not fingerprint:
            continue
        similarity = art_fingerprint_similarity(observed_fingerprint, fingerprint)
        scored.append((candidate, similarity))

    if not scored:
        return {
            "winner": None,
            "confidence": 0.0,
            "candidates": [],
            "debug": {"used": False, "reason": "no_visual_pool_candidates"},
        }

    scored.sort(key=lambda item: (-item[1], item[0].name, item[0].set_code or "", item[0].collector_number or ""))
    best_candidate, best_similarity = scored[0]
    second_similarity = scored[1][1] if len(scored) > 1 else 0.0
    margin = round(best_similarity - second_similarity, 4)
    candidate_payloads = [
        candidate
        for candidate in (
            _candidate_from_visual_pool_entry(pool_candidate, score=similarity, catalog=catalog)
            for pool_candidate, similarity in scored
        )
        if candidate is not None
    ]

    debug = {
        "used": False,
        "reason": "not_distinctive",
        "best_similarity": round(best_similarity, 4),
        "margin": margin,
        "comparisons": [
            {
                "name": pool_candidate.name,
                "set_code": pool_candidate.set_code,
                "collector_number": pool_candidate.collector_number,
                "similarity": round(similarity, 4),
            }
            for pool_candidate, similarity in scored[:10]
        ],
    }
    if best_similarity < VISUAL_SMALL_POOL_MATCH_THRESHOLD or margin < VISUAL_SMALL_POOL_MARGIN_THRESHOLD:
        return {
            "winner": None,
            "confidence": 0.0,
            "candidates": candidate_payloads,
            "debug": debug,
        }

    winner = _candidate_from_visual_pool_entry(
        best_candidate,
        score=min(1.0, round(best_similarity + min(0.06, margin * 0.5), 4)),
        catalog=catalog,
    )
    if winner is None:
        return {
            "winner": None,
            "confidence": 0.0,
            "candidates": candidate_payloads,
            "debug": {"used": False, "reason": "winner_not_in_catalog", **debug},
        }

    candidate_payloads = [winner] + [
        candidate
        for candidate in candidate_payloads
        if _candidate_identity(candidate) != _candidate_identity(winner)
    ]
    debug["used"] = True
    debug["reason"] = "matched"
    return {
        "winner": winner,
        "confidence": winner.score,
        "candidates": candidate_payloads,
        "debug": debug,
    }


def _candidate_from_visual_pool_entry(
    pool_candidate: VisualPoolCandidate,
    *,
    score: float,
    catalog: LocalCatalogIndex,
) -> Candidate | None:
    record = catalog.find_record(
        name=pool_candidate.name,
        set_code=pool_candidate.set_code,
        collector_number=pool_candidate.collector_number,
    )
    if record is None:
        return None
    return Candidate(
        name=record.name,
        score=score,
        scryfall_id=record.scryfall_id,
        oracle_id=record.oracle_id,
        set_code=record.set_code,
        collector_number=record.collector_number,
        notes=["observed_art_pool_match"],
    )


def _candidate_identity(candidate: Candidate) -> tuple[str, str | None, str | None]:
    return (candidate.name, candidate.set_code, candidate.collector_number)
