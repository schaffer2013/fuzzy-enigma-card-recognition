from pathlib import Path
import time

import numpy

from card_engine.api import _should_use_split_full_fallback, recognize_card
from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.config import EngineConfig
from card_engine.image_types import EditableLoadedImage
from card_engine.models import Candidate, VisualPoolCandidate
from card_engine.ocr import OCRResult
from card_engine.operational_modes import CandidatePool, ExpectedCard


class DummyImage:
    shape = (100, 80, 3)


def test_recognize_card_returns_result_shape():
    result = recognize_card(DummyImage())
    assert result.bbox == (0, 0, 80, 100)
    assert result.active_roi == "standard"
    assert result.debug["normalization"]["crop_count"] > 0
    assert "total" in result.debug["timings"]
    assert result.debug["timings"]["total"] >= 0.0


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
    image_array = numpy.zeros((120, 90, 3), dtype=numpy.uint8)


def test_recognize_card_reports_layout_specific_tried_rois():
    result = recognize_card(SplitLayoutImage())

    assert result.active_roi == "planar_title"
    assert result.tried_rois == ["planar_title", "split_full", "standard", "art_match", "type_line", "set_symbol", "lower_text"]
    assert "planar_title" in result.debug["normalization"]["roi_groups"]


class PlanarLayoutImage:
    shape = (1490, 1040, 3)
    layout_hint = "planar"
    image_array = numpy.zeros((1490, 1040, 3), dtype=numpy.uint8)


def test_recognize_card_reports_planar_title_roi_first():
    result = recognize_card(PlanarLayoutImage())

    assert result.tried_rois[0] == "planar_title"
    assert "planar_title" in result.debug["normalization"]["roi_groups"]


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

    assert result.active_roi == "planar_title"
    assert result.ocr_lines == []
    assert result.debug["ocr"]["results_by_roi"]["planar_title"]["lines"] == []


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
        content_hash="deadbeef" * 8,
        image_array=numpy.zeros((100, 80, 3), dtype=numpy.uint8),
        card_quad=None,
        roi_overrides={},
    )

    result = recognize_card(editable_image)

    assert seen_roi_labels == ["standard", "type_line", "lower_text"]
    assert result.debug["ocr"]["results_by_roi"]["standard"]["debug"]["backend"] == "fake"


