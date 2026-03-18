from pathlib import Path
from typing import Any

from .config import EngineConfig
from .detector import detect_card
from .matcher import match_candidates
from .models import RecognitionResult
from .normalize import normalize_card
from .ocr import run_ocr
from .roi import resolve_roi_groups_for_layout
from .scorer import score_candidates
from .utils.image_io import load_image


def recognize_card(image: Any) -> RecognitionResult:
    prepared_image = _prepare_image_input(image)
    config = EngineConfig()
    detection = detect_card(prepared_image)
    layout_hint = getattr(prepared_image, "layout_hint", getattr(prepared_image, "layout", "normal"))
    tried_rois = resolve_roi_groups_for_layout(
        layout_hint,
        enabled_groups=config.enabled_roi_groups,
        cycle_order=config.roi_cycle_order,
    )
    normalized = normalize_card(prepared_image, detection.bbox, quad=detection.quad, roi_groups=tried_rois)

    ocr_results = [run_ocr(normalized.normalized_image, roi_label=roi_group) for roi_group in tried_rois]
    active_index = next((index for index, result in enumerate(ocr_results) if result.lines), 0)
    active_roi = tried_rois[active_index] if tried_rois else None
    ocr = ocr_results[active_index] if ocr_results else run_ocr(normalized.normalized_image, roi_label=None)
    candidates = match_candidates(ocr.lines)
    best_name, confidence = score_candidates(candidates)

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
                "results_by_roi": {
                    roi_group: {"line_count": len(result.lines), "debug": result.debug}
                    for roi_group, result in zip(tried_rois, ocr_results)
                },
                **ocr.debug,
            },
        },
    )


def _prepare_image_input(image: Any) -> Any:
    if isinstance(image, (str, Path)):
        return load_image(image)

    return image
