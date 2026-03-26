#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from card_engine.config import load_engine_config
from card_engine.split_fixtures import DEFAULT_SPLIT_FIXTURES_DIR, build_split_fixture_set


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a fixture set for all split-layout cards in the offline catalog.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_SPLIT_FIXTURES_DIR),
        help="Directory to write the split-card fixtures into.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on the number of split printings to materialize.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Redownload images even when they already exist locally.",
    )
    return parser


def _safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        print(str(message).encode("ascii", "replace").decode("ascii"))


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = load_engine_config()

    written = build_split_fixture_set(
        catalog_path=config.catalog_path,
        output_dir=Path(args.output_dir),
        limit=args.limit,
        overwrite=args.overwrite,
        progress_callback=_safe_print,
    )
    _safe_print(f"Wrote {len(written)} split-card fixtures to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
