from pathlib import Path
from functools import lru_cache
from typing import Any

from .catalog.local_index import LocalCatalogIndex
from .config import EngineConfig
from .detector import detect_card
from .matcher import match_candidates
from .models import RecognitionResult
from .normalize import normalize_card
from .ocr import run_ocr
from .roi import resolve_roi_groups_for_layout
from .scorer import score_candidates
from .set_symbol import rerank_candidates_by_set_symbol, should_skip_secondary_ocr
from .utils.image_io import load_image

TITLE_FIRST_ROIS = {"standard", "split_left", "split_right", "adventure", "transform_back"}


def recognize_card(image: Any, *, progress_callback=None) -> RecognitionResult:
    _notify(progress_callback, "Preparing image input...")
    prepared_image = _prepare_image_input(image)
    config = EngineConfig()
    catalog = _load_catalog(config.catalog_path)
    _notify(progress_callback, "Detecting card bounds...")
    detection = detect_card(prepared_image)
    layout_hint = getattr(prepared_image, "layout_hint", getattr(prepared_image, "layout", "normal"))
    tried_rois = resolve_roi_groups_for_layout(
        layout_hint,
        enabled_groups=config.enabled_roi_groups,
        cycle_order=config.roi_cycle_order,
    )
    _notify(progress_callback, "Normalizing card image...")
    normalized = normalize_card(prepared_image, detection.bbox, quad=detection.quad, roi_groups=tried_rois)

    results_by_roi: dict[str, dict] = {}
    title_rois = [roi_group for roi_group in tried_rois if roi_group in TITLE_FIRST_ROIS]
    secondary_rois = [roi_group for roi_group in tried_rois if roi_group not in TITLE_FIRST_ROIS and roi_group != "set_symbol"]

    ocr_results = []
    for roi_group in title_rois:
        _notify(progress_callback, f"Running OCR for ROI: {roi_group}...")
        result = run_ocr(
            normalized.normalized_image,
            roi_label=roi_group,
            crop_region=_first_crop_for_group(normalized.crops, roi_group),
        )
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
    _notify(progress_callback, "Matching OCR text against catalog...")
    candidates = match_candidates(
        ocr.lines,
        limit=config.candidate_count,
        catalog=catalog,
        results_by_roi=results_by_roi,
        layout_hint=layout_hint,
    )
    set_symbol_debug = {"used": False, "reason": "not_attempted"}
    set_symbol_crop = _first_crop_for_group(normalized.crops, "set_symbol")
    if candidates and set_symbol_crop is not None:
        _notify(progress_callback, "Comparing set symbol against top candidates...")
        set_symbol_result = rerank_candidates_by_set_symbol(
            candidates,
            observed_crop=set_symbol_crop,
            catalog=catalog,
            progress_callback=progress_callback,
        )
        candidates = set_symbol_result.candidates
        set_symbol_debug = set_symbol_result.debug
    _notify(progress_callback, "Scoring candidates...")
    best_name, confidence = score_candidates(candidates)

    if secondary_rois and not should_skip_secondary_ocr(candidates, confidence):
        for roi_group in secondary_rois:
            _notify(progress_callback, f"Running OCR for ROI: {roi_group}...")
            result = run_ocr(
                normalized.normalized_image,
                roi_label=roi_group,
                crop_region=_first_crop_for_group(normalized.crops, roi_group),
            )
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
        candidates = match_candidates(
            ocr.lines,
            limit=config.candidate_count,
            catalog=catalog,
            results_by_roi=results_by_roi,
            layout_hint=layout_hint,
        )
        if set_symbol_crop is not None:
            set_symbol_result = rerank_candidates_by_set_symbol(
                candidates,
                observed_crop=set_symbol_crop,
                catalog=catalog,
                progress_callback=progress_callback,
            )
            candidates = set_symbol_result.candidates
            set_symbol_debug = set_symbol_result.debug
        _notify(progress_callback, "Scoring candidates...")
        best_name, confidence = score_candidates(candidates)
    elif secondary_rois:
        _notify(progress_callback, "Skipping secondary OCR after confident title and set-symbol match...")
    _notify(progress_callback, f"Recognition complete: {best_name or 'no match'}")

    return RecognitionResult(
        bbox=detection.bbox,
        best_name=best_name,
        confidence=confidence,
        ocr_lines=ocr.lines,
        top_k_candidates=candidates,
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
    return LocalCatalogIndex.from_sqlite(db_path)


def _notify(callback, message: str) -> None:
    if callback is not None:
        callback(message)


class OCR_like:
    def __init__(self, payload: dict[str, Any]):
        self.lines = payload.get("lines", [])
        self.confidence = payload.get("confidence", 0.0)
        self.debug = payload.get("debug", {})
