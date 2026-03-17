from pathlib import Path
from typing import Any

from .detector import detect_card
from .matcher import match_candidates
from .models import RecognitionResult
from .normalize import normalize_card
from .ocr import run_ocr
from .scorer import score_candidates
from .utils.image_io import load_image


def recognize_card(image: Any) -> RecognitionResult:
    prepared_image = _prepare_image_input(image)
    detection = detect_card(prepared_image)
    normalized = normalize_card(prepared_image, detection.bbox)
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
            "image": {
                "source": str(getattr(prepared_image, "path", "")) or type(prepared_image).__name__,
                "shape": getattr(prepared_image, "shape", None),
            },
            "detection": detection.debug,
            "normalization": {"crop_count": len(normalized.crops)},
            "ocr": ocr.debug,
        },
    )


def _prepare_image_input(image: Any) -> Any:
    if isinstance(image, (str, Path)):
        return load_image(image)

    return image
