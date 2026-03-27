#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from card_engine.catalog.query import OfflineCatalogQuery
from card_engine.config import load_engine_config


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect the offline paper-only catalog by Oracle or printing identity.",
    )
    parser.add_argument(
        "--catalog",
        default=None,
        help="Optional catalog path. Defaults to the current engine config catalog path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    oracle_name = subparsers.add_parser("oracle-name", help="Find Oracle-level cards by name.")
    oracle_name.add_argument("query")
    oracle_name.add_argument("--limit", type=int, default=20)

    oracle_id = subparsers.add_parser("oracle-id", help="Load one Oracle-level card by oracle_id.")
    oracle_id.add_argument("oracle_id")

    printing_id = subparsers.add_parser("printing-id", help="Load one printed card by scryfall_id.")
    printing_id.add_argument("scryfall_id")

    printings_oracle = subparsers.add_parser("printings-for-oracle", help="List all printings for one oracle_id.")
    printings_oracle.add_argument("oracle_id")
    printings_oracle.add_argument("--limit", type=int, default=None)

    printings_name = subparsers.add_parser("printings-for-name", help="List all printings for one card name.")
    printings_name.add_argument("query")
    printings_name.add_argument("--limit", type=int, default=None)

    printed_search = subparsers.add_parser("printed-search", help="Search printed cards with exact filters.")
    printed_search.add_argument("--name", default=None)
    printed_search.add_argument("--oracle-id", default=None)
    printed_search.add_argument("--set-code", default=None)
    printed_search.add_argument("--collector-number", default=None)
    printed_search.add_argument("--limit", type=int, default=50)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    catalog_path = args.catalog or load_engine_config().catalog_path
    query = OfflineCatalogQuery.from_sqlite(catalog_path)

    if args.command == "oracle-name":
        payload = [asdict(row) for row in query.find_oracle_cards(args.query, limit=args.limit)]
    elif args.command == "oracle-id":
        row = query.get_oracle_card(args.oracle_id)
        payload = asdict(row) if row else None
    elif args.command == "printing-id":
        row = query.get_printed_card(args.scryfall_id)
        payload = asdict(row) if row else None
    elif args.command == "printings-for-oracle":
        payload = [asdict(row) for row in query.printings_for_oracle(args.oracle_id, limit=args.limit)]
    elif args.command == "printings-for-name":
        payload = [asdict(row) for row in query.printings_for_name(args.query, limit=args.limit)]
    elif args.command == "printed-search":
        payload = [
            asdict(row)
            for row in query.find_printed_cards(
                name_query=args.name,
                oracle_id=args.oracle_id,
                set_code=args.set_code,
                collector_number=args.collector_number,
                limit=args.limit,
            )
        ]
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
