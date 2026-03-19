from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from .normalize import CropRegion
from .utils.text_normalize import normalize_text

OCR_LOG_PATH = Path("data") / "cache" / "ocr_logs" / "ocr_attempts.jsonl"
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
    attempt_log = _base_attempt_log(image=image, roi_label=roi_label, crop_region=crop_region)

    if _resolve_ocr_input(image, crop_region) is None:
        attempt_log["result"] = "no_pixel_input"
        _write_ocr_log(attempt_log)
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug=_build_debug(
                backend="unavailable",
                roi_label=roi_label,
                crop_region=crop_region,
                source=image,
                normalized_lines=[],
                attempts=attempt_log["attempts"],
                outcome="no_pixel_input",
            ),
        )

    rapid_result = _run_rapidocr_backend(image, roi_label=roi_label, crop_region=crop_region, attempt_log=attempt_log)
    if rapid_result is not None:
        _write_ocr_log(attempt_log)
        return rapid_result

    paddle_result = _run_paddleocr_backend(image, roi_label=roi_label, crop_region=crop_region, attempt_log=attempt_log)
    if paddle_result is not None:
        _write_ocr_log(attempt_log)
        return paddle_result

    attempt_log["result"] = "no_backend_result"
    _write_ocr_log(attempt_log)
    return OCRResult(
        lines=[],
        confidence=0.0,
        debug=_build_debug(
            backend="unavailable",
            roi_label=roi_label,
            crop_region=crop_region,
            source=image,
            normalized_lines=[],
            attempts=attempt_log["attempts"],
            outcome="no_backend_result",
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
    attempts: list[dict[str, Any]],
    outcome: str,
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
            attempts=attempts,
            outcome=outcome,
        ),
    )


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


def _run_paddleocr_backend(
    image: Any,
    *,
    roi_label: str | None,
    crop_region: CropRegion | None,
    attempt_log: dict[str, Any],
) -> OCRResult | None:
    global _PADDLE_OCR_DISABLED_REASON
    attempt = _begin_backend_attempt(attempt_log, "paddleocr")
    if find_spec("paddleocr") is None:
        attempt["status"] = "module_missing"
        return None
    if _PADDLE_OCR_DISABLED_REASON is not None:
        attempt["status"] = "disabled"
        attempt["reason"] = _PADDLE_OCR_DISABLED_REASON
        return None

    ocr_input = _resolve_ocr_input(image, crop_region)
    if ocr_input is None:
        attempt["status"] = "no_input"
        return None

    try:
        ocr_engine = _get_paddle_ocr_instance()
        raw_result = ocr_engine.predict(ocr_input)
        lines, confidences = _extract_paddle_lines(raw_result)
    except Exception as exc:
        _PADDLE_OCR_DISABLED_REASON = f"{type(exc).__name__}: {exc}"
        attempt["status"] = "error"
        attempt["reason"] = _PADDLE_OCR_DISABLED_REASON
        return None

    attempt["status"] = "success" if lines else "empty"
    attempt["line_count"] = len(lines)
    confidence = (sum(confidences) / len(confidences)) if confidences else 0.0
    attempt["confidence"] = round(confidence, 4)
    attempt_log["result"] = attempt["status"]

    result = _result_from_lines(
        lines,
        confidence=confidence,
        backend="paddleocr",
        roi_label=roi_label,
        crop_region=crop_region,
        source=image,
        attempts=attempt_log["attempts"],
        outcome=attempt["status"],
    )
    result.debug["crop_applied"] = crop_region is not None
    return result


