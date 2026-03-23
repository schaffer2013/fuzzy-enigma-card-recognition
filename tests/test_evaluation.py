import json
import sqlite3
from pathlib import Path
import time

from card_engine.evaluation import (
    BenchmarkModeResult,
    BenchmarkReport,
    benchmark_report_to_json,
    build_random_sample,
    compare_summaries,
    evaluate_benchmark_modes,
    evaluate_random_sample,
    evaluate_fixture_set,
    infer_expected_name,
    infer_fixture_expectation,
    FixtureEvaluation,
    load_summary_json,
    render_benchmark_report,
    render_comparison,
    render_summary,
    resolve_benchmark_modes,
    summary_from_json,
    summary_to_json,
)
from card_engine.config import EngineConfig
from card_engine.eval_pair_store import SimulatedPairStore, build_observed_card_id
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
    assert summary.average_runtime_seconds >= 0.0
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

    assert "Average runtime (s):" in rendered
    assert "Stage timings (avg seconds):" in rendered
    assert "Calibration error (ECE): 0.230" in rendered
    assert "0.6-0.8: count=1, avg_confidence=0.630, accuracy=1.000, gap=0.370" in rendered
    assert payload["average_runtime_seconds"] >= 0.0
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


def test_summary_json_round_trip_preserves_comparison_fields():
    summary = summary_from_json(
        {
            "fixture_count": 2,
            "scored_count": 2,
            "set_scored_count": 1,
            "art_scored_count": 1,
            "top1_accuracy": 0.5,
            "top5_accuracy": 1.0,
            "set_accuracy": 1.0,
            "art_accuracy": 0.0,
            "average_confidence": 0.7,
            "average_scored_confidence": 0.7,
            "average_runtime_seconds": 0.1234,
            "calibration_error": 0.11,
            "calibration_bins": [
                {
                    "lower_bound": 0.6,
                    "upper_bound": 0.8,
                    "fixture_count": 2,
                    "average_confidence": 0.7,
                    "empirical_accuracy": 0.5,
                    "calibration_gap": 0.2,
                }
            ],
            "average_stage_timings": {"total": 0.1234, "title_ocr": 0.01},
            "roi_usage": {"standard": 2},
            "error_classes": {"wrong_top1": 1, "correct_top1": 1},
            "fixtures": [],
        }
    )

    payload = summary_to_json(summary)

    assert payload["average_runtime_seconds"] == 0.1234
    assert payload["average_stage_timings"]["title_ocr"] == 0.01
    assert payload["calibration_bins"][0]["calibration_gap"] == 0.2


def test_load_summary_json_reads_saved_eval_summary(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "fixture_count": 1,
                "scored_count": 1,
                "set_scored_count": 1,
                "art_scored_count": 1,
                "top1_accuracy": 1.0,
                "top5_accuracy": 1.0,
                "set_accuracy": 1.0,
                "art_accuracy": 1.0,
                "average_confidence": 0.9,
                "average_scored_confidence": 0.9,
                "average_runtime_seconds": 0.05,
                "calibration_error": 0.02,
                "calibration_bins": [],
                "average_stage_timings": {"total": 0.05},
                "roi_usage": {"standard": 1},
                "error_classes": {"correct_top1": 1},
                "fixtures": [],
            }
        ),
        encoding="utf-8",
    )

    summary = load_summary_json(summary_path)

    assert summary.fixture_count == 1
    assert summary.average_runtime_seconds == 0.05
    assert summary.average_stage_timings["total"] == 0.05


