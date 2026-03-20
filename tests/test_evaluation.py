import json

from card_engine.evaluation import evaluate_fixture_set, infer_expected_name
from card_engine.models import Candidate, RecognitionResult
from card_engine.utils.image_io import load_image


def test_infer_expected_name_prefers_sidecar_standard(tmp_path):
    image_path = tmp_path / "echoing-courage-deadbeef.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))
    image_path.with_suffix(".json").write_text(
        json.dumps({"ocr_text_by_roi": {"standard": "Echoing Courage"}}),
        encoding="utf-8",
    )

    image = load_image(image_path)

    assert infer_expected_name(image) == "Echoing Courage"


def test_infer_expected_name_falls_back_to_filename(tmp_path):
    image_path = tmp_path / "jade-avenger-f81500be.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))

    image = load_image(image_path)

    assert infer_expected_name(image) == "Jade Avenger"


def test_evaluate_fixture_set_reports_accuracy(monkeypatch, tmp_path):
    fixture_a = tmp_path / "echoing-courage-deadbeef.png"
    fixture_b = tmp_path / "jade-avenger-f81500be.png"
    fixture_a.write_bytes(_minimal_png(width=80, height=100))
    fixture_b.write_bytes(_minimal_png(width=80, height=100))
    fixture_a.with_suffix(".json").write_text(
        json.dumps({"ocr_text_by_roi": {"standard": "Echoing Courage"}}),
        encoding="utf-8",
    )
    fixture_b.with_suffix(".json").write_text(
        json.dumps({"ocr_text_by_roi": {"standard": "Jade Avenger"}}),
        encoding="utf-8",
    )

    predictions = {
        "echoing-courage-deadbeef.png": RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Echoing Courage",
            confidence=0.91,
            top_k_candidates=[Candidate(name="Echoing Courage", score=0.9)],
            active_roi="standard",
            tried_rois=["standard", "type_line", "lower_text"],
        ),
        "jade-avenger-f81500be.png": RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Jade Guardian",
            confidence=0.63,
            top_k_candidates=[
                Candidate(name="Jade Guardian", score=0.7),
                Candidate(name="Jade Avenger", score=0.68),
            ],
            active_roi="lower_text",
            tried_rois=["standard", "type_line", "lower_text"],
        ),
    }

    monkeypatch.setattr(
        "card_engine.evaluation.recognize_card",
        lambda image: predictions[image.path.name],
    )

    summary = evaluate_fixture_set(tmp_path)

    assert summary.fixture_count == 2
    assert summary.scored_count == 2
    assert summary.top1_accuracy == 0.5
    assert summary.top5_accuracy == 1.0
    assert summary.roi_usage == {"lower_text": 1, "standard": 1}
    assert summary.error_classes == {"correct_in_top5": 1, "correct_top1": 1}


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