def _run_rapidocr_backend(
    image: Any,
    *,
    roi_label: str | None,
    crop_region: CropRegion | None,
    attempt_log: dict[str, Any],
) -> OCRResult | None:
    attempt = _begin_backend_attempt(attempt_log, "rapidocr")
    if find_spec("rapidocr_onnxruntime") is None:
        attempt["status"] = "module_missing"
        return None

    ocr_input = _resolve_ocr_input(image, crop_region)
    if ocr_input is None:
        attempt["status"] = "no_input"
        return None

    try:
        ocr_engine = _get_rapidocr_instance()
        raw_result, elapsed = ocr_engine(ocr_input)
    except Exception as exc:
        attempt["status"] = "error"
        attempt["reason"] = f"{type(exc).__name__}: {exc}"
        return None

    entries = raw_result or []
    lines = [entry[1] for entry in entries if len(entry) > 1 and entry[1]]
    confidences = [float(entry[2]) for entry in entries if len(entry) > 2]
    confidence = (sum(confidences) / len(confidences)) if confidences else 0.0

    attempt["status"] = "success" if lines else "empty"
    attempt["line_count"] = len(lines)
    attempt["confidence"] = round(confidence, 4)
    attempt["timings"] = elapsed
    attempt_log["result"] = attempt["status"]

    result = _result_from_lines(
        lines,
        confidence=confidence,
        backend="rapidocr",
        roi_label=roi_label,
        crop_region=crop_region,
        source=image,
        attempts=attempt_log["attempts"],
        outcome=attempt["status"],
    )
    result.debug["crop_applied"] = crop_region is not None
    result.debug["timings"] = elapsed
    return result


def _resolve_ocr_input(image: Any, crop_region: CropRegion | None) -> Any | None:
    if crop_region is not None and getattr(crop_region, "image_array", None) is not None:
        return crop_region.image_array

    for source in _iter_sources(image):
        for attr_name in ("image_array", "pixels", "array"):
            value = getattr(source, attr_name, None)
            if value is not None:
                return value

    return None


def _iter_sources(image: Any) -> list[Any]:
    sources: list[Any] = []
    for candidate in (image, getattr(image, "source_image", None)):
        if candidate is None:
            continue
        if any(existing is candidate for existing in sources):
            continue
        sources.append(candidate)
    return sources


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


def _base_attempt_log(*, image: Any, roi_label: str | None, crop_region: CropRegion | None) -> dict[str, Any]:
    source_path = getattr(image, "path", None) or getattr(getattr(image, "source_image", None), "path", None)
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": str(source_path) if source_path else None,
        "roi_label": roi_label,
        "crop_label": crop_region.label if crop_region is not None else None,
        "crop_bbox": crop_region.bbox if crop_region is not None else None,
        "crop_shape": crop_region.shape if crop_region is not None else None,
        "has_crop_pixels": bool(crop_region is not None and getattr(crop_region, "image_array", None) is not None),
        "attempts": [],
        "result": "pending",
    }


def _begin_backend_attempt(attempt_log: dict[str, Any], backend: str) -> dict[str, Any]:
    attempt = {"backend": backend, "status": "pending"}
    attempt_log["attempts"].append(attempt)
    return attempt


def _write_ocr_log(payload: dict[str, Any]) -> None:
    try:
        OCR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OCR_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        return


def _build_debug(
    *,
    backend: str,
    roi_label: str | None,
    crop_region: CropRegion | None,
    source: Any,
    normalized_lines: list[str],
    attempts: list[dict[str, Any]],
    outcome: str,
) -> dict[str, Any]:
    crop_bbox = crop_region.bbox if crop_region is not None else None
    crop_shape = crop_region.shape if crop_region is not None else None
    source_path = getattr(source, "path", None) if source is not None else None
    if source_path is None and source is not None:
        source_path = getattr(getattr(source, "source_image", None), "path", None)
    return {
        "backend": backend,
        "roi_label": roi_label,
        "crop_label": crop_region.label if crop_region is not None else None,
        "crop_bbox": crop_bbox,
        "crop_shape": crop_shape,
        "normalized_lines": normalized_lines,
        "source_path": str(source_path) if source_path else None,
        "paddle_disabled_reason": _PADDLE_OCR_DISABLED_REASON,
        "attempts": attempts,
        "outcome": outcome,
        "log_path": str(OCR_LOG_PATH),
    }
