from __future__ import annotations

import argparse
import json
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .api import recognize_card
from .catalog.scryfall_sync import fetch_random_card_image
from .utils.image_io import LoadedImage, load_image

SUPPORTED_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
HASHED_NAME_SUFFIX = re.compile(r"-(?P<hash>[0-9a-f]{8})$", re.IGNORECASE)
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class FixtureExpectation:
    name: str | None
    set_code: str | None
    collector_number: str | None


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
    roi_usage: dict[str, int]
    error_classes: dict[str, int]
    fixtures: list[FixtureEvaluation]


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
        "--random-sample",
        type=int,
        default=0,
        help="Fetch this many random cards into a dedicated evaluation folder before scoring them.",
    )
    parser.add_argument(
        "--random-output-dir",
        default="data/sample_outputs/random_eval_cards",
        help="Output directory used when --random-sample is provided.",
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


def evaluate_fixture_set(fixtures_dir: str | Path, *, limit: int | None = None) -> EvaluationSummary:
    fixture_paths = discover_fixture_paths(fixtures_dir)
    if limit is not None:
        fixture_paths = fixture_paths[: max(0, limit)]

    evaluations = [evaluate_fixture(path) for path in fixture_paths]
    fixture_count = len(evaluations)
    scored = [evaluation for evaluation in evaluations if evaluation.expected_name]
    set_scored = [evaluation for evaluation in evaluations if evaluation.expected_set_code]
    art_scored = [
        evaluation
        for evaluation in evaluations
        if evaluation.expected_set_code and evaluation.expected_collector_number
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
        roi_usage=roi_usage,
        error_classes=error_classes,
        fixtures=evaluations,
    )


def evaluate_fixture(path: str | Path) -> FixtureEvaluation:
    fixture_path = Path(path)
    loaded_image = load_image(fixture_path)
    expected = infer_fixture_expectation(loaded_image)
    result = recognize_card(loaded_image)
    best_candidate = result.top_k_candidates[0] if result.top_k_candidates else None
    candidate_names = [candidate.name for candidate in result.top_k_candidates]
    predicted_set_code = best_candidate.set_code if best_candidate else None
    predicted_collector_number = best_candidate.collector_number if best_candidate else None
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
            predicted_name=result.best_name,
            predicted_set_code=predicted_set_code,
            predicted_collector_number=predicted_collector_number,
            candidate_names=candidate_names,
        ),
    )


def infer_expected_name(image: LoadedImage) -> str | None:
    return infer_fixture_expectation(image).name


def infer_fixture_expectation(image: LoadedImage) -> FixtureExpectation:
    payload = _read_sidecar_payload(image.path)
    expected_name = _coerce_string(payload.get("expected_name"))
    expected_set_code = _coerce_string(payload.get("expected_set_code"))
    expected_collector_number = _coerce_string(payload.get("expected_collector_number"))

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
    )


def build_random_sample(
    output_dir: str | Path,
    *,
    count: int,
    progress_callback: ProgressCallback | None = None,
) -> Path:
    if count < 1:
        raise ValueError("count must be at least 1.")

    output_root = Path(output_dir)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    for index in range(count):
        path = fetch_random_card_image(output_root, max_cached_cards=count)
        _notify(progress_callback, f"Fetched random card {index + 1}/{count}: {path.name}")
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
        "",
        "ROI usage:",
    ]
    if summary.roi_usage:
        lines.extend(f"  - {roi}: {count}" for roi, count in sorted(summary.roi_usage.items()))
    else:
        lines.append("  - none")

    lines.append("")
    lines.append("Error classes:")
    if summary.error_classes:
        lines.extend(f"  - {label}: {count}" for label, count in sorted(summary.error_classes.items()))
    else:
        lines.append("  - none")

    incorrect = [fixture for fixture in summary.fixtures if not fixture.top1_hit and fixture.expected_name]
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
        "roi_usage": summary.roi_usage,
        "error_classes": summary.error_classes,
        "fixtures": [asdict(fixture) for fixture in summary.fixtures],
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    fixtures_dir = args.fixtures_dir
    if args.random_sample:
        fixtures_dir = str(
            build_random_sample(
                args.random_output_dir,
                count=args.random_sample,
                progress_callback=print,
            )
        )

    summary = evaluate_fixture_set(fixtures_dir, limit=args.limit)
    print(render_summary(summary))

    if args.json_out:
        output_path = Path(args.json_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary_to_json(summary), indent=2, sort_keys=True), encoding="utf-8")
        print(f"\nWrote JSON summary to {output_path}")

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


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


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
    predicted_name: str | None,
    predicted_set_code: str | None,
    predicted_collector_number: str | None,
    candidate_names: list[str],
) -> str:
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


def _safe_ratio(numerator: float, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
