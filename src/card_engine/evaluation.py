from __future__ import annotations

import argparse
from functools import lru_cache
import inspect
import json
import math
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any, Callable

from .api import recognize_card
from .art_prehash import eligible_art_records, prehash_missing_art_records
from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .catalog.scryfall_sync import fetch_random_card_image
from .config import EngineConfig, load_engine_config, parse_roi_expand_factors
from .eval_pair_store import (
    DEFAULT_SIMULATED_PAIR_DB_PATH,
    SimulatedPairStore,
    build_observed_card_id,
)
from .operational_modes import expected_card_from_values
from .utils.image_io import LoadedImage, load_image

SUPPORTED_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
HASHED_NAME_SUFFIX = re.compile(r"-(?P<hash>[0-9a-f]{8})$", re.IGNORECASE)
ProgressCallback = Callable[[str], None]
MAX_RANDOM_TEST_MINUTES = 10.0
DEFAULT_BENCHMARK_MODES = ("default", "lazy_basic_lands", "lazy_all_printings")
DEFAULT_OPERATIONAL_MODES = ("greenfield", "reevaluation", "small_pool", "confirmation")
LONG_RUN_ETA_THRESHOLD_SECONDS = 180.0
DEFAULT_MODE_RUNTIME_ESTIMATES = {
    "default": 7.0,
    "lazy_basic_lands": 6.0,
    "lazy_all_printings": 9.5,
}
DEFAULT_OPERATIONAL_MODE_RUNTIME_ESTIMATES = {
    "greenfield": 7.0,
    "reevaluation": 7.0,
    "small_pool": 4.5,
    "confirmation": 4.5,
}


@dataclass(frozen=True)
class FixtureExpectation:
    name: str | None
    set_code: str | None
    collector_number: str | None
    games: tuple[str, ...] = ()


@dataclass(frozen=True)
class FixtureEvaluation:
    path: str
    expected_name: str | None
    expected_set_code: str | None
    expected_collector_number: str | None
    predicted_name: str | None
    predicted_set_code: str | None
    predicted_collector_number: str | None
    confidence: float
    name_hit: bool
    set_hit: bool
    art_hit: bool
    top1_hit: bool
    top5_hit: bool
    active_roi: str | None
    tried_rois: list[str]
    candidate_names: list[str]
    error_class: str
    runtime_seconds: float = 0.0
    stage_timings: dict[str, float] = field(default_factory=dict)
    expected_games: list[str] = field(default_factory=list)
    expected_is_paper: bool | None = None


@dataclass(frozen=True)
class EvaluationSummary:
    fixture_count: int
    scored_count: int
    set_scored_count: int
    art_scored_count: int
    top1_accuracy: float
    top5_accuracy: float
    set_accuracy: float
    art_accuracy: float
    average_confidence: float
    average_scored_confidence: float
    average_runtime_seconds: float
    median_runtime_seconds: float
    runtime_stddev_seconds: float
    runtime_p95_seconds: float
    max_runtime_seconds: float
    calibration_error: float
    calibration_bins: list["ConfidenceCalibrationBin"]
    average_stage_timings: dict[str, float]
    roi_usage: dict[str, int]
    error_classes: dict[str, int]
    fixtures: list[FixtureEvaluation]


@dataclass(frozen=True)
class ConfidenceCalibrationBin:
    lower_bound: float
    upper_bound: float
    fixture_count: int
    average_confidence: float
    empirical_accuracy: float
    calibration_gap: float


@dataclass(frozen=True)
class MetricDelta:
    label: str
    baseline: float
    current: float
    delta: float


@dataclass(frozen=True)
class EvaluationSummaryComparison:
    baseline_label: str
    current_label: str
    metric_deltas: list[MetricDelta]
    calibration_gap_deltas: list[MetricDelta]
    stage_timing_deltas: list[MetricDelta]


@dataclass(frozen=True)
class BenchmarkModeResult:
    mode_name: str
    config_overrides: dict[str, Any]
    summary: EvaluationSummary


@dataclass(frozen=True)
class BenchmarkReport:
    fixtures_dir: str
    mode_results: list[BenchmarkModeResult]


@dataclass(frozen=True)
class OperationalModeResult:
    mode_name: str
    summary: EvaluationSummary
    implementation_note: str | None = None


@dataclass(frozen=True)
class OperationalModeReport:
    fixtures_dir: str
    mode_results: list[OperationalModeResult]


@dataclass(frozen=True)
class BenchmarkPrehashPlan:
    fixture_count: int
    resolved_fixture_count: int
    oracle_group_count: int
    records: list[CatalogRecord]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate recognition accuracy on a fixture folder.")
    parser.add_argument(
        "--fixtures-dir",
        default="data/cache/random_cards",
        help="Directory containing fixture images to evaluate.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of fixtures to evaluate.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional path to write a JSON summary.",
    )
    parser.add_argument(
        "--compare-to",
        default=None,
        help="Optional path to a prior JSON summary to compare against the current run.",
    )
    parser.add_argument(
        "--benchmark-modes",
        default="default",
        help=(
            "Comma-separated benchmark config modes to run against the same fixture set. "
            "Use 'all' for the built-in suite."
        ),
    )
    parser.add_argument(
        "--operational-modes",
        default="",
        help=(
            "Comma-separated operational recognition modes to run against the same fixture set. "
            "Use 'all' for the built-in suite."
        ),
    )
    parser.add_argument(
        "--random-time-limit-minutes",
        type=float,
        default=0.0,
        help=(
            "Fetch and score random cards until the runtime budget is exhausted. "
            "The limit is checked between cards and may not exceed 10 minutes."
        ),
    )
    parser.add_argument(
        "--random-output-dir",
        default="data/sample_outputs/random_eval_cards",
        help="Output directory used when --random-time-limit-minutes is provided.",
    )
    parser.add_argument(
        "--pair-db",
        default=str(DEFAULT_SIMULATED_PAIR_DB_PATH),
        help=(
            "SQLite database used to track expected-vs-actual card ID pairs for simulated evaluations. "
            "Counts are aggregated across runs and capped to 10,000 unique pairs."
        ),
    )
    parser.add_argument(
        "--roi-expand",
        nargs="+",
        type=float,
        default=None,
        metavar="FACTOR",
        help=(
            "Scale ROI crops from their center point. Pass one value to scale both directions equally, "
            "or pass LONG SHORT to scale the crop's long and short axes separately."
        ),
    )
    return parser


def discover_fixture_paths(fixtures_dir: str | Path) -> list[Path]:
    root = Path(fixtures_dir)
    if not root.exists():
        return []
    return sorted(
        [path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES],
        key=lambda path: str(path).lower(),
    )


def _limited_fixture_paths(fixtures_dir: str | Path, limit: int | None = None) -> list[Path]:
    fixture_paths = discover_fixture_paths(fixtures_dir)
    if limit is not None:
        fixture_paths = fixture_paths[: max(0, limit)]
    return fixture_paths


def evaluate_fixture_set(
    fixtures_dir: str | Path,
    *,
    limit: int | None = None,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_label: str | None = None,
    fixture_evaluator: Callable[..., FixtureEvaluation] | None = None,
) -> EvaluationSummary:
    fixture_paths = _limited_fixture_paths(fixtures_dir, limit)

    config = config or load_engine_config()
    fixture_evaluator = fixture_evaluator or evaluate_fixture
    evaluations: list[FixtureEvaluation] = []
    total_fixtures = len(fixture_paths)
    for index, path in enumerate(fixture_paths, start=1):
        if deadline is not None and time.monotonic() >= deadline:
            break
        if progress_callback is not None:
            label = progress_label or "fixtures"
            _notify(progress_callback, f"[{label}] {index}/{total_fixtures}: {Path(path).name}")
        evaluations.append(
            _call_with_supported_kwargs(
                fixture_evaluator,
                path,
                deadline=deadline,
                config=config,
                pair_store=pair_store,
            )
        )
    return _summarize_evaluations(evaluations)