def test_compare_summaries_reports_metric_and_stage_deltas():
    baseline = summary_from_json(
        {
            "fixture_count": 10,
            "scored_count": 10,
            "set_scored_count": 10,
            "art_scored_count": 10,
            "top1_accuracy": 0.7,
            "top5_accuracy": 0.9,
            "set_accuracy": 0.6,
            "art_accuracy": 0.4,
            "average_confidence": 0.8,
            "average_scored_confidence": 0.8,
            "average_runtime_seconds": 0.5,
            "calibration_error": 0.12,
            "calibration_bins": [
                {
                    "lower_bound": 0.8,
                    "upper_bound": 1.0,
                    "fixture_count": 5,
                    "average_confidence": 0.9,
                    "empirical_accuracy": 0.7,
                    "calibration_gap": 0.2,
                }
            ],
            "average_stage_timings": {"total": 0.5, "title_ocr": 0.1},
            "roi_usage": {},
            "error_classes": {},
            "fixtures": [],
        }
    )
    current = summary_from_json(
        {
            "fixture_count": 10,
            "scored_count": 10,
            "set_scored_count": 10,
            "art_scored_count": 10,
            "top1_accuracy": 0.8,
            "top5_accuracy": 0.95,
            "set_accuracy": 0.7,
            "art_accuracy": 0.5,
            "average_confidence": 0.78,
            "average_scored_confidence": 0.78,
            "average_runtime_seconds": 0.45,
            "calibration_error": 0.08,
            "calibration_bins": [
                {
                    "lower_bound": 0.8,
                    "upper_bound": 1.0,
                    "fixture_count": 5,
                    "average_confidence": 0.88,
                    "empirical_accuracy": 0.8,
                    "calibration_gap": 0.08,
                }
            ],
            "average_stage_timings": {"total": 0.45, "title_ocr": 0.09},
            "roi_usage": {},
            "error_classes": {},
            "fixtures": [],
        }
    )

    comparison = compare_summaries(baseline, current, baseline_label="baseline.json", current_label="candidate run")
    rendered = render_comparison(comparison)

    assert comparison.metric_deltas[0].label == "Name top-1 accuracy"
    assert comparison.metric_deltas[0].delta == 0.1
    assert comparison.metric_deltas[5].label == "Average runtime (s)"
    assert comparison.metric_deltas[5].delta == -0.05
    assert comparison.calibration_gap_deltas[0].label == "0.8-1.0"
    assert comparison.calibration_gap_deltas[0].delta == -0.12
    assert comparison.stage_timing_deltas[0].label == "title_ocr"
    assert "Comparison: candidate run vs baseline.json" in rendered
    assert "Name top-1 accuracy: 0.7000 -> 0.8000 (+0.1000)" in rendered
    assert "Average runtime (s): 0.5000 -> 0.4500 (-0.0500)" in rendered


def test_resolve_benchmark_modes_expands_all_and_dedupes():
    assert resolve_benchmark_modes("default,all,default") == [
        "default",
        "lazy_basic_lands",
        "lazy_all_printings",
    ]


def test_evaluate_benchmark_modes_runs_same_fixture_set_across_modes(monkeypatch, tmp_path):
    seen: list[tuple[str, EngineConfig]] = []

    def fake_summary(name_top1, set_acc):
        return summary_from_json(
            {
                "fixture_count": 3,
                "scored_count": 3,
                "set_scored_count": 3,
                "art_scored_count": 3,
                "top1_accuracy": name_top1,
                "top5_accuracy": name_top1,
                "set_accuracy": set_acc,
                "art_accuracy": set_acc,
                "average_confidence": 0.9,
                "average_scored_confidence": 0.9,
                "average_runtime_seconds": 0.1,
                "calibration_error": 0.05,
                "calibration_bins": [],
                "average_stage_timings": {"total": 0.1},
                "roi_usage": {"standard": 3},
                "error_classes": {"correct_top1": 3},
                "fixtures": [],
            }
        )

    summaries = iter([fake_summary(0.9, 0.8), fake_summary(0.8, 0.7), fake_summary(0.7, 0.6)])

    monkeypatch.setattr("card_engine.evaluation.evaluate_fixture_set", lambda fixtures_dir, *, limit=None, config=None: (seen.append((str(fixtures_dir), config)) or next(summaries)))

    report = evaluate_benchmark_modes(
        tmp_path,
        mode_names=["default", "lazy_basic_lands", "lazy_all_printings"],
        limit=10,
        base_config=EngineConfig(),
    )

    assert [mode_result.mode_name for mode_result in report.mode_results] == [
        "default",
        "lazy_basic_lands",
        "lazy_all_printings",
    ]
    assert all(entry[0] == str(tmp_path) for entry in seen)
    assert seen[0][1].lazy_group_basic_land_printings is False
    assert seen[1][1].lazy_group_basic_land_printings is True
    assert seen[2][1].lazy_default_printing_by_name is True


