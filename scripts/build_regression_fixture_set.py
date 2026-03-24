#!/usr/bin/env python
from __future__ import annotations

import argparse

from card_engine.eval_pair_store import DEFAULT_SIMULATED_PAIR_DB_PATH
from card_engine.regression_fixtures import export_regression_fixture_set, render_regression_fixture_export


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a curated regression fixture set from repeated simulated mismatches."
    )
    parser.add_argument(
        "--fixtures-dir",
        default="data/sample_outputs/random_eval_cards",
        help="Directory containing saved fixture images and sidecars.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/cache/regression_fixtures",
        help="Directory to populate with copied regression fixtures and a manifest.",
    )
    parser.add_argument(
        "--pair-db",
        default=str(DEFAULT_SIMULATED_PAIR_DB_PATH),
        help="SQLite database containing simulated expected-vs-actual pair counts.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=12,
        help="Maximum number of expected-card regression cases to export.",
    )
    parser.add_argument(
        "--min-seen-count",
        type=int,
        default=2,
        help="Minimum repeated mismatch count required to include a case.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    export = export_regression_fixture_set(
        args.fixtures_dir,
        args.output_dir,
        db_path=args.pair_db,
        max_cases=args.max_cases,
        min_seen_count=args.min_seen_count,
    )
    print(render_regression_fixture_export(export))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
