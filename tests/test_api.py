from pathlib import Path

import numpy

from card_engine.api import recognize_card
from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.ocr import OCRResult
from card_engine.ui.app import EditableLoadedImage


class DummyImage:
    shape = (100, 80, 3)


def test_recognize_card_returns_result_shape():
    result = recognize_card(DummyImage())
    assert result.bbox == (0, 0, 80, 100)
    assert result.active_roi == "standard"
    assert result.debug["normalization"]["crop_count"] > 0


class QuadImage:
    shape = (120, 90, 3)
    card_quad = ((10, 8), (72, 12), (70, 101), (12, 96))


def test_recognize_card_exposes_normalization_debug_for_quad_inputs():
    result = recognize_card(QuadImage())

    assert result.bbox == (10, 8, 62, 93)
    assert result.debug["detection"]["method"] == "explicit_quad"
    assert result.debug["normalization"]["warp_method"] == "quad_to_canonical"


class SplitLayoutImage:
    shape = (120, 90, 3)
    layout_hint = "split"


def test_recognize_card_reports_layout_specific_tried_rois():
    result = recognize_card(SplitLayoutImage())

    assert result.active_roi == "standard"
    assert result.tried_rois == ["standard", "type_line", "lower_text", "split_left", "split_right"]
    assert "split_left" in result.debug["normalization"]["roi_groups"]


def test_recognize_card_accepts_image_path(tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))

    result = recognize_card(image_path)

    assert result.bbox == (0, 0, 80, 100)
    assert result.debug["image"]["source"] == str(image_path)
    assert result.debug["image"]["shape"] == (100, 80, 3)


def test_recognize_card_uses_sidecar_ocr_metadata_for_multiple_rois(tmp_path):
    image_path = tmp_path / "lightning-bolt.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))
    image_path.with_suffix(".json").write_text(
        (
            '{'
            '"layout_hint":"normal",'
            '"ocr_text_by_roi":{'
            '"standard":"Lightning Bolt",'
            '"type_line":"Instant",'
            '"lower_text":"Deal 3 damage to any target."'
            "}"
            "}"
        ),
        encoding="utf-8",
    )

    result = recognize_card(image_path)

    assert result.debug["ocr"]["results_by_roi"]["standard"]["lines"] == []
    assert result.debug["ocr"]["results_by_roi"]["type_line"]["lines"] == []
    assert result.debug["ocr"]["results_by_roi"]["lower_text"]["lines"] == []
    assert result.debug["ocr"]["results_by_roi"]["standard"]["debug"]["outcome"] == "no_pixel_input"


class SimulatedOCRImage:
    shape = (100, 80, 3)
    ocr_text_by_roi = {
        "standard": "Lightning Bolt",
        "type_line": "Instant",
        "lower_text": "Deal 3 damage to any target.",
    }


def test_recognize_card_uses_simulated_ocr_for_candidates():
    result = recognize_card(SimulatedOCRImage())

    assert result.active_roi == "standard"
    assert result.ocr_lines == []
    assert result.best_name is None
    assert result.top_k_candidates == []
    assert result.debug["ocr"]["results_by_roi"]["type_line"]["lines"] == []


class SplitOCRImage:
    shape = (120, 90, 3)
    layout_hint = "split"
    ocr_text_by_roi = {
        "split_left": "Fire",
        "split_right": "Ice",
    }


def test_recognize_card_supports_alternate_roi_ocr_passes():
    result = recognize_card(SplitOCRImage())

    assert result.active_roi == "standard"
    assert result.ocr_lines == []
    assert result.debug["ocr"]["results_by_roi"]["split_right"]["lines"] == []


def test_recognize_card_preserves_pixels_for_ui_editable_images(monkeypatch, tmp_path):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        assert crop_region is not None
        assert crop_region.image_array is not None
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={
                "backend": "fake",
                "roi_label": roi_label,
                "attempts": [{"backend": "fake", "status": "empty"}],
                "outcome": "empty",
            },
        )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)

    image_path = tmp_path / "ui-fixture.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))
    editable_image = EditableLoadedImage(
        path=image_path,
        image_format="png",
        width=80,
        height=100,
        layout_hint="normal",
        image_array=numpy.zeros((100, 80, 3), dtype=numpy.uint8),
        card_quad=None,
        roi_overrides={},
    )

    result = recognize_card(editable_image)

    assert seen_roi_labels == ["standard", "type_line", "lower_text"]
    assert result.debug["ocr"]["results_by_roi"]["standard"]["debug"]["backend"] == "fake"


def test_recognize_card_uses_multi_roi_matching_for_catalog_ranking(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        lines_by_roi = {
            "standard": ["Opt"],
            "type_line": ["Instant"],
            "lower_text": [],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.9,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", type_line="Instant", layout="normal"),
            CatalogRecord(name="Opt", normalized_name="", set_code="ALT", type_line="Sorcery", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage())

    assert result.best_name == "Opt"
    assert result.top_k_candidates[0].set_code == "XLN"
    assert "type_line_match" in (result.top_k_candidates[0].notes or [])
    assert 0.0 <= result.confidence <= 1.0
    assert result.confidence >= result.top_k_candidates[0].score


def test_recognize_card_reports_progress(monkeypatch):
    messages: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)

    recognize_card(DummyImage(), progress_callback=messages.append)

    assert messages[0] == "Preparing image input..."
    assert "Detecting card bounds..." in messages
    assert "Normalizing card image..." in messages
    assert "Running OCR for ROI: standard..." in messages
    assert messages[-1].startswith("Recognition complete:")


def _minimal_png(*, width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
