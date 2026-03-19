from card_engine.models import Candidate, RecognitionResult
from card_engine.ui.state import UIState
from card_engine.ui.views import discover_fixture_paths, format_fixture_summary, format_recognition_summary
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
    )

    summary = format_fixture_summary(state)

    assert "Format: png" in summary
    assert "Dimensions: 120 x 168" in summary
    assert "OCR metadata: standard, type_line" in summary


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
            "ocr": {
                "results_by_roi": {
                    "standard": {
                        "lines": ["Lightning Bolt"],
                        "confidence": 0.99,
                        "debug": {"backend": "simulated_hint"},
                    }
                }
            }
        },
    )

    summary = format_recognition_summary(result)

    assert "Best name: Lightning Bolt" in summary
    assert "OCR by ROI:" in summary
    assert "backend=simulated_hint" in summary
    assert "Candidates:" in summary
    assert "Lightning Bolt" in summary
    assert "Tried ROIs: standard" in summary