def evaluate_random_sample(
    output_dir: str | Path,
    *,
    time_limit_seconds: float,
    progress_callback: ProgressCallback | None = None,
    clock: Callable[[], float] = time.monotonic,
    pair_store: SimulatedPairStore | None = None,
) -> EvaluationSummary:
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be greater than 0.")

    deadline = clock() + time_limit_seconds
    config = load_engine_config()
    output_root = Path(output_dir)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    evaluations: list[FixtureEvaluation] = []
    while clock() < deadline:
        card_index = len(evaluations) + 1
        path = fetch_random_card_image(output_root, max_cached_cards=card_index)
        _notify(progress_callback, f"Fetched random card {card_index}: {path.name}")
        if clock() >= deadline:
            break
        evaluations.append(
            _call_with_supported_kwargs(
                evaluate_fixture,
                path,
                deadline=deadline,
                config=config,
                pair_store=pair_store,
            )
        )
        _notify(progress_callback, f"Evaluated random card {card_index}: {path.name}")

    return _summarize_evaluations(evaluations)


def evaluate_benchmark_modes(
    fixtures_dir: str | Path,
    *,
    mode_names: list[str],
    limit: int | None = None,
    base_config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
    progress_callback: ProgressCallback | None = None,
) -> BenchmarkReport:
    resolved_mode_names = resolve_benchmark_modes(mode_names)
    config = base_config or load_engine_config()
    _prehash_benchmark_art_pool(
        fixtures_dir,
        limit=limit,
        config=config,
        progress_callback=progress_callback,
    )
    mode_results: list[BenchmarkModeResult] = []
    for mode_index, mode_name in enumerate(resolved_mode_names, start=1):
        _notify(progress_callback, f"[benchmark] Mode {mode_index}/{len(resolved_mode_names)}: {mode_name}")
        mode_config = config_for_benchmark_mode(config, mode_name)
        mode_results.append(
            BenchmarkModeResult(
                mode_name=mode_name,
                config_overrides=_benchmark_mode_overrides(mode_name),
                summary=_call_with_supported_kwargs(
                    evaluate_fixture_set,
                    fixtures_dir,
                    limit=limit,
                    config=mode_config,
                    pair_store=pair_store,
                    progress_callback=progress_callback,
                    progress_label=f"{mode_name}",
                ),
            )
        )
    return BenchmarkReport(
        fixtures_dir=str(fixtures_dir),
        mode_results=mode_results,
    )


def evaluate_operational_modes(
    fixtures_dir: str | Path,
    *,
    mode_names: list[str],
    limit: int | None = None,
    base_config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
    progress_callback: ProgressCallback | None = None,
) -> OperationalModeReport:
    resolved_mode_names = resolve_operational_modes(mode_names)
    config = base_config or load_engine_config()
    _prehash_benchmark_art_pool(
        fixtures_dir,
        limit=limit,
        config=config,
        progress_callback=progress_callback,
    )
    mode_results: list[OperationalModeResult] = []
    for mode_index, mode_name in enumerate(resolved_mode_names, start=1):
        _notify(progress_callback, f"[operational] Mode {mode_index}/{len(resolved_mode_names)}: {mode_name}")
        fixture_evaluator, implementation_note = fixture_evaluator_for_operational_mode(mode_name)
        mode_results.append(
            OperationalModeResult(
                mode_name=mode_name,
                summary=_call_with_supported_kwargs(
                    evaluate_fixture_set,
                    fixtures_dir,
                    limit=limit,
                    config=config,
                    pair_store=pair_store,
                    progress_callback=progress_callback,
                    progress_label=f"{mode_name}",
                    fixture_evaluator=fixture_evaluator,
                ),
                implementation_note=implementation_note,
            )
        )
    return OperationalModeReport(
        fixtures_dir=str(fixtures_dir),
        mode_results=mode_results,
    )


def fixture_evaluator_for_operational_mode(
    mode_name: str,
) -> tuple[Callable[..., FixtureEvaluation], str | None]:
    if mode_name == "greenfield":
        return evaluate_fixture_greenfield, None
    if mode_name == "reevaluation":
        return evaluate_fixture_reevaluation, "Biases the expected card while still allowing disagreement recovery."
    if mode_name == "small_pool":
        return evaluate_fixture_small_pool, None
    if mode_name == "confirmation":
        return (
            evaluate_fixture_confirmation,
            "Scores agreement with the expected printing and surfaces the strongest contradiction.",
        )
    raise ValueError(f"Unknown operational mode: {mode_name}")


def _summarize_evaluations(evaluations: list[FixtureEvaluation]) -> EvaluationSummary:
    fixture_count = len(evaluations)
    scored = [evaluation for evaluation in evaluations if evaluation.expected_name and _is_paper_fixture(evaluation)]
    set_scored = [evaluation for evaluation in evaluations if evaluation.expected_set_code and _is_paper_fixture(evaluation)]
    art_scored = [
        evaluation
        for evaluation in evaluations
        if evaluation.expected_set_code and evaluation.expected_collector_number
        and _is_paper_fixture(evaluation)
    ]
    scored_count = len(scored)
    set_scored_count = len(set_scored)
    art_scored_count = len(art_scored)
    roi_usage = _count_by_key(evaluation.active_roi for evaluation in evaluations if evaluation.active_roi)
    error_classes = _count_by_key(evaluation.error_class for evaluation in evaluations)

    top1_hits = sum(1 for evaluation in scored if evaluation.top1_hit)
    top5_hits = sum(1 for evaluation in scored if evaluation.top5_hit)
    set_hits = sum(1 for evaluation in set_scored if evaluation.set_hit)
    art_hits = sum(1 for evaluation in art_scored if evaluation.art_hit)
    total_confidence = sum(evaluation.confidence for evaluation in evaluations)
    scored_confidence = sum(evaluation.confidence for evaluation in scored)
    total_runtime = sum(evaluation.runtime_seconds for evaluation in evaluations)
    runtimes = [evaluation.runtime_seconds for evaluation in evaluations]
    calibration_bins = _build_confidence_calibration_bins(scored)
    calibration_error = _expected_calibration_error(calibration_bins, scored_count)

    return EvaluationSummary(
        fixture_count=fixture_count,
        scored_count=scored_count,
        set_scored_count=set_scored_count,
        art_scored_count=art_scored_count,
        top1_accuracy=_safe_ratio(top1_hits, scored_count),
        top5_accuracy=_safe_ratio(top5_hits, scored_count),
        set_accuracy=_safe_ratio(set_hits, set_scored_count),
        art_accuracy=_safe_ratio(art_hits, art_scored_count),
        average_confidence=_safe_ratio(total_confidence, fixture_count),
        average_scored_confidence=_safe_ratio(scored_confidence, scored_count),
        average_runtime_seconds=_safe_ratio(total_runtime, fixture_count),
        median_runtime_seconds=_median(runtimes),
        runtime_stddev_seconds=_population_stddev(runtimes),
        runtime_p95_seconds=_percentile(runtimes, 0.95),
        max_runtime_seconds=max(runtimes) if runtimes else 0.0,
        calibration_error=calibration_error,
        calibration_bins=calibration_bins,
        average_stage_timings=_average_stage_timings(evaluations),
        roi_usage=roi_usage,
        error_classes=error_classes,
        fixtures=evaluations,
    )


