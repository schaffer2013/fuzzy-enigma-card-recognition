#!/usr/bin/env python
from __future__ import annotations

import argparse

from card_engine.catalog.build_catalog import build_catalog
from card_engine.catalog.scryfall_sync import sync_bulk_data


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the local SQLite card catalog.")
    parser.add_argument(
        "--db-path",
        default="data/catalog/cards.sqlite3",
        help="Destination SQLite path.",
    )
    parser.add_argument(
        "--source-json",
        default="data/catalog/default-cards.json",
        help="Source JSON path. Downloaded from Scryfall when --download is used.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the latest default-cards bulk export from Scryfall before building.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.download:
        source_path = sync_bulk_data(args.source_json)
        print(f"Downloaded bulk data to {source_path}")

    stats = build_catalog(args.db_path, args.source_json)
    print(
        "Catalog ready at "
        f"{stats.database_path} "
        f"({stats.card_count} cards, {stats.alias_count} aliases, source={stats.source_path})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
