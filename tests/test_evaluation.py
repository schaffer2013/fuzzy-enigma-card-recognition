import json
from pathlib import Path
import time

from card_engine.evaluation import (
    build_random_sample,
    evaluate_random_sample,
    evaluate_fixture_set,
    infer_expected_name,
    infer_fixture_expectation,
    FixtureEvaluation,
    render_summary,
    summary_to_json,
)
from card_engine.config import EngineConfig
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
    assert summary.average_runtime_seconds == 0.0
    assert summary.calibration_error == 0.23
    assert len(summary.calibration_bins) == 2
    assert summary.calibration_bins[0].lower_bound == 0.6
    assert summary.calibration_bins[0].upper_bound == 0.8
    assert summary.calibration_bins[0].fixture_count == 1
    assert summary.calibration_bins[0].average_confidence == 0.63
    assert summary.calibration_bins[0].empirical_accuracy == 1.0
    assert summary.calibration_bins[0].calibration_gap == 0.37
    assert summary.calibration_bins[1].lower_bound == 0.8
    assert summary.calibration_bins[1].upper_bound == 1.0
    assert summary.calibration_bins[1].fixture_count == 1
    assert summary.calibration_bins[1].average_confidence == 0.91
    assert summary.calibration_bins[1].empirical_accuracy == 1.0
    assert summary.calibration_bins[1].calibration_gap == 0.09
    assert summary.roi_usage == {"lower_text": 1, "standard": 1}
    assert summary.error_classes == {"correct_top1": 1, "wrong_art": 1}
    assert summary.average_stage_timings == {}

    rendered = render_summary(summary)
    payload = summary_to_json(summary)

    assert "Average runtime (s): 0.000" in rendered
    assert "Stage timings (avg seconds):" in rendered
    assert "Calibration error (ECE): 0.230" in rendered
    assert "0.6-0.8: count=1, avg_confidence=0.630, accuracy=1.000, gap=0.370" in rendered
    assert payload["average_runtime_seconds"] == 0.0
    assert payload["average_stage_timings"] == {}
    assert payload["calibration_error"] == 0.23
    assert payload["calibration_bins"][0]["lower_bound"] == 0.6
    assert payload["calibration_bins"][1]["upper_bound"] == 1.0


def test_build_random_sample_fetches_until_time_limit(monkeypatch, tmp_path):
    calls: list[int] = []
    times = iter([0.0, 1.0, 2.0, 3.0])

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

    output_dir = build_random_sample(
        tmp_path / "random-sample",
        time_limit_seconds=2.5,
        clock=lambda: next(times),
    )

    assert output_dir.name == "random-sample"
    assert calls == [1, 2]


def test_evaluate_random_sample_stops_when_time_limit_is_exhausted(monkeypatch, tmp_path):
    fetch_calls: list[int] = []
    evaluated_paths: list[str] = []
    times = iter([0.0, 0.2, 0.4, 0.6, 1.2])

    def fake_fetch_random_card_image(output_dir, *, client_factory=None, downloader=None, max_cached_cards=60):
        index = len(fetch_calls) + 1
        fetch_calls.append(max_cached_cards)
        image_path = tmp_path / "random-eval" / f"card-{index:03d}.png"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(_minimal_png(width=80, height=100))
        image_path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "expected_name": f"Card {index}",
                    "expected_set_code": f"s{index}",
                    "expected_collector_number": str(index),
                }
            ),
            encoding="utf-8",
        )
        return image_path

    def fake_evaluate_fixture(path):
        image_path = tmp_path / "random-eval" / Path(path).name
        evaluated_paths.append(Path(path).name)
        index = len(evaluated_paths)
        return FixtureEvaluation(
            path=str(image_path),
            expected_name=f"Card {index}",
            expected_set_code=f"s{index}",
            expected_collector_number=str(index),
            predicted_name=f"Card {index}",
            predicted_set_code=f"s{index}",
            predicted_collector_number=str(index),
            confidence=0.9,
            name_hit=True,
            set_hit=True,
            art_hit=True,
            top1_hit=True,
            top5_hit=True,
            active_roi="standard",
            tried_rois=["standard"],
            candidate_names=[f"Card {index}"],
            error_class="correct_top1",
        )

    monkeypatch.setattr("card_engine.evaluation.fetch_random_card_image", fake_fetch_random_card_image)
    monkeypatch.setattr("card_engine.evaluation.evaluate_fixture", fake_evaluate_fixture)

    summary = evaluate_random_sample(
        tmp_path / "random-eval",
        time_limit_seconds=1.0,
        clock=lambda: next(times),
    )

    assert fetch_calls == [1, 2]
    assert evaluated_paths == ["card-001.png"]
    assert summary.fixture_count == 1
    assert summary.top1_accuracy == 1.0


def test_evaluate_fixture_set_passes_deadline_and_config_to_recognizer(monkeypatch, tmp_path):
    fixture_path = tmp_path / "opt-deadbeef.png"
    fixture_path.write_bytes(_minimal_png(width=80, height=100))
    fixture_path.with_suffix(".json").write_text(
        json.dumps({"expected_name": "Opt"}),
        encoding="utf-8",
    )

    seen: dict[str, object] = {}

    def fake_recognize_card(image, *, deadline=None, config=None):
        seen["deadline"] = deadline
        seen["config"] = config
        return RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Opt",
            confidence=0.91,
            top_k_candidates=[Candidate(name="Opt", score=0.9, set_code="XLN", collector_number="65")],
            active_roi="standard",
            tried_rois=["standard"],
        )

    monkeypatch.setattr("card_engine.evaluation.recognize_card", fake_recognize_card)

    config = EngineConfig(lazy_default_printing_by_name=True)
    deadline = time.monotonic() + 123.0
    summary = evaluate_fixture_set(tmp_path, deadline=deadline, config=config)

    assert summary.fixture_count == 1
    assert seen["deadline"] == deadline
    assert seen["config"] is config


def test_evaluate_fixture_set_aggregates_stage_timings(monkeypatch, tmp_path):
    fixture_path = tmp_path / "opt-deadbeef.png"
    fixture_path.write_bytes(_minimal_png(width=80, height=100))
    fixture_path.with_suffix(".json").write_text(
        json.dumps({"expected_name": "Opt"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "card_engine.evaluation.recognize_card",
        lambda image, *, deadline=None, config=None: RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Opt",
            confidence=0.91,
            top_k_candidates=[Candidate(name="Opt", score=0.9, set_code="XLN", collector_number="65")],
            active_roi="standard",
            tried_rois=["standard"],
            debug={
                "timings": {
                    "prepare_image_input": 0.0001,
                    "load_catalog": 0.0002,
                    "detect_card": 0.0003,
                    "normalize_card": 0.0004,
                    "title_ocr": 0.0005,
                    "match_candidates_primary": 0.0006,
                    "score_candidates_primary": 0.0007,
                    "total": 0.0028,
                }
            },
        ),
    )

    summary = evaluate_fixture_set(tmp_path)

    assert summary.average_runtime_seconds == 0.0028
    assert summary.average_stage_timings["total"] == 0.0028
    assert summary.average_stage_timings["load_catalog"] == 0.0002


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