def evaluate_fixture(
    path: str | Path,
    *,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
) -> FixtureEvaluation:
    fixture_path = Path(path)
    loaded_image = load_image(fixture_path)
    expected = infer_fixture_expectation(loaded_image)
    started_at = time.monotonic()
    result = _call_with_supported_kwargs(recognize_card, loaded_image, deadline=deadline, config=config)
    runtime_seconds = round(time.monotonic() - started_at, 4)
    return _build_fixture_evaluation(
        fixture_path=fixture_path,
        expected=expected,
        result=result,
        runtime_seconds=runtime_seconds,
        pair_store=pair_store,
    )


def evaluate_fixture_greenfield(
    path: str | Path,
    *,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
) -> FixtureEvaluation:
    return evaluate_fixture_with_mode(
        path,
        mode="greenfield",
        deadline=deadline,
        config=config,
        pair_store=pair_store,
    )


def evaluate_fixture_small_pool(
    path: str | Path,
    *,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
) -> FixtureEvaluation:
    fixture_path = Path(path)
    loaded_image = load_image(fixture_path)
    expected = infer_fixture_expectation(loaded_image)
    started_at = time.monotonic()
    result = _call_with_supported_kwargs(
        recognize_card,
        loaded_image,
        mode="small_pool",
        expected_card=expected_card_from_values(
            name=expected.name,
            set_code=expected.set_code,
            collector_number=expected.collector_number,
        ),
        deadline=deadline,
        config=config or load_engine_config(),
    )
    runtime_seconds = round(time.monotonic() - started_at, 4)
    return _build_fixture_evaluation(
        fixture_path=fixture_path,
        expected=expected,
        result=result,
        runtime_seconds=runtime_seconds,
        pair_store=pair_store,
    )


def evaluate_fixture_reevaluation(
    path: str | Path,
    *,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
) -> FixtureEvaluation:
    return evaluate_fixture_with_mode(
        path,
        mode="reevaluation",
        deadline=deadline,
        config=config,
        pair_store=pair_store,
    )


def evaluate_fixture_confirmation(
    path: str | Path,
    *,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
) -> FixtureEvaluation:
    return evaluate_fixture_with_mode(
        path,
        mode="confirmation",
        deadline=deadline,
        config=config,
        pair_store=pair_store,
    )


def evaluate_fixture_with_mode(
    path: str | Path,
    *,
    mode: str,
    deadline: float | None = None,
    config: EngineConfig | None = None,
    pair_store: SimulatedPairStore | None = None,
) -> FixtureEvaluation:
    fixture_path = Path(path)
    loaded_image = load_image(fixture_path)
    expected = infer_fixture_expectation(loaded_image)
    started_at = time.monotonic()
    result = _call_with_supported_kwargs(
        recognize_card,
        loaded_image,
        mode=mode,
        expected_card=expected_card_from_values(
            name=expected.name,
            set_code=expected.set_code,
            collector_number=expected.collector_number,
        ),
        deadline=deadline,
        config=config or load_engine_config(),
    )
    runtime_seconds = round(time.monotonic() - started_at, 4)
    return _build_fixture_evaluation(
        fixture_path=fixture_path,
        expected=expected,
        result=result,
        runtime_seconds=runtime_seconds,
        pair_store=pair_store,
    )


def _build_fixture_evaluation(
    *,
    fixture_path: Path,
    expected: FixtureExpectation,
    result,
    runtime_seconds: float,
    pair_store: SimulatedPairStore | None,
) -> FixtureEvaluation:
    best_candidate = result.top_k_candidates[0] if result.top_k_candidates else None
    candidate_names = [candidate.name for candidate in result.top_k_candidates]
    predicted_set_code = best_candidate.set_code if best_candidate else None
    predicted_collector_number = best_candidate.collector_number if best_candidate else None
    stage_timings = _coerce_stage_timings(result.debug.get("timings", {}))
    top1_hit = bool(expected.name and result.best_name == expected.name)
    top5_hit = bool(expected.name and expected.name in candidate_names[:5])
    set_hit = bool(
        expected.set_code
        and predicted_set_code
        and predicted_set_code.lower() == expected.set_code.lower()
    )
    art_hit = bool(
        expected.set_code
        and expected.collector_number
        and predicted_set_code
        and predicted_collector_number
        and predicted_set_code.lower() == expected.set_code.lower()
        and str(predicted_collector_number).lower() == str(expected.collector_number).lower()
    )
    if is_paper_expectation(expected):
        _record_simulated_pair(
            pair_store,
            expected_name=expected.name,
            expected_set_code=expected.set_code,
            expected_collector_number=expected.collector_number,
            predicted_name=result.best_name,
            predicted_set_code=predicted_set_code,
            predicted_collector_number=predicted_collector_number,
        )

    return FixtureEvaluation(
        path=str(fixture_path),
        expected_name=expected.name,
        expected_set_code=expected.set_code,
        expected_collector_number=expected.collector_number,
        predicted_name=result.best_name,
        predicted_set_code=predicted_set_code,
        predicted_collector_number=predicted_collector_number,
        confidence=result.confidence,
        name_hit=top1_hit,
        set_hit=set_hit,
        art_hit=art_hit,
        top1_hit=top1_hit,
        top5_hit=top5_hit,
        active_roi=result.active_roi,
        tried_rois=result.tried_rois,
        candidate_names=candidate_names,
        error_class=_classify_result(
            expected_name=expected.name,
            expected_set_code=expected.set_code,
            expected_collector_number=expected.collector_number,
            expected_is_paper=is_paper_expectation(expected),
            predicted_name=result.best_name,
            predicted_set_code=predicted_set_code,
            predicted_collector_number=predicted_collector_number,
            candidate_names=candidate_names,
        ),
        runtime_seconds=stage_timings.get("total", runtime_seconds),
        stage_timings=stage_timings,
        expected_games=list(expected.games),
        expected_is_paper=is_paper_expectation(expected),
    )


def infer_expected_name(image: LoadedImage) -> str | None:
    return infer_fixture_expectation(image).name


def infer_fixture_expectation(image: LoadedImage) -> FixtureExpectation:
    payload = _read_sidecar_payload(image.path)
    expected_name = _coerce_string(payload.get("expected_name"))
    expected_set_code = _coerce_string(payload.get("expected_set_code"))
    expected_collector_number = _coerce_string(payload.get("expected_collector_number"))
    expected_games = _coerce_string_list(payload.get("expected_games"))

    if expected_name is None:
        standard_text = image.ocr_text_by_roi.get("standard")
        if isinstance(standard_text, str) and standard_text.strip():
            expected_name = standard_text.strip()
        else:
            expected_name = _infer_name_from_path(image.path)

    return FixtureExpectation(
        name=expected_name,
        set_code=expected_set_code,
        collector_number=expected_collector_number,
        games=tuple(expected_games),
    )


