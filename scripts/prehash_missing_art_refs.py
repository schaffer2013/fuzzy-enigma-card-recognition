from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from card_engine.art_match import ART_MATCH_CACHE_DIR
from card_engine.art_prehash import DEFAULT_ART_PREHASH_WORKERS, load_eligible_art_records, prehash_missing_art_records
from card_engine.config import load_engine_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prehash missing reference art fingerprints into data/cache/art_match_refs.",
    )
    parser.add_argument(
        "--config",
        help="Optional engine config path. Defaults to CARD_ENGINE_CONFIG_PATH or data/config/engine.json.",
    )
    parser.add_argument(
        "--catalog",
        help="Optional catalog SQLite path. Defaults to the configured catalog_path.",
    )
    parser.add_argument(
        "--cache-dir",
        default=str(ART_MATCH_CACHE_DIR),
        help="Reference art cache directory. Defaults to data/cache/art_match_refs.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on missing records to hash this run.")
    parser.add_argument(
        "--download-timeout-seconds",
        type=float,
        default=10.0,
        help="Timeout per reference image download.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_ART_PREHASH_WORKERS,
        help="Number of parallel workers for downloading and hashing art references.",
    )
    parser.add_argument("--shuffle", action="store_true", help="Shuffle the missing worklist before hashing.")
    parser.add_argument("--dry-run", action="store_true", help="Only count and report missing entries.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_engine_config(args.config)
    catalog_path = args.catalog or config.catalog_path
    cache_dir = Path(args.cache_dir)

    print(f"Loading catalog from {catalog_path}")
    records = load_eligible_art_records(catalog_path)
    print(f"Eligible paper printings with art images: {len(records)}")

    result = prehash_missing_art_records(
        records,
        cache_dir=cache_dir,
        limit=args.limit,
        shuffle=args.shuffle,
        download_timeout_seconds=args.download_timeout_seconds,
        max_workers=args.max_workers,
        progress_callback=None if args.dry_run else _print_progress,
    )

    pending = max(0, result.total_eligible - result.already_hashed - result.newly_hashed)
    print(
        f"Already hashed: {result.already_hashed} | attempted now: {result.attempted} | "
        f"newly hashed: {result.newly_hashed} | pending after run: {pending}"
    )
    if args.dry_run:
        print("Dry run only; no downloads performed.")
        return 0
    print(f"Done in {result.elapsed_seconds:.1f}s. Cache dir: {cache_dir}")
    if result.failures:
        preview = ", ".join(result.failures[:10])
        suffix = "" if len(result.failures) <= 10 else f" ... (+{len(result.failures) - 10} more)"
        print(f"Failed records: {preview}{suffix}")
        return 2
    return 0


def _print_progress(progress) -> None:
    eta = datetime.now() + timedelta(seconds=progress.eta_seconds)
    print(f"{progress.message} | eta at {eta.strftime('%Y-%m-%d %I:%M:%S %p')}")


if __name__ == "__main__":
    raise SystemExit(main())
