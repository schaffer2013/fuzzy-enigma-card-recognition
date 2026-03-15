from typing import Any

from .detector import detect_card
from .matcher import match_candidates
from .models import RecognitionResult
from .normalize import normalize_card
from .ocr import run_ocr
from .scorer import score_candidates


def recognize_card(image: Any) -> RecognitionResult:
    detection = detect_card(image)
    normalized = normalize_card(image, detection.bbox)
    ocr = run_ocr(normalized.normalized_image, roi_label="standard")
    candidates = match_candidates(ocr.lines)
    best_name, confidence = score_candidates(candidates)

    return RecognitionResult(
        bbox=detection.bbox,
        best_name=best_name,
        confidence=confidence,
        ocr_lines=ocr.lines,
        top_k_candidates=candidates,
        active_roi="standard",
        tried_rois=["standard"],
        debug={
            "detection": detection.debug,
            "normalization": {"crop_count": len(normalized.crops)},
            "ocr": ocr.debug,
        },
    )