def _build_benchmark_prehash_plan(
    fixtures_dir: str | Path,
    *,
    limit: int | None = None,
    config: EngineConfig | None = None,
) -> BenchmarkPrehashPlan:
    fixture_paths = _limited_fixture_paths(fixtures_dir, limit)
    if not fixture_paths:
        return BenchmarkPrehashPlan(0, 0, 0, [])

    catalog = _load_catalog_for_evaluation((config or load_engine_config()).catalog_path)
    oracle_records: dict[str, list[CatalogRecord]] = {}
    for record in catalog.records:
        if record.oracle_id:
            oracle_records.setdefault(record.oracle_id, []).append(record)

    selected_by_key: dict[tuple[str | None, str | None, str | None], CatalogRecord] = {}
    resolved_fixture_count = 0
    oracle_group_ids: set[str] = set()

    for fixture_path in fixture_paths:
        expected = infer_fixture_expectation(load_image(fixture_path))
        if not expected.name:
            continue
        record = catalog.find_record(
            name=expected.name,
            set_code=expected.set_code,
            collector_number=expected.collector_number,
        )
        if record is None:
            continue
        resolved_fixture_count += 1
        _add_prehash_record(selected_by_key, record)
        if record.oracle_id:
            oracle_group_ids.add(record.oracle_id)
            for sibling in oracle_records.get(record.oracle_id, []):
                _add_prehash_record(selected_by_key, sibling)

    return BenchmarkPrehashPlan(
        fixture_count=len(fixture_paths),
        resolved_fixture_count=resolved_fixture_count,
        oracle_group_count=len(oracle_group_ids),
        records=eligible_art_records(list(selected_by_key.values())),
    )


def _add_prehash_record(
    selected_by_key: dict[tuple[str | None, str | None, str | None], CatalogRecord],
    record: CatalogRecord,
) -> None:
    key = (
        record.scryfall_id,
        (record.set_code or "").lower() or None,
        str(record.collector_number or "").lower() or None,
    )
    selected_by_key.setdefault(key, record)


