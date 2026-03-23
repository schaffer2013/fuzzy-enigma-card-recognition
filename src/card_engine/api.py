from pathlib import Path
from functools import lru_cache
from typing import Any
import inspect
import time

from .art_match import rerank_candidates_by_art
from .catalog.maintenance import ensure_catalog_ready
from .catalog.local_index import LocalCatalogIndex
from .config import EngineConfig, load_engine_config
from .detector import detect_card
from .fixture_cache import persist_saved_detection
from .matcher import match_candidates
from .models import RecognitionResult
from .normalize import normalize_card
from .ocr import run_ocr
from .roi import resolve_roi_groups_for_layout
from .scorer import score_candidates
from .set_symbol import rerank_candidates_by_set_symbol, should_skip_secondary_ocr
from .utils.image_io import load_image

TITLE_FIRST_ROIS = {"standard", "split_left", "split_right", "adventure", "transform_back"}
VISUAL_ONLY_ROIS = {"set_symbol", "art_match"}


def recognize_card(
    image: Any,
    *,
    progress_callback=None,
    deadline: float | None = None,
    config: EngineConfig | None = None,
) -> RecognitionResult:
    start_time = time.monotonic()
    stage_timings: dict[str, float] = {}
    _notify(progress_callback, "Preparing image input...")
    prepared_image = _timed_call(stage_timings, "prepare_image_input", _prepare_image_input, image)
    config = config or load_engine_config()
    candidate_pool_limit = max(config.candidate_count * 4, config.candidate_count)
    catalog = _timed_call(stage_timings, "load_catalog", _load_catalog, config.catalog_path)
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
    )

    results_by_roi: dict[str, dict] = {}
    title_rois = [roi_group for roi_group in tried_rois if roi_group in TITLE_FIRST_ROIS]
    secondary_rois = [roi_group for roi_group in tried_rois if roi_group not in TITLE_FIRST_ROIS and roi_group not in VISUAL_ONLY_ROIS]

    ocr_results = []
    for roi_group in title_rois:
        _notify(progress_callback, f"Running OCR for ROI: {roi_group}...")
        ocr_start = time.monotonic()
        result = run_ocr(
            normalized.normalized_image,
            roi_label=roi_group,
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

    active_index = next((index for index, result in enumerate(ocr_results) if result.lines), 0)
    active_roi = title_rois[active_index] if title_rois else None
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
    set_symbol_debug = {"used": False, "reason": "not_attempted"}
    art_match_debug = {"used": False, "reason": "not_attempted"}
    set_symbol_crop = _first_crop_for_group(normalized.crops, "set_symbol")
    art_match_crop = _first_crop_for_group(normalized.crops, "art_match")
    visual_deadline = _resolve_visual_deadline(deadline, config)
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
    _notify(progress_callback, "Scoring candidates...")
    best_name, confidence = _timed_call(stage_timings, "score_candidates_primary", score_candidates, candidates)

    if secondary_rois and not _deadline_exceeded(deadline) and not should_skip_secondary_ocr(candidates, confidence):
        for roi_group in secondary_rois:
            if _deadline_exceeded(deadline):
                break
            _notify(progress_callback, f"Running OCR for ROI: {roi_group}...")
            ocr_start = time.monotonic()
            result = run_ocr(
                normalized.normalized_image,
                roi_label=roi_group,
                crop_region=_first_crop_for_group(normalized.crops, roi_group),
            )
            _record_duration(stage_timings, "secondary_ocr", ocr_start)
            results_by_roi[roi_group] = {
                "line_count": len(result.lines),
                "lines": result.lines,
                "confidence": result.confidence,
                "debug": result.debug,
            }
        active_roi = next((roi for roi in tried_rois if results_by_roi.get(roi, {}).get("lines")), active_roi)
        ocr = (
            OCR_like(results_by_roi[active_roi])
            if active_roi and active_roi in results_by_roi
            else ocr
        )
        _notify(progress_callback, "Re-ranking with secondary OCR signals...")
        candidates = _timed_call(
            stage_timings,
            "match_candidates_secondary",
            match_candidates,
            title_match_lines,
            limit=candidate_pool_limit,
            catalog=catalog,
            results_by_roi=results_by_roi,
            layout_hint=layout_hint,
            config=config,
        )
        if set_symbol_crop is not None and not _deadline_exceeded(deadline):
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
        if art_match_crop is not None and not _deadline_exceeded(deadline):
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
        _notify(progress_callback, "Scoring candidates...")
        best_name, confidence = _timed_call(stage_timings, "score_candidates_secondary", score_candidates, candidates)
    elif secondary_rois:
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
            "timings": stage_timings,
        },
    )


def _prepare_image_input(image: Any) -> Any:
    if isinstance(image, (str, Path)):
        return load_image(image)

    return image


def _first_crop_for_group(crops: dict[str, Any], group_name: str):
    for crop_name, crop_region in crops.items():
        if crop_name.partition(":")[0] == group_name:
            return crop_region
    return None


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