def test_benchmark_report_renders_and_serializes_mode_accuracy():
    report = BenchmarkReport(
        fixtures_dir="data/sample_outputs/random_eval_cards",
        mode_results=[
            BenchmarkModeResult(
                mode_name="default",
                config_overrides={},
                summary=summary_from_json(
                    {
                        "fixture_count": 3,
                        "scored_count": 3,
                        "set_scored_count": 3,
                        "art_scored_count": 3,
                        "top1_accuracy": 0.9,
                        "top5_accuracy": 0.9,
                        "set_accuracy": 0.8,
                        "art_accuracy": 0.7,
                        "average_confidence": 0.85,
                        "average_scored_confidence": 0.85,
                        "average_runtime_seconds": 0.12,
                        "calibration_error": 0.04,
                        "calibration_bins": [],
                        "average_stage_timings": {"total": 0.12},
                        "roi_usage": {},
                        "error_classes": {},
                        "fixtures": [],
                    }
                ),
            )
        ],
    )

    rendered = render_benchmark_report(report)
    payload = benchmark_report_to_json(report)

    assert "Mode: default" in rendered
    assert "Top-1 accuracy: 0.900" in rendered
    assert payload["mode_results"][0]["mode_name"] == "default"
    assert payload["mode_results"][0]["summary"]["set_accuracy"] == 0.8


def test_evaluate_fixture_set_tracks_expected_vs_actual_pairs(monkeypatch, tmp_path):
    fixture_path = tmp_path / "echoing-courage-deadbeef.png"
    fixture_path.write_bytes(_minimal_png(width=80, height=100))
    fixture_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "expected_name": "Echoing Courage",
                "expected_set_code": "DST",
                "expected_collector_number": "61",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "card_engine.evaluation.recognize_card",
        lambda image, *, deadline=None, config=None: RecognitionResult(
            bbox=(0, 0, 80, 100),
            best_name="Echoing Courage",
            confidence=0.91,
            top_k_candidates=[
                Candidate(name="Echoing Courage", score=0.9, set_code="DST", collector_number="62")
            ],
            active_roi="standard",
            tried_rois=["standard"],
        ),
    )

    db_path = tmp_path / "pairs.sqlite3"
    with SimulatedPairStore(db_path) as pair_store:
        summary = evaluate_fixture_set(tmp_path, pair_store=pair_store)

    assert summary.fixture_count == 1
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT expected_card_id, actual_card_id, seen_count FROM simulated_card_pairs"
        ).fetchone()

    assert row == ("printing:dst:61", "printing:dst:62", 1)


def test_evaluate_benchmark_modes_passes_pair_store_through(monkeypatch, tmp_path):
    seen_pair_stores: list[object] = []

    monkeypatch.setattr(
        "card_engine.evaluation.evaluate_fixture_set",
        lambda fixtures_dir, *, limit=None, config=None, pair_store=None: (
            seen_pair_stores.append(pair_store) or summary_from_json(
                {
                    "fixture_count": 1,
                    "scored_count": 1,
                    "set_scored_count": 1,
                    "art_scored_count": 1,
                    "top1_accuracy": 1.0,
                    "top5_accuracy": 1.0,
                    "set_accuracy": 1.0,
                    "art_accuracy": 1.0,
                    "average_confidence": 0.9,
                    "average_scored_confidence": 0.9,
                    "average_runtime_seconds": 0.1,
                    "calibration_error": 0.0,
                    "calibration_bins": [],
                    "average_stage_timings": {"total": 0.1},
                    "roi_usage": {},
                    "error_classes": {"correct_top1": 1},
                    "fixtures": [],
                }
            )
        ),
    )

    with SimulatedPairStore(tmp_path / "pairs.sqlite3") as pair_store:
        evaluate_benchmark_modes(
            tmp_path,
            mode_names=["default", "lazy_basic_lands"],
            pair_store=pair_store,
        )

    assert len(seen_pair_stores) == 2
    assert all(store is seen_pair_stores[0] for store in seen_pair_stores)


def test_build_observed_card_id_prefers_printing_and_falls_back_to_name():
    assert build_observed_card_id(
        name="Faithless Looting",
        set_code="STA",
        collector_number="38",
        missing_label="unrecognized",
    ) == "printing:sta:38"
    assert build_observed_card_id(
        name="Faithless Looting",
        set_code=None,
        collector_number=None,
        missing_label="unrecognized",
    ) == "name:faithless looting"
    assert build_observed_card_id(
        name=None,
        set_code=None,
        collector_number=None,
        missing_label="unrecognized",
    ) == "unrecognized"


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
