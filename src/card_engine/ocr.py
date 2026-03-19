from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .normalize import CropRegion
from .utils.text_normalize import normalize_text

_TITLE_LIKE_ROIS = {"standard", "split_left", "split_right", "adventure", "transform_back", None}
_PADDLE_OCR_INSTANCE: Any | None = None
_RAPID_OCR_INSTANCE: Any | None = None
_PADDLE_OCR_DISABLED_REASON: str | None = None


@dataclass
class OCRResult:
    lines: list[str] = field(default_factory=list)
    confidence: float = 0.0
    debug: dict[str, Any] = field(default_factory=dict)


def run_ocr(
    image: Any,
    roi_label: str | None = None,
    *,
    crop_region: CropRegion | None = None,
) -> OCRResult:
    rapid_result = _run_rapidocr_backend(image, roi_label=roi_label, crop_region=crop_region)
    if rapid_result is not None:
        return rapid_result

    paddle_result = _run_paddleocr_backend(image, roi_label=roi_label, crop_region=crop_region)
    if paddle_result is not None:
        return paddle_result

    explicit_lines = _extract_explicit_lines(image, roi_label)
    if explicit_lines is not None:
        return _result_from_lines(
            explicit_lines,
            confidence=0.99 if explicit_lines else 0.0,
            backend="simulated_hint",
            roi_label=roi_label,
            crop_region=crop_region,
            source=image,
        )

    filename_lines = _extract_filename_lines(image, roi_label)
    if filename_lines:
        return _result_from_lines(
            filename_lines,
            confidence=0.72,
            backend="filename_fallback",
            roi_label=roi_label,
            crop_region=crop_region,
            source=image,
        )

    if paddle_result is not None:
        return paddle_result

    return OCRResult(
        lines=[],
        confidence=0.0,
        debug=_build_debug(
            backend="unavailable",
            roi_label=roi_label,
            crop_region=crop_region,
            source=image,
            normalized_lines=[],
        ),
    )


def _result_from_lines(
    raw_lines: list[str],
    *,
    confidence: float,
    backend: str,
    roi_label: str | None,
    crop_region: CropRegion | None,
    source: Any,
) -> OCRResult:
    lines = _normalize_display_lines(raw_lines)
    return OCRResult(
        lines=lines,
        confidence=(confidence if lines else 0.0),
        debug=_build_debug(
            backend=backend,
            roi_label=roi_label,
            crop_region=crop_region,
            source=source,
            normalized_lines=[normalize_text(line) for line in lines],
        ),
    )


def _extract_explicit_lines(image: Any, roi_label: str | None) -> list[str] | None:
    for source in _iter_hint_sources(image):
        for attr_name in ("ocr_lines_by_roi", "ocr_text_by_roi"):
            mapping = getattr(source, attr_name, None)
            if isinstance(mapping, dict) and roi_label in mapping:
                return _coerce_lines(mapping.get(roi_label))

        for attr_name in _roi_specific_attrs(roi_label):
            if hasattr(source, attr_name):
                return _coerce_lines(getattr(source, attr_name))

    return None


def _extract_filename_lines(image: Any, roi_label: str | None) -> list[str]:
    if roi_label not in _TITLE_LIKE_ROIS:
        return []

    for source in _iter_hint_sources(image):
        path_value = getattr(source, "path", None)
        if path_value is None:
            continue

        path = Path(path_value)
        title = _title_from_path(path)
        if title:
            return [title]

    return []


def _title_from_path(path: Path) -> str | None:
    stem = path.stem.strip()
    if not stem:
        return None

    stem = re.sub(r"^[0-9]+[-_ ]+", "", stem)
    tokens = [token for token in re.split(r"[-_ ]+", stem) if token]
    if tokens and _looks_generated_suffix(tokens[-1]):
        tokens = tokens[:-1]
    if not tokens:
        return None

    return " ".join(_humanize_token(token) for token in tokens)


def _looks_generated_suffix(token: str) -> bool:
    if len(token) < 6:
        return False
    has_alpha = any(character.isalpha() for character in token)
    has_digit = any(character.isdigit() for character in token)
    return has_alpha and has_digit


def _humanize_token(token: str) -> str:
    if not token:
        return token
    if token.isupper():
        return token
    return token[0].upper() + token[1:].lower()