def test_recognize_card_uses_rotated_planar_title_fallback(monkeypatch):
    seen_shapes: list[tuple[int, int, int] | None] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_shapes.append(getattr(crop_region, "shape", None))
        if roi_label == "planar_title" and crop_region is not None and crop_region.shape[1] > crop_region.shape[0]:
            return OCRResult(
                lines=["Sokenzan"],
                confidence=0.92,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Sokenzan",
                normalized_name="sokenzan",
                set_code="OPCA",
                collector_number="72",
                layout="planar",
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(PlanarLayoutImage())

    assert result.best_name == "Sokenzan"
    assert result.active_roi == "planar_title"
    assert result.debug["ocr"]["rotation_degrees"] in (90, 270)
    assert result.debug["ocr"]["results_by_roi"]["planar_title"]["debug"]["rotation_attempts"]
    assert any(shape is not None and shape[1] > shape[0] for shape in seen_shapes)


def test_recognize_card_uses_planar_title_for_split_layout(monkeypatch):
    seen_shapes: list[tuple[int, int, int] | None] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_shapes.append(getattr(crop_region, "shape", None))
        if roi_label == "planar_title" and crop_region is not None and crop_region.shape[1] > crop_region.shape[0]:
            return OCRResult(
                lines=["Boom"],
                confidence=0.91,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Boom // Bust",
                normalized_name="boom bust",
                set_code="TSR",
                collector_number="156",
                layout="split",
                aliases=["Boom"],
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(SplitLayoutImage())

    assert result.best_name == "Boom // Bust"
    assert result.active_roi == "planar_title"
    assert result.debug["ocr"]["rotation_degrees"] in (90, 270)
    assert result.debug["ocr"]["results_by_roi"]["planar_title"]["debug"]["rotation_attempts"]
    assert any(shape is not None and shape[1] > shape[0] for shape in seen_shapes)


def test_recognize_card_stops_split_title_ocr_early_when_planar_title_is_strong(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        if roi_label == "planar_title":
            return OCRResult(
                lines=["Central", "Elevator", "Promising", "Stairs"],
                confidence=0.97,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Central Elevator // Promising Stairs",
                normalized_name="central elevator promising stairs",
                set_code="DSK",
                collector_number="336",
                layout="split",
                aliases=["Central", "Elevator", "Promising", "Stairs"],
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(SplitLayoutImage())

    assert result.best_name == "Central Elevator // Promising Stairs"
    assert seen_roi_labels[:2] == ["planar_title", "planar_title"]
    assert "standard" not in seen_roi_labels


def test_recognize_card_uses_split_full_fallback_for_split_layout(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        if roi_label == "split_full" and crop_region is not None and crop_region.shape[1] > crop_region.shape[0]:
            return OCRResult(
                lines=["Appeal"],
                confidence=0.9,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Appeal // Authority",
                normalized_name="appeal authority",
                set_code="HOU",
                collector_number="152",
                layout="split",
                aliases=["Appeal"],
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(SplitLayoutImage())

    assert result.best_name == "Appeal // Authority"
    assert result.active_roi == "split_full"
    assert result.debug["ocr"]["results_by_roi"]["split_full"]["debug"]["rotation_attempts"]
    assert seen_roi_labels[:2] == ["planar_title", "planar_title"]
    assert "split_full" in seen_roi_labels


def test_recognize_card_skips_split_full_when_primary_split_title_is_exact(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        if roi_label == "planar_title" and crop_region is not None and crop_region.shape[1] > crop_region.shape[0]:
            return OCRResult(
                lines=["Wear", "Tear"],
                confidence=0.93,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=["Instant"] if roi_label == "type_line" else [],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Wear // Tear",
                normalized_name="wear tear",
                set_code="DGM",
                collector_number="135",
                layout="split",
                aliases=["Wear", "Tear"],
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.should_skip_secondary_ocr", lambda candidates, confidence: False)

    result = recognize_card(SplitLayoutImage())

    assert result.best_name == "Wear // Tear"
    assert "split_full" not in seen_roi_labels
    assert seen_roi_labels[:2] == ["planar_title", "planar_title"]


def test_split_full_fallback_is_kept_when_primary_exact_split_title_disagrees():
    should_retry = _should_use_split_full_fallback(
        layout_hint="split",
        results_by_roi={
            "planar_title": {
                "lines": ["Assure", "Assemblo"],
                "confidence": 0.98,
            }
        },
        candidates=[
            Candidate(name="Bind // Liberate", score=0.95, set_code="CMB1", notes=["exact"]),
            Candidate(name="Assure // Assemble", score=0.91, set_code="GRN", notes=["exact"]),
        ],
        confidence=0.95,
    )

    assert should_retry is True


def test_recognize_card_keeps_split_full_when_primary_split_title_is_weak(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        if roi_label == "planar_title":
            return OCRResult(
                lines=["App3a1"],
                confidence=0.51,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        if roi_label == "split_full" and crop_region is not None and crop_region.shape[1] > crop_region.shape[0]:
            return OCRResult(
                lines=["Appeal"],
                confidence=0.9,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Appeal // Authority",
                normalized_name="appeal authority",
                set_code="HOU",
                collector_number="152",
                layout="split",
                aliases=["Appeal"],
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.should_skip_secondary_ocr", lambda candidates, confidence: False)

    result = recognize_card(SplitLayoutImage())

    assert result.best_name == "Appeal // Authority"
    assert "split_full" in seen_roi_labels


def test_recognize_card_allows_split_full_to_reopen_catalog_search(monkeypatch):
    seen_candidate_record_lengths: list[int | None] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        if roi_label == "planar_title":
            return OCRResult(
                lines=["or,"],
                confidence=0.99,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        if roi_label == "split_full":
            return OCRResult(
                lines=["Meat Locker", "2C", "Drowned Diner"],
                confidence=0.95,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Meat Locker // Drowned Diner", normalized_name="", set_code="DSK", layout="split"),
            CatalogRecord(name="Orgg", normalized_name="", set_code="TMP", layout="normal"),
        ]
    )

    def fake_match_candidates(ocr_lines, limit=5, catalog=None, *, results_by_roi=None, layout_hint=None, config=None, candidate_records=None):
        has_split_full = bool(results_by_roi and results_by_roi.get("split_full", {}).get("lines"))
        if not has_split_full:
            return [Candidate(name="Orgg", score=0.4, set_code="TMP", notes=["fuzzy"])]
        seen_candidate_record_lengths.append(None if candidate_records is None else len(candidate_records))
        return [Candidate(name="Meat Locker // Drowned Diner", score=0.9, set_code="DSK", notes=["exact"])]

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.match_candidates", fake_match_candidates)
    monkeypatch.setattr("card_engine.api.should_skip_secondary_ocr", lambda candidates, confidence: False)

    result = recognize_card(SplitLayoutImage())

    assert result.best_name == "Meat Locker // Drowned Diner"
    assert seen_candidate_record_lengths[0] == 1


def test_small_pool_allows_split_full_even_when_secondary_ocr_is_normally_skipped(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        if roi_label == "planar_title":
            return OCRResult(
                lines=["or,"],
                confidence=0.99,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        if roi_label == "split_full":
            return OCRResult(
                lines=["Meat Locker", "2C", "Drowned Diner"],
                confidence=0.95,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        return OCRResult(
            lines=[],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Meat Locker // Drowned Diner",
                normalized_name="",
                set_code="DSK",
                collector_number="65",
                layout="split",
            ),
            CatalogRecord(name="Orgg", normalized_name="", set_code="TMP", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(
        SplitLayoutImage(),
        mode="small_pool",
        expected_card=ExpectedCard(name="Meat Locker // Drowned Diner", set_code="DSK", collector_number="65"),
    )

    assert result.best_name == "Meat Locker // Drowned Diner"
    assert "split_full" in seen_roi_labels


def test_small_pool_skips_split_full_when_primary_split_title_is_robust(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        if roi_label == "planar_title":
            return OCRResult(
                lines=["Central", "Elevator", "Promising", "Stairs"],
                confidence=0.97,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
            )
        if roi_label == "standard":
            return OCRResult(
                lines=[],
                confidence=0.0,
                debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
            )
        return OCRResult(
            lines=["Instant"] if roi_label == "type_line" else [],
            confidence=0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "empty"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Central Elevator // Promising Stairs",
                normalized_name="",
                set_code="DSK",
                collector_number="336",
                layout="split",
                aliases=["Central", "Elevator", "Promising", "Stairs"],
            ),
            CatalogRecord(
                name="Central Elevator // Promising Stairs",
                normalized_name="",
                set_code="DSK",
                collector_number="44",
                layout="split",
                aliases=["Central", "Elevator", "Promising", "Stairs"],
            ),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.should_skip_secondary_ocr", lambda candidates, confidence: False)

    result = recognize_card(
        SplitLayoutImage(),
        mode="small_pool",
        expected_card=ExpectedCard(name="Central Elevator // Promising Stairs", set_code="DSK", collector_number="336"),
    )

    assert result.best_name == "Central Elevator // Promising Stairs"
    assert "split_full" not in seen_roi_labels


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
            CatalogRecord(
                name="Opt",
                normalized_name="",
                scryfall_id="opt-1",
                oracle_id="oracle-opt",
                set_code="XLN",
                type_line="Instant",
                layout="normal",
            ),
            CatalogRecord(name="Opt", normalized_name="", set_code="ALT", type_line="Sorcery", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage())

    assert result.best_name == "Opt"
    assert result.top_k_candidates[0].scryfall_id == "opt-1"
    assert result.top_k_candidates[0].oracle_id == "oracle-opt"
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


def test_recognize_card_reports_stage_timings_for_primary_pipeline(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=["Opt"] if roi_label == "standard" else [],
            confidence=0.9,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", collector_number="65", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage())

    timings = result.debug["timings"]
    for stage_name in ("prepare_image_input", "load_catalog", "detect_card", "normalize_card", "title_ocr", "match_candidates_primary", "score_candidates_primary", "total"):
        assert stage_name in timings
        assert timings[stage_name] >= 0.0


def test_recognize_card_can_skip_secondary_ocr_after_set_symbol_match(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        lines_by_roi = {
            "standard": ["Commander's Plate"],
            "type_line": ["Artifact Equipment"],
            "lower_text": ["Armor changes, but Iron Man endures."],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Commander's Plate", normalized_name="", set_code="SLD", collector_number="1733", layout="normal"),
            CatalogRecord(name="Commander's Plate", normalized_name="", set_code="CMR", collector_number="305", layout="normal"),
        ]
    )

    def fake_set_symbol_rerank(candidates, *, observed_crop, catalog, progress_callback=None):
        boosted = list(candidates)
        boosted[0].score = 0.95
        boosted[0].notes = ["exact", "set_symbol_match"]
        return type("Result", (), {"candidates": boosted, "debug": {"used": True}})()

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_set_symbol", fake_set_symbol_rerank)

    result = recognize_card(DummyImage())

    assert seen_roi_labels == ["standard"]
    assert result.best_name == "Commander's Plate"
    assert result.debug["set_symbol"]["used"] is True


def test_recognize_card_can_force_skip_secondary_ocr(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        lines_by_roi = {
            "standard": ["Island"],
            "type_line": ["Basic Land - Island"],
            "lower_text": [],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Island", normalized_name="", set_code="ELD", collector_number="254", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage(), skip_secondary_ocr=True)

    assert seen_roi_labels == ["standard"]
    assert result.best_name == "Island"
    assert result.debug["mode"]["requested"] == "default"
    assert result.debug["mode"]["effective"] == "default"


def test_recognize_card_reuses_primary_candidate_records_for_secondary_matching(monkeypatch):
    seen_candidate_record_counts: list[int | None] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        lines_by_roi = {
            "standard": ["Rushing Tide Zubera"],
            "type_line": ["Creature - Zubera Spirit"],
            "lower_text": ["When Rushing-Tide Zubera dies, draw a card."],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.8,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    def fake_match_candidates(
        ocr_lines,
        limit=5,
        catalog=None,
        *,
        results_by_roi=None,
        layout_hint=None,
        config=None,
        candidate_records=None,
    ):
        seen_candidate_record_counts.append(None if candidate_records is None else len(candidate_records))
        return [
            Candidate(name="Rushing-Tide Zubera", score=0.72, set_code="CHK", collector_number="95", notes=["fuzzy"]),
            Candidate(name="Dripping-Tongue Zubera", score=0.68, set_code="CHK", collector_number="59", notes=["fuzzy"]),
        ]

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Rushing-Tide Zubera", normalized_name="", set_code="CHK", collector_number="95", layout="normal"),
            CatalogRecord(name="Dripping-Tongue Zubera", normalized_name="", set_code="CHK", collector_number="59", layout="normal"),
            CatalogRecord(name="Lightning Bolt", normalized_name="", set_code="M11", collector_number="146", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.match_candidates", fake_match_candidates)
    monkeypatch.setattr("card_engine.api.should_skip_secondary_ocr", lambda candidates, confidence: False)
    monkeypatch.setattr(
        "card_engine.api.rerank_candidates_by_set_symbol",
        lambda candidates, **kwargs: type("Result", (), {"candidates": candidates, "debug": {"used": False}})(),
    )
    monkeypatch.setattr(
        "card_engine.api.rerank_candidates_by_art",
        lambda candidates, **kwargs: type("Result", (), {"candidates": candidates, "debug": {"used": False}})(),
    )

    recognize_card(DummyImage())

    assert seen_candidate_record_counts == [None, 2, 2]


def test_recognize_card_can_stop_secondary_ocr_after_first_support_roi(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        lines_by_roi = {
            "standard": ["Rushing Tide Zubera"],
            "type_line": ["Creature - Zubera Spirit"],
            "lower_text": ["When Rushing-Tide Zubera dies, draw a card."],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.8,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    call_index = {"value": 0}

    def fake_match_candidates(
        ocr_lines,
        limit=5,
        catalog=None,
        *,
        results_by_roi=None,
        layout_hint=None,
        config=None,
        candidate_records=None,
    ):
        call_index["value"] += 1
        if call_index["value"] == 1:
            return [
                Candidate(name="Rushing-Tide Zubera", score=0.71, set_code="CHK", collector_number="95", notes=["fuzzy"]),
                Candidate(name="Dripping-Tongue Zubera", score=0.69, set_code="CHK", collector_number="59", notes=["fuzzy"]),
            ]
        return [
            Candidate(name="Rushing-Tide Zubera", score=0.92, set_code="CHK", collector_number="95", notes=["exact", "type_line_match"]),
            Candidate(name="Dripping-Tongue Zubera", score=0.62, set_code="CHK", collector_number="59", notes=["fuzzy"]),
        ]

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Rushing-Tide Zubera", normalized_name="", set_code="CHK", collector_number="95", layout="normal"),
            CatalogRecord(name="Dripping-Tongue Zubera", normalized_name="", set_code="CHK", collector_number="59", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.match_candidates", fake_match_candidates)
    monkeypatch.setattr(
        "card_engine.api.rerank_candidates_by_set_symbol",
        lambda candidates, **kwargs: type("Result", (), {"candidates": candidates, "debug": {"used": False}})(),
    )
    monkeypatch.setattr(
        "card_engine.api.rerank_candidates_by_art",
        lambda candidates, **kwargs: type("Result", (), {"candidates": candidates, "debug": {"used": False}})(),
    )

    result = recognize_card(DummyImage())

    assert seen_roi_labels == ["standard", "type_line"]
    assert result.best_name == "Rushing-Tide Zubera"


def test_recognize_card_skips_secondary_ocr_for_unique_exact_primary_match(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        return OCRResult(
            lines=["Cromat"] if roi_label == "standard" else ["Legendary Creature - Illusion"],
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Cromat", normalized_name="", set_code="APC", collector_number="94", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage())

    assert seen_roi_labels == ["standard"]
    assert result.best_name == "Cromat"
    assert result.top_k_candidates[0].set_code == "APC"


def test_recognize_card_supports_explicit_greenfield_mode(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=["Opt"] if roi_label == "standard" else [],
            confidence=0.9,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", collector_number="65", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage(), mode="greenfield")

    assert result.best_name == "Opt"
    assert result.debug["mode"]["requested"] == "greenfield"
    assert result.debug["mode"]["effective"] == "greenfield"
    assert result.debug["mode"]["candidate_count"] == 1


def test_recognize_card_can_short_circuit_small_pool_via_visual_pool(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Forest", normalized_name="", set_code="M21", collector_number="274", layout="normal"),
        ]
    )

    detection = type("Detection", (), {"bbox": (0, 0, 80, 100), "quad": None, "debug": {"method": "fake"}})()
    art_crop = type(
        "Crop",
        (),
        {
            "label": "art_box",
            "bbox": (0, 0, 40, 40),
            "shape": (40, 40, 3),
            "image_array": numpy.zeros((40, 40, 3), dtype=numpy.uint8),
        },
    )()
    normalized = type(
        "Normalized",
        (),
        {
            "normalized_image": DummyImage(),
            "crops": {"art_match:art_box": art_crop},
            "debug_outputs": {"roi_groups": {"art_match": [("art_box", (0, 0, 40, 40))]}},
        },
    )()

    monkeypatch.setattr("card_engine.api.detect_card", lambda image: detection)
    monkeypatch.setattr("card_engine.api.normalize_card", lambda *args, **kwargs: normalized)
    monkeypatch.setattr(
        "card_engine.api.compute_art_fingerprint",
        lambda *_args, **_kwargs: {"gray_dhash": "a" * 64, "edge_dhash": "b" * 64, "mean_bgr": [1.0, 2.0, 3.0]},
    )
    monkeypatch.setattr(
        "card_engine.api.art_fingerprint_similarity",
        lambda observed, reference: 0.98 if reference.get("token") == "island" else 0.72,
    )
    monkeypatch.setattr("card_engine.api.run_ocr", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("OCR should not run")))

    result = recognize_card(
        DummyImage(),
        mode="small_pool",
        candidate_pool=CandidatePool.from_records(catalog.records),
        visual_pool_candidates=[
            VisualPoolCandidate(
                name="Island",
                set_code="M21",
                collector_number="264",
                observed_art_fingerprint={"token": "island"},
            ),
            VisualPoolCandidate(
                name="Forest",
                set_code="M21",
                collector_number="274",
                observed_art_fingerprint={"token": "forest"},
            ),
        ],
        catalog=catalog,
    )

    assert result.best_name == "Island"
    assert result.active_roi == "art_match"
    assert result.debug["small_pool_visual"]["used"] is True
    assert result.top_k_candidates[0].name == "Island"


def test_recognize_card_small_pool_uses_candidate_pool_and_skips_secondary_ocr(monkeypatch):
    seen_roi_labels: list[str] = []

    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        seen_roi_labels.append(roi_label)
        return OCRResult(
            lines=["Island"] if roi_label == "standard" else [],
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    full_catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Island", normalized_name="", set_code="ELD", collector_number="254", layout="normal"),
            CatalogRecord(name="Forest", normalized_name="", set_code="M21", collector_number="274", layout="normal"),
        ]
    )
    pool = CandidatePool.from_records(full_catalog.exact_lookup("Island"))

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: full_catalog)

    result = recognize_card(DummyImage(), mode="small_pool", candidate_pool=pool)

    assert seen_roi_labels == ["standard"]
    assert result.best_name == "Island"
    assert result.debug["mode"]["requested"] == "small_pool"
    assert result.debug["mode"]["effective"] == "small_pool"
    assert result.debug["mode"]["candidate_count"] == 2
    assert result.debug["mode"]["has_candidate_pool"] is True


def test_recognize_card_reevaluation_requires_expected_card(monkeypatch):
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", collector_number="65", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    try:
        recognize_card(DummyImage(), mode="reevaluation")
    except ValueError as exc:
        assert "expected_card" in str(exc)
    else:
        raise AssertionError("Expected reevaluation mode to require expected_card")


def test_recognize_card_reevaluation_can_promote_close_expected_card(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=["Opt"] if roi_label == "standard" else [],
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    def fake_match_candidates(*args, **kwargs):
        return [
            Candidate(name="Opt", score=0.91, set_code="XLN", collector_number="65", notes=["exact"]),
            Candidate(name="Opt", score=0.87, set_code="M11", collector_number="73", notes=["exact", "set_symbol_match"]),
        ]

    def fake_set_symbol_rerank(candidates, **kwargs):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": False}})()

    def fake_art_rerank(candidates, **kwargs):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": False}})()

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api.match_candidates", fake_match_candidates)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_set_symbol", fake_set_symbol_rerank)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_art", fake_art_rerank)

    result = recognize_card(
        DummyImage(),
        mode="reevaluation",
        expected_card=ExpectedCard(name="Opt", set_code="M11", collector_number="73"),
    )

    assert result.best_name == "Opt"
    assert result.top_k_candidates[0].set_code == "M11"
    assert result.debug["mode"]["requested"] == "reevaluation"
    assert result.debug["mode"]["effective"] == "reevaluation"
    assert result.debug["expectation"]["promoted"] is True
    assert result.debug["expectation"]["agrees_with_expected"] is True


def test_recognize_card_reevaluation_can_disagree_when_expected_is_weak(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=["Opt"] if roi_label == "standard" else [],
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    def fake_match_candidates(*args, **kwargs):
        return [
            Candidate(name="Opt", score=0.93, set_code="XLN", collector_number="65", notes=["exact", "set_symbol_match"]),
            Candidate(name="Opt", score=0.62, set_code="M11", collector_number="73", notes=["exact"]),
        ]

    def fake_set_symbol_rerank(candidates, **kwargs):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": False}})()

    def fake_art_rerank(candidates, **kwargs):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": False}})()

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api.match_candidates", fake_match_candidates)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_set_symbol", fake_set_symbol_rerank)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_art", fake_art_rerank)

    result = recognize_card(
        DummyImage(),
        mode="reevaluation",
        expected_card=ExpectedCard(name="Opt", set_code="M11", collector_number="73"),
    )

    assert result.top_k_candidates[0].set_code == "XLN"
    assert result.debug["expectation"]["promoted"] is False
    assert result.debug["expectation"]["agrees_with_expected"] is False


def test_recognize_card_confirmation_scores_expected_printing_directly(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=["Island"] if roi_label == "standard" else [],
            confidence=0.95,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    full_catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Island", normalized_name="", set_code="M21", collector_number="264", layout="normal"),
            CatalogRecord(name="Island", normalized_name="", set_code="ELD", collector_number="254", layout="normal"),
        ]
    )

    def fake_match_candidates(*args, **kwargs):
        return [
            Candidate(name="Island", score=0.89, set_code="M21", collector_number="264", notes=["exact", "set_symbol_match"]),
            Candidate(name="Island", score=0.85, set_code="ELD", collector_number="254", notes=["exact"]),
        ]

    def fake_set_symbol_rerank(candidates, **kwargs):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": True}})()

    def fake_art_rerank(candidates, **kwargs):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": False}})()

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: full_catalog)
    monkeypatch.setattr("card_engine.api.match_candidates", fake_match_candidates)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_set_symbol", fake_set_symbol_rerank)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_art", fake_art_rerank)

    result = recognize_card(
        DummyImage(),
        mode="confirmation",
        expected_card=ExpectedCard(name="Island", set_code="M21", collector_number="264"),
    )

    assert result.best_name == "Island"
    assert result.debug["mode"]["requested"] == "confirmation"
    assert result.debug["mode"]["effective"] == "confirmation"
    assert result.debug["confirmation"]["used"] is True
    assert result.debug["confirmation"]["matches_expected"] is True
    assert result.debug["confirmation"]["expected_rank"] == 1
    assert result.confidence > 0.9


def test_recognize_card_keeps_wider_candidate_pool_before_final_top_k(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        lines_by_roi = {
            "standard": ["Ancient Craving"],
            "lower_text": ["Knowledge demands sacrifice."],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.9,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    records = [
        CatalogRecord(
            name="Ancient Craving",
            normalized_name="",
            set_code=f"S{i:02d}",
            collector_number=str(100 + i),
            layout="normal",
        )
        for i in range(24)
    ]
    records.append(
        CatalogRecord(name="Ancient Craving", normalized_name="", set_code="J22", collector_number="376", layout="normal")
    )
    catalog = LocalCatalogIndex.from_records(records)
    seen_candidate_count = 0

    def fake_set_symbol_rerank(candidates, *, observed_crop, catalog, progress_callback=None):
        nonlocal seen_candidate_count
        seen_candidate_count = len(candidates)
        updated = list(candidates)
        for index, candidate in enumerate(updated):
            if candidate.set_code == "J22":
                updated[index].score = 0.99
                updated[index].notes = ["exact", "set_symbol_match"]
        updated.sort(key=lambda candidate: (-candidate.score, candidate.name))
        return type("Result", (), {"candidates": updated, "debug": {"used": True}})()

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_set_symbol", fake_set_symbol_rerank)

    result = recognize_card(DummyImage())

    assert result.best_name == "Ancient Craving"
    assert result.top_k_candidates[0].set_code == "J22"
    assert seen_candidate_count == 25
    assert len(result.top_k_candidates) == 5


def test_recognize_card_can_promote_candidate_with_art_tiebreak(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        lines_by_roi = {
            "standard": ["Plains"],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.9,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Plains", normalized_name="", set_code="M13", collector_number="230", layout="normal"),
            CatalogRecord(name="Plains", normalized_name="", set_code="DOM", collector_number="250", layout="normal"),
        ]
    )

    def fake_set_symbol_rerank(candidates, *, observed_crop, catalog, progress_callback=None):
        return type("Result", (), {"candidates": list(candidates), "debug": {"used": False, "reason": "not_needed"}})()

    def fake_art_rerank(candidates, *, observed_crop, catalog, progress_callback=None):
        updated = list(candidates)
        for index, candidate in enumerate(updated):
            if candidate.set_code == "DOM":
                updated[index].score = 0.97
                updated[index].notes = ["exact", "layout_match", "art_match"]
        updated.sort(key=lambda candidate: (-candidate.score, candidate.name))
        return type("Result", (), {"candidates": updated, "debug": {"used": True}})()

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_set_symbol", fake_set_symbol_rerank)
    monkeypatch.setattr("card_engine.api.rerank_candidates_by_art", fake_art_rerank)

    result = recognize_card(DummyImage())

    assert result.best_name == "Plains"
    assert result.top_k_candidates[0].set_code == "DOM"
    assert result.debug["art_match"]["used"] is True


def test_recognize_card_does_not_treat_lower_text_as_title_when_title_ocr_is_empty(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        lines_by_roi = {
            "standard": [],
            "type_line": [],
            "lower_text": ["2,", ": Add @ to your mana", "pool."],
        }
        return OCRResult(
            lines=lines_by_roi.get(roi_label, []),
            confidence=0.9 if lines_by_roi.get(roi_label) else 0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="An-Havva Township", normalized_name="", set_code="HML", collector_number="111", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)

    result = recognize_card(DummyImage())

    assert result.best_name is None
    assert result.top_k_candidates == []
    assert result.active_roi == "lower_text"
    assert result.ocr_lines == ["2,", ": Add @ to your mana", "pool."]


def test_recognize_card_fails_when_runtime_budget_is_exceeded(monkeypatch):
    def fake_run_ocr(image, roi_label=None, *, crop_region=None):
        return OCRResult(
            lines=["Opt"] if roi_label == "standard" else [],
            confidence=0.99 if roi_label == "standard" else 0.0,
            debug={"backend": "fake", "roi_label": roi_label, "attempts": [], "outcome": "success"},
        )

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", collector_number="65", layout="normal"),
        ]
    )

    monkeypatch.setattr("card_engine.api.run_ocr", fake_run_ocr)
    monkeypatch.setattr("card_engine.api._load_catalog", lambda _db_path: catalog)
    monkeypatch.setattr("card_engine.api._resolve_recognition_deadline", lambda deadline, config: time.monotonic() - 1)

    result = recognize_card(
        DummyImage(),
        config=EngineConfig(recognition_deadline_seconds=0.001),
    )

    assert result.best_name is None
    assert result.confidence == 0.0
    assert result.top_k_candidates == []
    assert result.debug["deadline"]["exceeded"] is True
    assert result.debug["deadline"]["partial_best_name"] == "Opt"


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
