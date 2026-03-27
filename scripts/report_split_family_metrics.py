#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize a split-layout operational benchmark by split family.",
    )
    parser.add_argument(
        "--report-json",
        default="data/sample_outputs/split_layout_operational_full.json",
        help="Operational benchmark JSON report to summarize.",
    )
    parser.add_argument(
        "--csv-out",
        default=None,
        help="Optional CSV output path.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Optional JSON output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report_path = Path(args.report_json)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = build_family_rows(report)

    if args.csv_out:
        csv_path = Path(args.csv_out)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(rows, csv_path)
        print(f"Wrote CSV summary to {csv_path}")
    if args.json_out:
        json_path = Path(args.json_out)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Wrote JSON summary to {json_path}")

    for row in rows:
        print(
            f"{row['mode_name']}: {row['split_family']} | "
            f"{row['correct']}/{row['fixture_count']} correct | "
            f"top1={row['top1_accuracy']:.3f} | avg={row['average_runtime_seconds']:.3f}s"
        )
    return 0


def build_family_rows(report: dict) -> list[dict]:
    rows: list[dict] = []
    for mode_result in report.get("mode_results", []):
        families: dict[str, list[dict]] = defaultdict(list)
        fixtures = mode_result.get("summary", {}).get("fixtures", [])
        for fixture in fixtures:
            families[_fixture_split_family(fixture)].append(fixture)
        for family_name in sorted(families):
            family_fixtures = families[family_name]
            fixture_count = len(family_fixtures)
            correct = sum(1 for fixture in family_fixtures if fixture.get("top1_hit"))
            rows.append(
                {
                    "mode_name": mode_result.get("mode_name"),
                    "split_family": family_name,
                    "fixture_count": fixture_count,
                    "correct": correct,
                    "incorrect": fixture_count - correct,
                    "top1_accuracy": round(correct / fixture_count, 4) if fixture_count else 0.0,
                    "average_runtime_seconds": round(
                        sum(float(fixture.get("runtime_seconds") or 0.0) for fixture in family_fixtures) / fixture_count,
                        4,
                    )
                    if fixture_count
                    else 0.0,
                }
            )
    return rows


def write_csv(rows: list[dict], output_path: Path) -> None:
    fieldnames = [
        "mode_name",
        "split_family",
        "fixture_count",
        "correct",
        "incorrect",
        "top1_accuracy",
        "average_runtime_seconds",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture_split_family(fixture: dict) -> str:
    path = fixture.get("path")
    if not path:
        return "unknown"
    sidecar_path = Path(path).with_suffix(".json")
    if not sidecar_path.exists():
        return "unknown"
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(payload.get("split_family") or "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
