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