def _normalize_display_lines(lines: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for line in lines:
        for piece in str(line).splitlines():
            cleaned = " ".join(piece.strip().split())
            if not cleaned:
                continue
            dedupe_key = normalize_text(cleaned)
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized.append(cleaned)
    return normalized


def _coerce_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    return [str(value)]


def _iter_hint_sources(image: Any) -> list[Any]:
    sources: list[Any] = []
    for candidate in (image, getattr(image, "source_image", None)):
        if candidate is None:
            continue
        if any(existing is candidate for existing in sources):
            continue
        sources.append(candidate)
    return sources


def _roi_specific_attrs(roi_label: str | None) -> tuple[str, ...]:
    if roi_label == "type_line":
        return ("type_line_text", "type_line")
    if roi_label == "lower_text":
        return ("lower_text", "oracle_text", "rules_text")
    if roi_label == "split_left":
        return ("split_left_text", "left_title", "left_name")
    if roi_label == "split_right":
        return ("split_right_text", "right_title", "right_name")
    if roi_label == "adventure":
        return ("adventure_title", "adventure_name")
    if roi_label == "transform_back":
        return ("transform_back_title", "back_title", "back_name")
    return ("title_text", "title", "name", "card_name")


def _run_paddleocr_backend(
    image: Any,
    *,
    roi_label: str | None,
    crop_region: CropRegion | None,
) -> OCRResult | None:
    global _PADDLE_OCR_DISABLED_REASON
    if find_spec("paddleocr") is None:
        return None
    if _PADDLE_OCR_DISABLED_REASON is not None:
        return None

    paddle_input = _resolve_paddle_input(image, crop_region)
    if paddle_input is None:
        return None

    try:
        ocr_engine = _get_paddle_ocr_instance()
        raw_result = ocr_engine.predict(paddle_input)
        lines, confidences = _extract_paddle_lines(raw_result)
    except Exception as exc:
        _PADDLE_OCR_DISABLED_REASON = f"{type(exc).__name__}: {exc}"
        return None

    confidence = (sum(confidences) / len(confidences)) if confidences else 0.0

    result = _result_from_lines(
        lines,
        confidence=confidence,
        backend="paddleocr",
        roi_label=roi_label,
        crop_region=crop_region,
        source=image,
    )
    result.debug["crop_applied"] = crop_region is not None
    return result


def _run_rapidocr_backend(
    image: Any,
    *,
    roi_label: str | None,
    crop_region: CropRegion | None,
) -> OCRResult | None:
    if find_spec("rapidocr_onnxruntime") is None:
        return None

    ocr_input = _resolve_paddle_input(image, crop_region)
    if ocr_input is None:
        return None

    try:
        ocr_engine = _get_rapidocr_instance()
        raw_result, elapsed = ocr_engine(ocr_input)
    except Exception:
        return None

    entries = raw_result or []
    lines = [entry[1] for entry in entries if len(entry) > 1 and entry[1]]
    confidences = [float(entry[2]) for entry in entries if len(entry) > 2]
    confidence = (sum(confidences) / len(confidences)) if confidences else 0.0

    result = _result_from_lines(
        lines,
        confidence=confidence,
        backend="rapidocr",
        roi_label=roi_label,
        crop_region=crop_region,
        source=image,
    )
    result.debug["crop_applied"] = crop_region is not None
    result.debug["timings"] = elapsed
    return result


def _resolve_paddle_input(image: Any, crop_region: CropRegion | None) -> Any | None:
    if crop_region is not None and getattr(crop_region, "image_array", None) is not None:
        return crop_region.image_array

    for source in _iter_hint_sources(image):
        for attr_name in ("image_array", "pixels", "array"):
            if not hasattr(source, attr_name):
                continue
            value = getattr(source, attr_name)
            if value is None:
                continue
            if crop_region is None:
                return value

            left, top, width, height = crop_region.bbox
            try:
                cropped = value[top : top + height, left : left + width]
            except Exception:
                cropped = value
            if cropped is not None:
                return cropped

    return None


def _get_paddle_ocr_instance() -> Any:
    global _PADDLE_OCR_INSTANCE
    if _PADDLE_OCR_INSTANCE is None:
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        paddleocr_module = import_module("paddleocr")
        _PADDLE_OCR_INSTANCE = paddleocr_module.PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            lang="en",
        )
    return _PADDLE_OCR_INSTANCE


def _get_rapidocr_instance() -> Any:
    global _RAPID_OCR_INSTANCE
    if _RAPID_OCR_INSTANCE is None:
        rapidocr_module = import_module("rapidocr_onnxruntime")
        _RAPID_OCR_INSTANCE = rapidocr_module.RapidOCR()
    return _RAPID_OCR_INSTANCE


def _extract_paddle_lines(raw_result: Any) -> tuple[list[str], list[float]]:
    lines: list[str] = []
    confidences: list[float] = []

    for item in raw_result or []:
        if hasattr(item, "rec_texts"):
            lines.extend([text for text in getattr(item, "rec_texts", []) if text])
        if hasattr(item, "rec_scores"):
            confidences.extend([float(score) for score in getattr(item, "rec_scores", [])])

        if isinstance(item, dict):
            lines.extend([text for text in item.get("rec_texts", []) if text])
            confidences.extend([float(score) for score in item.get("rec_scores", [])])

    return lines, confidences


def _build_debug(
    *,
    backend: str,
    roi_label: str | None,
    crop_region: CropRegion | None,
    source: Any,
    normalized_lines: list[str],
) -> dict[str, Any]:
    crop_bbox = crop_region.bbox if crop_region is not None else None
    crop_shape = crop_region.shape if crop_region is not None else None
    source_path = getattr(source, "path", None) if source is not None else None
    return {
        "backend": backend,
        "roi_label": roi_label,
        "crop_label": crop_region.label if crop_region is not None else None,
        "crop_bbox": crop_bbox,
        "crop_shape": crop_shape,
        "normalized_lines": normalized_lines,
        "source_path": str(source_path) if source_path else None,
        "paddle_disabled_reason": _PADDLE_OCR_DISABLED_REASON,
    }
