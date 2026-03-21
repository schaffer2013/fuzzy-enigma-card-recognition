import json

from card_engine.evaluation import (
    build_random_sample,
    evaluate_fixture_set,
    infer_expected_name,
    infer_fixture_expectation,
)
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


def test_infer_fixture_expectation_reads_set_and_collector_from_sidecar(tmp_path):
    image_path = tmp_path / "jade-avenger-f81500be.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))
    image_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "expected_name": "Jade Avenger",
                "expected_set_code": "mh2",
                "expected_collector_number": "167",
            }
        ),
        encoding="utf-8",
    )

    image = load_image(image_path)
    expectation = infer_fixture_expectation(image)

    assert expectation.name == "Jade Avenger"
    assert expectation.set_code == "mh2"
    assert expectation.collector_number == "167"


def test_evaluate_fixture_set_reports_name_set_and_art_accuracy(monkeypatch, tmp_path):
    fixture_a = tmp_path / "echoing-courage-deadbeef.png"
    fixture_b = tmp_path / "jade-avenger-f81500be.png"
    fixture_a.write_bytes(_minimal_png(width=80, height=100))
    fixture_b.write_bytes(_minimal_png(width=80, height=100))
    fixture_a.with_suffix(".json").write_text(
        json.dumps(
            {
                "expected_name": "Echoing Courage",
                "expected_set_code": "dst",
                "expected_collector_number": "61",
            }
        ),
        encoding="utf-8",
    )
    fixture_b.with_suffix(".json").write_text(
        json.dumps(
            {
                "expected_name": "Jade Avenger",
                "expected_set_code": "mh2",
                "expected_collector_number": "167",
            }
        ),
        encoding="utf-8",
    )

    predictions = {
        "echoing-courage-deadbeef.png": RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Echoing Courage",
            confidence=0.91,
            top_k_candidates=[
                Candidate(name="Echoing Courage", score=0.9, set_code="dst", collector_number="61")
            ],
            active_roi="standard",
            tried_rois=["standard", "type_line", "lower_text"],
        ),
        "jade-avenger-f81500be.png": RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Jade Avenger",
            confidence=0.63,
            top_k_candidates=[
                Candidate(name="Jade Avenger", score=0.7, set_code="mh2", collector_number="356"),
                Candidate(name="Jade Avenger", score=0.68, set_code="mh2", collector_number="167"),
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
    assert summary.set_scored_count == 2
    assert summary.art_scored_count == 2
    assert summary.top1_accuracy == 1.0
    assert summary.top5_accuracy == 1.0
    assert summary.set_accuracy == 1.0
    assert summary.art_accuracy == 0.5
    assert summary.roi_usage == {"lower_text": 1, "standard": 1}
    assert summary.error_classes == {"correct_top1": 1, "wrong_art": 1}


def test_build_random_sample_fetches_requested_count(monkeypatch, tmp_path):
    calls: list[int] = []

    def fake_fetch_random_card_image(output_dir, *, client_factory=None, downloader=None, max_cached_cards=60):
        index = len(calls) + 1
        calls.append(max_cached_cards)
        image_path = tmp_path / f"card-{index:03d}.png"
        image_path.write_bytes(_minimal_png(width=80, height=100))
        image_path.with_suffix(".json").write_text(
            json.dumps({"expected_name": f"Card {index}"}),
            encoding="utf-8",
        )
        return image_path

    monkeypatch.setattr("card_engine.evaluation.fetch_random_card_image", fake_fetch_random_card_image)

    output_dir = build_random_sample(tmp_path / "random-sample", count=3)

    assert output_dir.name == "random-sample"
    assert calls == [3, 3, 3]


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
