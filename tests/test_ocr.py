from card_engine.ocr import run_ocr


def test_ocr_placeholder_returns_empty_lines():
    result = run_ocr(image=object(), roi_label="standard")
    assert result.lines == []
    assert result.debug["roi_label"] == "standard"