def _prehash_benchmark_art_pool(
    fixtures_dir: str | Path,
    *,
    limit: int | None = None,
    config: EngineConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> None:
    plan = _build_benchmark_prehash_plan(fixtures_dir, limit=limit, config=config)
    if not plan.records:
        _notify(progress_callback, "[prehash] No eligible art refs found for this benchmark pool.")
        return

    _notify(
        progress_callback,
        (
            f"[prehash] Warming art refs for {len(plan.records)} printings from "
            f"{plan.resolved_fixture_count}/{plan.fixture_count} fixtures "
            f"across {plan.oracle_group_count} oracle groups."
        ),
    )
    result = prehash_missing_art_records(
        plan.records,
        progress_callback=(
            None
            if progress_callback is None
            else lambda progress: _notify(progress_callback, f"[prehash] {progress.message}")
        ),
    )
    if result.cancelled:
        _notify(
            progress_callback,
            (
                f"[prehash] Cancelled after hashing {result.newly_hashed} new refs "
                f"with {len(result.failures)} failures."
            ),
        )
    else:
        _notify(
            progress_callback,
            (
                f"[prehash] Ready: {result.newly_hashed} new refs, "
                f"{result.already_hashed} already cached, {len(result.failures)} failures."
            ),
        )


def build_random_sample(
    output_dir: str | Path,
    *,
    time_limit_seconds: float,
    progress_callback: ProgressCallback | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Path:
    if time_limit_seconds <= 0:
        raise ValueError("time_limit_seconds must be greater than 0.")

    deadline = clock() + time_limit_seconds
    output_root = Path(output_dir)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    fetched_count = 0
    while clock() < deadline:
        fetched_count += 1
        path = fetch_random_card_image(output_root, max_cached_cards=fetched_count)
        _notify(progress_callback, f"Fetched random card {fetched_count}: {path.name}")
    return output_root


def render_summary(summary: EvaluationSummary) -> str:
    lines = [
        f"Fixture count: {summary.fixture_count}",
        f"Scored fixtures: {summary.scored_count}",
        f"Set-scored fixtures: {summary.set_scored_count}",
        f"Art-scored fixtures: {summary.art_scored_count}",
        f"Name top-1 accuracy: {summary.top1_accuracy:.3f}",
        f"Name top-5 accuracy: {summary.top5_accuracy:.3f}",
        f"Set accuracy: {summary.set_accuracy:.3f}",
        f"Art accuracy: {summary.art_accuracy:.3f}",
        f"Average confidence: {summary.average_confidence:.3f}",
        f"Average scored confidence: {summary.average_scored_confidence:.3f}",
        f"Average runtime (s): {summary.average_runtime_seconds:.3f}",
        f"Median runtime (s): {summary.median_runtime_seconds:.3f}",
        f"Runtime stddev (s): {summary.runtime_stddev_seconds:.3f}",
        f"Runtime p95 (s): {summary.runtime_p95_seconds:.3f}",
        f"Max runtime (s): {summary.max_runtime_seconds:.3f}",
        f"Calibration error (ECE): {summary.calibration_error:.3f}",
        "",
        "Confidence calibration:",
    ]
    if summary.calibration_bins:
        lines.extend(
            "  - "
            f"{calibration_bin.lower_bound:.1f}-{calibration_bin.upper_bound:.1f}: "
            f"count={calibration_bin.fixture_count}, "
            f"avg_confidence={calibration_bin.average_confidence:.3f}, "
            f"accuracy={calibration_bin.empirical_accuracy:.3f}, "
            f"gap={calibration_bin.calibration_gap:.3f}"
            for calibration_bin in summary.calibration_bins
        )
    else:
        lines.append("  - none")

    lines.extend(
        [
        "",
        "ROI usage:",
        ]
    )
    if summary.roi_usage:
        lines.extend(f"  - {roi}: {count}" for roi, count in sorted(summary.roi_usage.items()))
    else:
        lines.append("  - none")

    lines.append("")
    lines.append("Stage timings (avg seconds):")
    if summary.average_stage_timings:
        lines.extend(
            f"  - {stage_name}: {elapsed:.4f}"
            for stage_name, elapsed in sorted(summary.average_stage_timings.items())
        )
    else:
        lines.append("  - none")

    lines.append("")
    lines.append("Error classes:")
    if summary.error_classes:
        lines.extend(f"  - {label}: {count}" for label, count in sorted(summary.error_classes.items()))
    else:
        lines.append("  - none")

    incorrect = [
        fixture
        for fixture in summary.fixtures
        if not fixture.top1_hit and fixture.expected_name and _is_paper_fixture(fixture)
    ]
    lines.append("")
    lines.append("Top mismatches:")
    if incorrect:
        for fixture in incorrect[:10]:
            lines.append(
                "  - "
                f"{Path(fixture.path).name}: expected={fixture.expected_name!r}, "
                f"predicted={fixture.predicted_name!r}, top5={fixture.top5_hit}, "
                f"set={fixture.predicted_set_code!r}, confidence={fixture.confidence:.3f}"
            )
    else:
        lines.append("  - none")

    return "\n".join(lines)


def summary_to_json(summary: EvaluationSummary) -> dict:
    return {
        "fixture_count": summary.fixture_count,
        "scored_count": summary.scored_count,
        "set_scored_count": summary.set_scored_count,
        "art_scored_count": summary.art_scored_count,
        "top1_accuracy": summary.top1_accuracy,
        "top5_accuracy": summary.top5_accuracy,
        "set_accuracy": summary.set_accuracy,
        "art_accuracy": summary.art_accuracy,
        "average_confidence": summary.average_confidence,
        "average_scored_confidence": summary.average_scored_confidence,
        "average_runtime_seconds": summary.average_runtime_seconds,
        "median_runtime_seconds": summary.median_runtime_seconds,
        "runtime_stddev_seconds": summary.runtime_stddev_seconds,
        "runtime_p95_seconds": summary.runtime_p95_seconds,
        "max_runtime_seconds": summary.max_runtime_seconds,
        "calibration_error": summary.calibration_error,
        "calibration_bins": [asdict(calibration_bin) for calibration_bin in summary.calibration_bins],
        "average_stage_timings": summary.average_stage_timings,
        "roi_usage": summary.roi_usage,
        "error_classes": summary.error_classes,
        "fixtures": [asdict(fixture) for fixture in summary.fixtures],
    }


def summary_from_json(payload: dict[str, Any]) -> EvaluationSummary:
    calibration_bins = [
        ConfidenceCalibrationBin(**_filter_dataclass_kwargs(ConfidenceCalibrationBin, item))
        for item in _coerce_list(payload.get("calibration_bins"))
        if isinstance(item, dict)
    ]
    fixtures = [
        FixtureEvaluation(**_filter_dataclass_kwargs(FixtureEvaluation, item))
        for item in _coerce_list(payload.get("fixtures"))
        if isinstance(item, dict)
    ]
    return EvaluationSummary(
        fixture_count=int(payload.get("fixture_count", 0) or 0),
        scored_count=int(payload.get("scored_count", 0) or 0),
        set_scored_count=int(payload.get("set_scored_count", 0) or 0),
        art_scored_count=int(payload.get("art_scored_count", 0) or 0),
        top1_accuracy=float(payload.get("top1_accuracy", 0.0) or 0.0),
        top5_accuracy=float(payload.get("top5_accuracy", 0.0) or 0.0),
        set_accuracy=float(payload.get("set_accuracy", 0.0) or 0.0),
        art_accuracy=float(payload.get("art_accuracy", 0.0) or 0.0),
        average_confidence=float(payload.get("average_confidence", 0.0) or 0.0),
        average_scored_confidence=float(payload.get("average_scored_confidence", 0.0) or 0.0),
        average_runtime_seconds=float(payload.get("average_runtime_seconds", 0.0) or 0.0),
        median_runtime_seconds=float(payload.get("median_runtime_seconds", 0.0) or 0.0),
        runtime_stddev_seconds=float(payload.get("runtime_stddev_seconds", 0.0) or 0.0),
        runtime_p95_seconds=float(payload.get("runtime_p95_seconds", 0.0) or 0.0),
        max_runtime_seconds=float(payload.get("max_runtime_seconds", 0.0) or 0.0),
        calibration_error=float(payload.get("calibration_error", 0.0) or 0.0),
        calibration_bins=calibration_bins,
        average_stage_timings=_coerce_stage_timings(payload.get("average_stage_timings", {})),
        roi_usage=_coerce_count_dict(payload.get("roi_usage", {})),
        error_classes=_coerce_count_dict(payload.get("error_classes", {})),
        fixtures=fixtures,
    )


def load_summary_json(path: str | Path) -> EvaluationSummary:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Summary JSON must contain an object at the top level.")
    return summary_from_json(payload)


def compare_summaries(
    baseline: EvaluationSummary,
    current: EvaluationSummary,
    *,
    baseline_label: str = "baseline",
    current_label: str = "current",
) -> EvaluationSummaryComparison:
    metric_deltas = [
        _metric_delta("Name top-1 accuracy", baseline.top1_accuracy, current.top1_accuracy),
        _metric_delta("Name top-5 accuracy", baseline.top5_accuracy, current.top5_accuracy),
        _metric_delta("Set accuracy", baseline.set_accuracy, current.set_accuracy),
        _metric_delta("Art accuracy", baseline.art_accuracy, current.art_accuracy),
        _metric_delta("Average confidence", baseline.average_confidence, current.average_confidence),
        _metric_delta("Average runtime (s)", baseline.average_runtime_seconds, current.average_runtime_seconds),
        _metric_delta("Median runtime (s)", baseline.median_runtime_seconds, current.median_runtime_seconds),
        _metric_delta("Runtime stddev (s)", baseline.runtime_stddev_seconds, current.runtime_stddev_seconds),
        _metric_delta("Runtime p95 (s)", baseline.runtime_p95_seconds, current.runtime_p95_seconds),
        _metric_delta("Max runtime (s)", baseline.max_runtime_seconds, current.max_runtime_seconds),
        _metric_delta("Calibration error (ECE)", baseline.calibration_error, current.calibration_error),
    ]

    calibration_gap_deltas: list[MetricDelta] = []
    current_bins = {(item.lower_bound, item.upper_bound): item for item in current.calibration_bins}
    for baseline_bin in baseline.calibration_bins:
        key = (baseline_bin.lower_bound, baseline_bin.upper_bound)
        current_bin = current_bins.get(key)
        if current_bin is None:
            continue
        calibration_gap_deltas.append(
            _metric_delta(
                f"{baseline_bin.lower_bound:.1f}-{baseline_bin.upper_bound:.1f}",
                baseline_bin.calibration_gap,
                current_bin.calibration_gap,
            )
        )

    stage_timing_deltas: list[MetricDelta] = []
    stage_names = sorted(set(baseline.average_stage_timings) | set(current.average_stage_timings))
    for stage_name in stage_names:
        stage_timing_deltas.append(
            _metric_delta(
                stage_name,
                baseline.average_stage_timings.get(stage_name, 0.0),
                current.average_stage_timings.get(stage_name, 0.0),
            )
        )

    return EvaluationSummaryComparison(
        baseline_label=baseline_label,
        current_label=current_label,
        metric_deltas=metric_deltas,
        calibration_gap_deltas=calibration_gap_deltas,
        stage_timing_deltas=stage_timing_deltas,
    )


def render_comparison(comparison: EvaluationSummaryComparison) -> str:
    lines = [
        f"Comparison: {comparison.current_label} vs {comparison.baseline_label}",
        "",
        "Metric deltas:",
    ]
    lines.extend(f"  - {_format_delta(metric)}" for metric in comparison.metric_deltas)

    lines.append("")
    lines.append("Calibration gap deltas:")
    if comparison.calibration_gap_deltas:
        lines.extend(f"  - {_format_delta(metric)}" for metric in comparison.calibration_gap_deltas)
    else:
        lines.append("  - none")

    lines.append("")
    lines.append("Stage timing deltas (avg seconds):")
    if comparison.stage_timing_deltas:
        lines.extend(f"  - {_format_delta(metric)}" for metric in comparison.stage_timing_deltas)
    else:
        lines.append("  - none")

    return "\n".join(lines)


def render_benchmark_report(report: BenchmarkReport) -> str:
    lines = [
        f"Benchmark fixtures dir: {report.fixtures_dir}",
        f"Benchmark modes: {', '.join(mode_result.mode_name for mode_result in report.mode_results) or 'none'}",
    ]
    for mode_result in report.mode_results:
        summary = mode_result.summary
        lines.extend(
            [
                "",
                f"Mode: {mode_result.mode_name}",
                f"  Top-1 accuracy: {summary.top1_accuracy:.3f}",
                f"  Top-5 accuracy: {summary.top5_accuracy:.3f}",
                f"  Set accuracy: {summary.set_accuracy:.3f}",
                f"  Art accuracy: {summary.art_accuracy:.3f}",
                f"  Average confidence: {summary.average_confidence:.3f}",
                f"  Average runtime (s): {summary.average_runtime_seconds:.3f}",
                f"  Median runtime (s): {summary.median_runtime_seconds:.3f}",
                f"  Runtime stddev (s): {summary.runtime_stddev_seconds:.3f}",
                f"  Runtime p95 (s): {summary.runtime_p95_seconds:.3f}",
                f"  Max runtime (s): {summary.max_runtime_seconds:.3f}",
                f"  Calibration error (ECE): {summary.calibration_error:.3f}",
            ]
        )
    return "\n".join(lines)


def benchmark_report_to_json(report: BenchmarkReport) -> dict[str, Any]:
    return {
        "fixtures_dir": report.fixtures_dir,
        "mode_results": [
            {
                "mode_name": mode_result.mode_name,
                "config_overrides": mode_result.config_overrides,
                "summary": summary_to_json(mode_result.summary),
            }
            for mode_result in report.mode_results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.operational_modes and args.random_time_limit_minutes:
        parser.error("--operational-modes currently supports saved fixture folders only.")
    try:
        operational_mode_names = resolve_operational_modes(args.operational_modes) if args.operational_modes else []
    except ValueError as exc:
        parser.error(str(exc))
    try:
        benchmark_mode_names = resolve_benchmark_modes(args.benchmark_modes)
    except ValueError as exc:
        parser.error(str(exc))

    if operational_mode_names and args.compare_to:
        parser.error("--compare-to currently supports summary runs only, not operational mode suites.")
    if args.compare_to and len(benchmark_mode_names) > 1:
        parser.error("--compare-to currently supports single-mode runs only.")
    base_config = load_engine_config()
    try:
        roi_expand = parse_roi_expand_factors(args.roi_expand)
    except ValueError as exc:
        parser.error(str(exc))
    if roi_expand is not None:
        base_config = replace(
            base_config,
            roi_expand_long_factor=roi_expand[0],
            roi_expand_short_factor=roi_expand[1],
        )

    with SimulatedPairStore(args.pair_db) as pair_store:
        if operational_mode_names:
            _announce_eta_if_long(
                "Operational mode evaluation",
                _estimate_fixture_run_seconds_for_operational_modes(args.fixtures_dir, operational_mode_names, limit=args.limit),
                progress_callback=_print_console,
            )
            report = evaluate_operational_modes(
                args.fixtures_dir,
                mode_names=operational_mode_names,
                limit=args.limit,
                config=base_config,
                pair_store=pair_store,
                progress_callback=_print_console,
            )
            _print_console(render_operational_mode_report(report))
            _print_console(f"\nTracking simulated pairs in {Path(args.pair_db)}")
            if args.json_out:
                output_path = Path(args.json_out)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(
                    json.dumps(operational_mode_report_to_json(report), indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                _print_console(f"\nWrote JSON summary to {output_path}")
            return 0

        if args.random_time_limit_minutes and len(benchmark_mode_names) > 1:
            if args.random_time_limit_minutes > MAX_RANDOM_TEST_MINUTES:
                parser.error(
                    f"--random-time-limit-minutes may not exceed {MAX_RANDOM_TEST_MINUTES:g} minutes."
                )
            _announce_eta_if_long(
                "Random sample build",
                args.random_time_limit_minutes * 60.0,
                progress_callback=_print_console,
            )
            sample_dir = build_random_sample(
                args.random_output_dir,
                time_limit_seconds=args.random_time_limit_minutes * 60.0,
                progress_callback=_print_console,
            )
            _announce_eta_if_long(
                "Benchmark evaluation",
                _estimate_fixture_run_seconds(sample_dir, benchmark_mode_names, limit=args.limit),
                progress_callback=_print_console,
            )
            report = evaluate_benchmark_modes(
                sample_dir,
                mode_names=benchmark_mode_names,
                limit=args.limit,
                base_config=base_config,
                pair_store=pair_store,
                progress_callback=_print_console,
            )
            _print_console(render_benchmark_report(report))
            _print_console(f"\nTracking simulated pairs in {Path(args.pair_db)}")
            if args.json_out:
                output_path = Path(args.json_out)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(benchmark_report_to_json(report), indent=2, sort_keys=True), encoding="utf-8")
                _print_console(f"\nWrote JSON summary to {output_path}")
            return 0

        if args.random_time_limit_minutes:
            if args.random_time_limit_minutes > MAX_RANDOM_TEST_MINUTES:
                parser.error(
                    f"--random-time-limit-minutes may not exceed {MAX_RANDOM_TEST_MINUTES:g} minutes."
                )
            _announce_eta_if_long(
                "Random sample evaluation",
                args.random_time_limit_minutes * 60.0,
                progress_callback=_print_console,
            )
            summary = evaluate_random_sample(
                args.random_output_dir,
                time_limit_seconds=args.random_time_limit_minutes * 60.0,
                config=base_config,
                progress_callback=_print_console,
                pair_store=pair_store,
            )
        elif len(benchmark_mode_names) > 1:
            _announce_eta_if_long(
                "Benchmark evaluation",
                _estimate_fixture_run_seconds(args.fixtures_dir, benchmark_mode_names, limit=args.limit),
                progress_callback=_print_console,
            )
            report = evaluate_benchmark_modes(
                args.fixtures_dir,
                mode_names=benchmark_mode_names,
                limit=args.limit,
                base_config=base_config,
                pair_store=pair_store,
                progress_callback=_print_console,
            )
            _print_console(render_benchmark_report(report))
            _print_console(f"\nTracking simulated pairs in {Path(args.pair_db)}")
            if args.json_out:
                output_path = Path(args.json_out)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(benchmark_report_to_json(report), indent=2, sort_keys=True), encoding="utf-8")
                _print_console(f"\nWrote JSON summary to {output_path}")
            return 0
        else:
            _announce_eta_if_long(
                "Fixture evaluation",
                _estimate_fixture_run_seconds(
                    args.fixtures_dir,
                    benchmark_mode_names,
                    limit=args.limit,
                    compare_to=args.compare_to,
                ),
                progress_callback=_print_console,
            )
            summary = evaluate_fixture_set(
                args.fixtures_dir,
                limit=args.limit,
                config=base_config,
                pair_store=pair_store,
                progress_callback=_print_console,
                progress_label="default",
            )
        _print_console(render_summary(summary))
        _print_console(f"\nTracking simulated pairs in {Path(args.pair_db)}")

        if args.compare_to:
            baseline_summary = load_summary_json(args.compare_to)
            comparison = compare_summaries(
                baseline_summary,
                summary,
                baseline_label=str(args.compare_to),
                current_label="current run",
            )
            _print_console("")
            _print_console(render_comparison(comparison))

        if args.json_out:
            output_path = Path(args.json_out)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(summary_to_json(summary), indent=2, sort_keys=True), encoding="utf-8")
            _print_console(f"\nWrote JSON summary to {output_path}")

        return 0


def _read_sidecar_payload(image_path: Path) -> dict:
    sidecar_path = image_path.with_suffix(".json")
    if not sidecar_path.exists():
        return {}
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _coerce_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    coerced: list[str] = []
    for item in value:
        normalized = _coerce_string(item)
        if normalized is not None:
            coerced.append(normalized)
    return coerced


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        try:
            callback(message)
        except UnicodeEncodeError:
            callback(str(message).encode("ascii", "replace").decode("ascii"))


def _print_console(message: str = "") -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        safe_message = str(message).encode("ascii", "replace").decode("ascii")
        try:
            sys.stdout.write(safe_message + "\n")
        except UnicodeEncodeError:
            print(safe_message.encode("ascii", "replace").decode("ascii"))


def _call_with_supported_kwargs(function, *args, **kwargs):
    signature = inspect.signature(function)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return function(*args, **kwargs)

    supported_kwargs = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return function(*args, **supported_kwargs)


def _announce_eta_if_long(
    label: str,
    estimated_seconds: float | None,
    *,
    progress_callback: ProgressCallback | None = None,
    now: datetime | None = None,
) -> None:
    if estimated_seconds is None or estimated_seconds <= LONG_RUN_ETA_THRESHOLD_SECONDS:
        return
    _notify(progress_callback, _format_eta_message(label, estimated_seconds, now=now))


def _format_eta_message(label: str, estimated_seconds: float, *, now: datetime | None = None) -> str:
    current_time = now or datetime.now().astimezone()
    finish_time = current_time + timedelta(seconds=estimated_seconds)
    return (
        f"{label} is expected to finish around "
        f"{finish_time.strftime('%Y-%m-%d %I:%M:%S %p %Z')} "
        f"(about {_format_duration(estimated_seconds)})."
    )


def _format_duration(total_seconds: float) -> str:
    rounded_seconds = max(0, int(round(total_seconds)))
    minutes, seconds = divmod(rounded_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _estimate_fixture_run_seconds(
    fixtures_dir: str | Path,
    mode_names: list[str],
    *,
    limit: int | None = None,
    compare_to: str | Path | None = None,
) -> float | None:
    fixture_count = len(discover_fixture_paths(fixtures_dir))
    if limit is not None:
        fixture_count = min(fixture_count, max(0, limit))
    if fixture_count <= 0:
        return None

    runtime_estimates = dict(DEFAULT_MODE_RUNTIME_ESTIMATES)
    runtime_estimates.update(_load_runtime_estimates(compare_to))
    per_fixture_seconds = sum(runtime_estimates.get(mode_name, DEFAULT_MODE_RUNTIME_ESTIMATES["default"]) for mode_name in mode_names)
    return fixture_count * per_fixture_seconds


def _estimate_fixture_run_seconds_for_operational_modes(
    fixtures_dir: str | Path,
    mode_names: list[str],
    *,
    limit: int | None = None,
) -> float | None:
    fixture_count = len(discover_fixture_paths(fixtures_dir))
    if limit is not None:
        fixture_count = min(fixture_count, max(0, limit))
    if fixture_count <= 0:
        return None

    per_fixture_seconds = sum(
        DEFAULT_OPERATIONAL_MODE_RUNTIME_ESTIMATES.get(
            mode_name,
            DEFAULT_OPERATIONAL_MODE_RUNTIME_ESTIMATES["greenfield"],
        )
        for mode_name in mode_names
    )
    return fixture_count * per_fixture_seconds


def is_paper_expectation(expected: FixtureExpectation) -> bool:
    if not expected.games:
        return True
    normalized_games = {game.strip().casefold() for game in expected.games if game.strip()}
    return "paper" in normalized_games


def _is_paper_fixture(evaluation: FixtureEvaluation) -> bool:
    if evaluation.expected_is_paper is None:
        return True
    return evaluation.expected_is_paper


def _load_runtime_estimates(summary_path: str | Path | None) -> dict[str, float]:
    if not summary_path:
        return {}
    path = Path(summary_path)
    if not path.exists():
        return {}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    mode_results = payload.get("mode_results")
    if isinstance(mode_results, list):
        estimates: dict[str, float] = {}
        for item in mode_results:
            if not isinstance(item, dict):
                continue
            mode_name = _coerce_string(item.get("mode_name"))
            summary = item.get("summary")
            if mode_name and isinstance(summary, dict):
                runtime_value = summary.get("average_runtime_seconds")
                if isinstance(runtime_value, (int, float)):
                    estimates[mode_name] = float(runtime_value)
        return estimates

    runtime_value = payload.get("average_runtime_seconds")
    if isinstance(runtime_value, (int, float)):
        return {"default": float(runtime_value)}
    return {}


def _record_simulated_pair(
    pair_store: SimulatedPairStore | None,
    *,
    expected_name: str | None,
    expected_set_code: str | None,
    expected_collector_number: str | None,
    predicted_name: str | None,
    predicted_set_code: str | None,
    predicted_collector_number: str | None,
) -> None:
    if pair_store is None:
        return

    expected_card_id = build_observed_card_id(
        name=expected_name,
        set_code=expected_set_code,
        collector_number=expected_collector_number,
        missing_label="missing_expected",
    )
    if expected_card_id == "missing_expected":
        return

    actual_card_id = build_observed_card_id(
        name=predicted_name,
        set_code=predicted_set_code,
        collector_number=predicted_collector_number,
        missing_label="unrecognized",
    )
    pair_store.record_pair(expected_card_id=expected_card_id, actual_card_id=actual_card_id)


def _infer_name_from_path(path: Path) -> str | None:
    stem = HASHED_NAME_SUFFIX.sub("", path.stem)
    if not stem:
        return None
    candidate = stem.replace("-", " ").strip()
    if not candidate:
        return None
    return " ".join(part.capitalize() for part in candidate.split())


def _classify_result(
    *,
    expected_name: str | None,
    expected_set_code: str | None,
    expected_collector_number: str | None,
    expected_is_paper: bool = True,
    predicted_name: str | None,
    predicted_set_code: str | None,
    predicted_collector_number: str | None,
    candidate_names: list[str],
) -> str:
    if not expected_is_paper:
        return "out_of_scope_nonpaper"
    if expected_name is None:
        return "missing_expected_name"
    if predicted_name is None:
        return "no_prediction"
    if predicted_name == expected_name:
        if expected_set_code and predicted_set_code and predicted_set_code.lower() != expected_set_code.lower():
            return "wrong_set"
        if (
            expected_set_code
            and expected_collector_number
            and predicted_set_code
            and predicted_collector_number
            and (
                predicted_set_code.lower() != expected_set_code.lower()
                or str(predicted_collector_number).lower() != str(expected_collector_number).lower()
            )
        ):
            return "wrong_art"
        return "correct_top1"
    if expected_name in candidate_names[:5]:
        return "correct_in_top5"
    return "wrong_top1"


def _count_by_key(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def resolve_benchmark_modes(mode_names: str | list[str]) -> list[str]:
    if isinstance(mode_names, str):
        raw_names = [part.strip() for part in mode_names.split(",") if part.strip()]
    else:
        raw_names = [str(part).strip() for part in mode_names if str(part).strip()]

    if not raw_names:
        raw_names = ["default"]

    expanded_names: list[str] = []
    for name in raw_names:
        if name == "all":
            expanded_names.extend(DEFAULT_BENCHMARK_MODES)
        else:
            expanded_names.append(name)

    resolved: list[str] = []
    seen: set[str] = set()
    for name in expanded_names:
        if name not in DEFAULT_BENCHMARK_MODES:
            raise ValueError(f"Unknown benchmark mode: {name}")
        if name in seen:
            continue
        seen.add(name)
        resolved.append(name)
    return resolved


def resolve_operational_modes(mode_names: str | list[str]) -> list[str]:
    if isinstance(mode_names, str):
        raw_names = [part.strip() for part in mode_names.split(",") if part.strip()]
    else:
        raw_names = [str(part).strip() for part in mode_names if str(part).strip()]

    if not raw_names:
        raw_names = ["greenfield"]

    expanded_names: list[str] = []
    for name in raw_names:
        if name == "all":
            expanded_names.extend(DEFAULT_OPERATIONAL_MODES)
        else:
            expanded_names.append(name)

    resolved: list[str] = []
    seen: set[str] = set()
    for name in expanded_names:
        if name not in DEFAULT_OPERATIONAL_MODES:
            raise ValueError(f"Unknown operational mode: {name}")
        if name in seen:
            continue
        seen.add(name)
        resolved.append(name)
    return resolved


def config_for_benchmark_mode(base_config: EngineConfig, mode_name: str) -> EngineConfig:
    overrides = _benchmark_mode_overrides(mode_name)
    return replace(base_config, **overrides)


def _benchmark_mode_overrides(mode_name: str) -> dict[str, Any]:
    if mode_name == "default":
        return {}
    if mode_name == "lazy_basic_lands":
        return {"lazy_group_basic_land_printings": True}
    if mode_name == "lazy_all_printings":
        return {"lazy_default_printing_by_name": True}
    raise ValueError(f"Unknown benchmark mode: {mode_name}")


def render_operational_mode_report(report: OperationalModeReport) -> str:
    lines = [
        f"Operational fixtures dir: {report.fixtures_dir}",
        f"Operational modes: {', '.join(mode_result.mode_name for mode_result in report.mode_results) or 'none'}",
    ]
    for mode_result in report.mode_results:
        summary = mode_result.summary
        lines.extend(
            [
                "",
                f"Mode: {mode_result.mode_name}",
                f"  Top-1 accuracy: {summary.top1_accuracy:.3f}",
                f"  Top-5 accuracy: {summary.top5_accuracy:.3f}",
                f"  Set accuracy: {summary.set_accuracy:.3f}",
                f"  Art accuracy: {summary.art_accuracy:.3f}",
                f"  Average confidence: {summary.average_confidence:.3f}",
                f"  Average runtime (s): {summary.average_runtime_seconds:.3f}",
                f"  Median runtime (s): {summary.median_runtime_seconds:.3f}",
                f"  Runtime stddev (s): {summary.runtime_stddev_seconds:.3f}",
                f"  Runtime p95 (s): {summary.runtime_p95_seconds:.3f}",
                f"  Max runtime (s): {summary.max_runtime_seconds:.3f}",
                f"  Calibration error (ECE): {summary.calibration_error:.3f}",
            ]
        )
        if mode_result.implementation_note:
            lines.append(f"  Note: {mode_result.implementation_note}")
    return "\n".join(lines)


def operational_mode_report_to_json(report: OperationalModeReport) -> dict[str, Any]:
    return {
        "fixtures_dir": report.fixtures_dir,
        "mode_results": [
            {
                "mode_name": mode_result.mode_name,
                "implementation_note": mode_result.implementation_note,
                "summary": summary_to_json(mode_result.summary),
            }
            for mode_result in report.mode_results
        ],
    }


def _metric_delta(label: str, baseline: float, current: float) -> MetricDelta:
    baseline_value = round(float(baseline), 4)
    current_value = round(float(current), 4)
    return MetricDelta(
        label=label,
        baseline=baseline_value,
        current=current_value,
        delta=round(current_value - baseline_value, 4),
    )


def _format_delta(metric: MetricDelta) -> str:
    sign = "+" if metric.delta >= 0 else ""
    return (
        f"{metric.label}: "
        f"{metric.baseline:.4f} -> {metric.current:.4f} "
        f"({sign}{metric.delta:.4f})"
    )


def _build_small_pool_catalog(
    full_catalog: LocalCatalogIndex,
    expected: FixtureExpectation,
) -> LocalCatalogIndex:
    if not expected.name:
        return full_catalog
    same_name_records = full_catalog.exact_lookup(expected.name)
    if not same_name_records:
        return full_catalog
    return LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name=record.name,
                normalized_name=record.normalized_name,
                set_code=record.set_code,
                collector_number=record.collector_number,
                layout=record.layout,
                type_line=record.type_line,
                oracle_text=record.oracle_text,
                flavor_text=record.flavor_text,
                image_uri=record.image_uri,
                aliases=list(record.aliases or []),
            )
            for record in same_name_records
        ]
    )


@lru_cache(maxsize=4)
def _load_catalog_for_evaluation(db_path: str) -> LocalCatalogIndex:
    return LocalCatalogIndex.from_sqlite(db_path)


def _average_stage_timings(evaluations: list[FixtureEvaluation]) -> dict[str, float]:
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for evaluation in evaluations:
        for stage_name, elapsed in evaluation.stage_timings.items():
            totals[stage_name] = totals.get(stage_name, 0.0) + elapsed
            counts[stage_name] = counts.get(stage_name, 0) + 1
    return {
        stage_name: round(totals[stage_name] / counts[stage_name], 4)
        for stage_name in sorted(totals)
        if counts[stage_name] > 0
    }


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return round(float(ordered[middle]), 4)
    return round(float((ordered[middle - 1] + ordered[middle]) / 2.0), 4)


def _population_stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return round(math.sqrt(variance), 4)


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(float(ordered[0]), 4)
    clamped = min(max(quantile, 0.0), 1.0)
    position = clamped * (len(ordered) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return round(float(ordered[lower_index]), 4)
    fraction = position - lower_index
    interpolated = ordered[lower_index] + ((ordered[upper_index] - ordered[lower_index]) * fraction)
    return round(float(interpolated), 4)


def _coerce_count_dict(payload: object) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {}
    coerced: dict[str, int] = {}
    for key, value in payload.items():
        try:
            coerced[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return coerced


def _coerce_stage_timings(payload: object) -> dict[str, float]:
    if not isinstance(payload, dict):
        return {}
    coerced: dict[str, float] = {}
    for key, value in payload.items():
        try:
            coerced[str(key)] = round(float(value), 4)
        except (TypeError, ValueError):
            continue
    return coerced


def _filter_dataclass_kwargs(dataclass_type, payload: dict[str, Any]) -> dict[str, Any]:
    valid_fields = {field_def.name for field_def in fields(dataclass_type)}
    return {
        key: value
        for key, value in payload.items()
        if key in valid_fields
    }


def _coerce_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _build_confidence_calibration_bins(
    evaluations: list[FixtureEvaluation],
    *,
    bin_width: float = 0.2,
) -> list[ConfidenceCalibrationBin]:
    if not evaluations:
        return []

    bins: list[ConfidenceCalibrationBin] = []
    lower_bound = 0.0
    while lower_bound < 1.0:
        upper_bound = min(1.0, round(lower_bound + bin_width, 10))
        in_bin = [
            evaluation
            for evaluation in evaluations
            if _confidence_in_bin(evaluation.confidence, lower_bound, upper_bound)
        ]
        if in_bin:
            average_confidence = _safe_ratio(sum(evaluation.confidence for evaluation in in_bin), len(in_bin))
            empirical_accuracy = _safe_ratio(sum(1 for evaluation in in_bin if evaluation.top1_hit), len(in_bin))
            calibration_gap = round(abs(average_confidence - empirical_accuracy), 4)
            bins.append(
                ConfidenceCalibrationBin(
                    lower_bound=round(lower_bound, 1),
                    upper_bound=round(upper_bound, 1),
                    fixture_count=len(in_bin),
                    average_confidence=average_confidence,
                    empirical_accuracy=empirical_accuracy,
                    calibration_gap=calibration_gap,
                )
            )
        lower_bound = upper_bound
    return bins


def _confidence_in_bin(confidence: float, lower_bound: float, upper_bound: float) -> bool:
    if upper_bound >= 1.0:
        return lower_bound <= confidence <= upper_bound
    return lower_bound <= confidence < upper_bound


def _expected_calibration_error(
    calibration_bins: list[ConfidenceCalibrationBin],
    scored_count: int,
) -> float:
    if scored_count <= 0:
        return 0.0
    total_gap = sum(calibration_bin.calibration_gap * calibration_bin.fixture_count for calibration_bin in calibration_bins)
    return round(total_gap / scored_count, 4)


def _safe_ratio(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
