import json

from card_engine.catalog.build_catalog import build_catalog
from card_engine.models import Candidate, RecognitionResult
from card_engine.art_prehash import count_prehash_cache_entries
from card_engine.catalog.query import OfflineCatalogQuery
from card_engine.ui.state import UIState
from card_engine.ui.views import discover_fixture_paths, format_fixture_summary, format_recognition_summary, format_status_summary
from card_engine.utils.image_io import LoadedImage


def test_discover_fixture_paths_filters_supported_suffixes(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "alpha.png").write_bytes(b"png")
    (fixtures_dir / "beta.jpg").write_bytes(b"jpg")
    (fixtures_dir / "notes.txt").write_text("ignore me", encoding="utf-8")

    paths = discover_fixture_paths(fixtures_dir)

    assert [path.name for path in paths] == ["alpha.png", "beta.jpg"]


def test_format_fixture_summary_handles_empty_state():
    state = UIState()

    summary = format_fixture_summary(state)

    assert "No fixture images found." in summary


def test_format_fixture_summary_includes_loaded_image_metadata(tmp_path):
    fixture_path = tmp_path / "fixture.png"
    fixture_path.write_bytes(b"png")
    state = UIState(
        fixture_paths=[fixture_path],
        current_image=LoadedImage(
            fixture_path,
            "png",
            120,
            168,
            ocr_text_by_roi={"standard": "Lightning Bolt", "type_line": "Instant"},
        ),
        active_backend="moss_machine",
    )

    summary = format_fixture_summary(state)

    assert "Format: png" in summary
    assert "Dimensions: 120 x 168" in summary
    assert "OCR metadata: standard, type_line" in summary
    assert "Backend: moss_machine" in summary


def test_format_recognition_summary_lists_candidates():
    result = RecognitionResult(
        bbox=(0, 0, 80, 100),
        best_name="Lightning Bolt",
        confidence=0.95,
        ocr_lines=["lightning bolt"],
        top_k_candidates=[
            Candidate(name="Lightning Bolt", score=0.95, set_code="M11", notes=["exact"]),
            Candidate(name="Chain Lightning", score=0.61),
        ],
        active_roi="standard",
        tried_rois=["standard"],
        debug={
            "timings": {
                "detect_card": 0.0012,
                "total": 0.0045,
            },
            "ocr": {
                "results_by_roi": {
                    "standard": {
                        "lines": ["Lightning Bolt"],
                        "confidence": 0.99,
                        "debug": {"backend": "simulated_hint"},
                    }
                }
            },
            "backend": {"requested": "moss_machine", "effective": "fuzzy_enigma", "fallback_reason": "image_path_required"},
        },
    )

    summary = format_recognition_summary(result)

    assert "Best name: Lightning Bolt" in summary
    assert "Best set: M11" in summary
    assert "Backend: fuzzy_enigma (requested=moss_machine; fallback=image_path_required)" in summary
    assert "OCR by ROI:" in summary
    assert "backend=simulated_hint" in summary
    assert "Timings (s):" in summary
    assert "detect_card: 0.0012" in summary
    assert "Candidates:" in summary
    assert "Lightning Bolt" in summary
    assert "Tried ROIs: standard" in summary


def test_format_status_summary_includes_active_backend(tmp_path):
    fixture_path = tmp_path / "fixture.png"
    fixture_path.write_bytes(b"png")
    state = UIState(fixture_paths=[fixture_path], active_backend="moss_machine")

    summary = format_status_summary(state)

    assert "Backend: moss_machine" in summary


def test_format_recognition_summary_shows_error_when_recognition_failed():
    summary = format_recognition_summary(None, error_message="max() iterable argument is empty")

    assert "Recognition failed." in summary
    assert "max() iterable argument is empty" in summary


def test_count_hashable_catalog_cards_counts_rows_with_image_uris(tmp_path):
    db_path = tmp_path / "cards.sqlite3"
    source_path = tmp_path / "default-cards.json"
    source_path.write_text(
        json.dumps(
            [
                {
                    "id": "card-1",
                    "name": "Opt",
                    "set": "XLN",
                    "collector_number": "65",
                    "lang": "en",
                    "layout": "normal",
                    "image_uris": {"png": "https://img.example/opt.png"},
                },
                {
                    "id": "card-2",
                    "name": "Island",
                    "set": "XLN",
                    "collector_number": "267",
                    "lang": "en",
                    "layout": "normal",
                },
            ]
        ),
        encoding="utf-8",
    )

    build_catalog(str(db_path), str(source_path))

    assert OfflineCatalogQuery.from_sqlite(db_path).count_hashable_printed_cards() == 1


def test_count_prehash_cache_entries_ignores_cache_metadata(tmp_path, monkeypatch):
    cache_dir = tmp_path / "art_match_refs"
    cache_dir.mkdir()
    (cache_dir / "_cache_meta.json").write_text("{}", encoding="utf-8")
    (cache_dir / "one.json").write_text("{}", encoding="utf-8")
    (cache_dir / "two.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("card_engine.art_prehash.ART_MATCH_CACHE_DIR", cache_dir)

    assert count_prehash_cache_entries() == 2
