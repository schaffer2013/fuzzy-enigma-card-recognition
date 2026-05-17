from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.config import load_engine_config
from card_engine.evaluation import discover_fixture_paths, infer_fixture_expectation
from card_engine.operational_modes import ExpectedCard
from card_engine.runtime import warm_recognition_runtime
from card_engine.utils.image_io import load_image


@dataclass(frozen=True)
class ScanResult:
    fixture: str
    mode: str
    elapsed_seconds: float
    expected_name: str | None
    predicted_name: str | None
    confidence: float
    name_hit: bool
    failure_code: str | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stress-test the long-lived end-user recognition path.")
    parser.add_argument("--fixtures-dir", required=True)
    parser.add_argument("--mode", choices=("greenfield", "reevaluation", "confirmation"), default="greenfield")
    parser.add_argument("--passes", type=int, default=2)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--warmup-passes", type=int, default=1)
    parser.add_argument("--json-out", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_engine_config(args.config)
    fixture_paths = discover_fixture_paths(args.fixtures_dir)
    if args.limit is not None:
        fixture_paths = fixture_paths[: max(0, args.limit)]
    if not fixture_paths:
        raise SystemExit("No fixtures found.")

    recognizer = SortingMachineRecognizer(config=config, auto_track_results=False)
    warmup = warm_recognition_runtime(config=config, session=recognizer.session)

    for _ in range(max(0, args.warmup_passes)):
        for path in fixture_paths:
            image = load_image(path)
            expectation = infer_fixture_expectation(image)
            _recognize(recognizer, image, args.mode, expectation)

    scans: list[ScanResult] = []
    for _pass_index in range(max(1, args.passes)):
        for path in fixture_paths:
            image = load_image(path)
            expectation = infer_fixture_expectation(image)
            started = time.monotonic()
            result = _recognize(recognizer, image, args.mode, expectation)
            elapsed = round(time.monotonic() - started, 4)
            scans.append(
                ScanResult(
                    fixture=str(path),
                    mode=args.mode,
                    elapsed_seconds=elapsed,
                    expected_name=expectation.name,
                    predicted_name=result.card_name,
                    confidence=result.confidence,
                    name_hit=bool(expectation.name and result.card_name == expectation.name),
                    failure_code=getattr(result, "failure_code", None),
                )
            )

    payload = {
        "fixtures_dir": str(args.fixtures_dir),
        "mode": args.mode,
        "passes": args.passes,
        "warmup_passes": args.warmup_passes,
        "warmup": asdict(warmup),
        "summary": _summarize(scans),
        "scans": [asdict(scan) for scan in scans],
    }
    print(json.dumps(payload["summary"], indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0


def _recognize(recognizer, image, mode: str, expectation):
    expected = None
    if mode in {"reevaluation", "confirmation"} and expectation.name:
        expected = ExpectedCard(
            name=expectation.name,
            set_code=expectation.set_code,
            collector_number=expectation.collector_number,
        )
    return recognizer.recognize_top_card(
        image,
        mode=mode,
        expected_card=expected,
        detailed=True,
    )


def _summarize(scans: list[ScanResult]) -> dict[str, float | int]:
    runtimes = [scan.elapsed_seconds for scan in scans]
    return {
        "scan_count": len(scans),
        "name_accuracy": round(sum(1 for scan in scans if scan.name_hit) / len(scans), 4) if scans else 0.0,
        "average_runtime_seconds": round(statistics.fmean(runtimes), 4) if runtimes else 0.0,
        "median_runtime_seconds": round(statistics.median(runtimes), 4) if runtimes else 0.0,
        "p95_runtime_seconds": _percentile(runtimes, 0.95),
        "max_runtime_seconds": max(runtimes) if runtimes else 0.0,
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return round(ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction), 4)


if __name__ == "__main__":
    raise SystemExit(main())
