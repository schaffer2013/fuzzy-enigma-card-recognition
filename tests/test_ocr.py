import json

import numpy

import card_engine.ocr as ocr_module
from card_engine.normalize import CropRegion
from card_engine.ocr import OCRResult, run_ocr


def test_run_ocr_returns_unavailable_without_pixel_input(tmp_path, monkeypatch):
    log_path = tmp_path / "ocr.jsonl"
    monkeypatch.setattr(ocr_module, "OCR_LOG_PATH", log_path)

    result = run_ocr(image=object(), roi_label="standard")

    assert result.lines == []
    assert result.debug["backend"] == "unavailable"
    assert result.debug["outcome"] == "no_pixel_input"
    payload = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["result"] == "no_pixel_input"


def test_run_ocr_logs_successful_backend_attempt(tmp_path, monkeypatch):
    log_path = tmp_path / "ocr.jsonl"
    monkeypatch.setattr(ocr_module, "OCR_LOG_PATH", log_path)

    def fake_rapidocr_backend(image, *, roi_label, crop_region, attempt_log):
        attempt = ocr_module._begin_backend_attempt(attempt_log, "rapidocr")
        attempt["status"] = "success"
        attempt["line_count"] = 1
        attempt_log["result"] = "success"
        return OCRResult(
            lines=["Lightning Bolt"],
            confidence=0.91,
            debug={
                "backend": "rapidocr",
                "roi_label": roi_label,
                "attempts": attempt_log["attempts"],
                "outcome": "success",
                "log_path": str(log_path),
            },
        )

    monkeypatch.setattr(ocr_module, "_run_rapidocr_backend", fake_rapidocr_backend)
    monkeypatch.setattr(ocr_module, "_run_paddleocr_backend", lambda *args, **kwargs: None)

    image = type("PixelImage", (), {"image_array": numpy.zeros((40, 80, 3), dtype=numpy.uint8)})()
    crop = CropRegion(label="title_band", bbox=(0, 0, 80, 20), shape=(20, 80, 3), image_array=image.image_array[:20])
    result = run_ocr(image=image, roi_label="standard", crop_region=crop)

    assert result.lines == ["Lightning Bolt"]
    payload = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["attempts"][0]["backend"] == "rapidocr"
    assert payload["attempts"][0]["status"] == "success"


def test_extract_rapidocr_line_boxes_preserves_geometry():
    entries = [
        (
            [[10, 20], [50, 20], [50, 40], [10, 40]],
            "Fire",
            0.98,
        ),
        (
            [[60, 20], [90, 20], [90, 40], [60, 40]],
            "Ice",
            0.95,
        ),
    ]

    line_boxes = ocr_module._extract_rapidocr_line_boxes(entries)

    assert [box["text"] for box in line_boxes] == ["Fire", "Ice"]
    assert line_boxes[0]["bbox"] == [10.0, 20.0, 40.0, 20.0]
    assert line_boxes[0]["points"] == [[10.0, 20.0], [50.0, 20.0], [50.0, 40.0], [10.0, 40.0]]


def test_result_from_lines_keeps_matching_line_boxes():
    result = ocr_module._result_from_lines(
        ["Fire", "Ice"],
        confidence=0.96,
        line_boxes=[
            {"text": "Fire", "normalized_text": "fire", "bbox": [0, 0, 10, 20], "points": [], "confidence": 0.9},
            {"text": "Noise", "normalized_text": "noise", "bbox": [1, 1, 5, 5], "points": [], "confidence": 0.1},
        ],
        backend="rapidocr",
        roi_label="planar_title",
        crop_region=None,
        source=None,
        attempts=[],
        outcome="success",
    )

    assert result.lines == ["Fire", "Ice"]
    assert [box["text"] for box in result.line_boxes] == ["Fire"]
    assert [box["text"] for box in result.debug["line_boxes"]] == ["Fire"]
