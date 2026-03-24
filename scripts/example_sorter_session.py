#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path

from card_engine.adapters.sortingmachine import SortingMachineRecognizer
from card_engine.operational_modes import ExpectedCard, VALID_RECOGNITION_MODES

SUPPORTED_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
DEFAULT_SEARCH_DIRS = (
    Path("data") / "sample_outputs" / "random_eval_cards_m9_closeout",
    Path("data") / "sample_outputs" / "random_eval_cards_refresh",
    Path("data") / "sample_outputs" / "random_eval_cards",
    Path("data") / "cache" / "random_cards",
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the sorter/session adapter against a sample image."
    )
    parser.add_argument(
        "--image",
        help="Optional image path. If omitted, the script picks the first sample image it can find.",
    )
    parser.add_argument(
        "--mode",
        default="greenfield",
        choices=list(VALID_RECOGNITION_MODES),
        help="Recognition mode to run.",
    )
    parser.add_argument(
        "--auto-track-results",
        action="store_true",
        help="Automatically add confident greenfield/reevaluation results into the tracked pool.",
    )
    parser.add_argument(
        "--seed-expected-name",
        help="Optional expected card name to add into the tracked pool before recognition.",
    )
    parser.add_argument(
        "--seed-expected-set",
        help="Optional set code paired with --seed-expected-name.",
    )
    parser.add_argument(
        "--seed-expected-collector",
        help="Optional collector number paired with --seed-expected-name.",
    )
    parser.add_argument(
        "--expected-name",
        help="Optional expected card name for reevaluation/confirmation mode.",
    )
    parser.add_argument(
        "--expected-set",
        help="Optional expected set code for reevaluation/confirmation mode.",
    )
    parser.add_argument(
        "--expected-collector",
        help="Optional expected collector number for reevaluation/confirmation mode.",
    )
    parser.add_argument(
        "--use-tracked-pool",
        action="store_true",
        help="Force the adapter to consume the tracked pool for this recognition call.",
    )
    parser.add_argument(
        "--track-result",
        action="store_true",
        help="Force the adapter to add this result into the tracked pool if it is confident enough.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    image_path = _resolve_image_path(args.image)
    recognizer = SortingMachineRecognizer(auto_track_results=args.auto_track_results)

    seed_card = _expected_card_from_args(
        name=args.seed_expected_name,
        set_code=args.seed_expected_set,
        collector_number=args.seed_expected_collector,
    )
    if seed_card is not None:
        added = recognizer.add_expected_card(seed_card)
        print(f"Seeded expected card into tracked pool: {added} -> {seed_card}")

    expected_card = _expected_card_from_args(
        name=args.expected_name,
        set_code=args.expected_set,
        collector_number=args.expected_collector,
    )

    print(f"Using image: {image_path}")
    print(f"Mode: {args.mode}")
    print(f"Tracked pool size before recognition: {len(recognizer.get_tracked_pool_entries())}")

    output = recognizer.recognize_top_card(
        image_path,
        mode=args.mode,
        expected_card=expected_card,
        use_tracked_pool=(True if args.use_tracked_pool else None),
        track_result=(True if args.track_result else None),
    )

    print("")
    print(f"Recognized card: {output.card_name}")
    print(f"Confidence: {output.confidence:.4f}")

    entries = recognizer.get_tracked_pool_entries()
    print("")
    print(f"Tracked pool size after recognition: {len(entries)}")
    for entry in entries[:10]:
        print(
            "  - "
            f"{entry.name} "
            f"({entry.set_code or '?'}:{entry.collector_number or '?'})"
        )
    if len(entries) > 10:
        print(f"  ... {len(entries) - 10} more")

    return 0


def _resolve_image_path(image: str | None) -> Path:
    if image:
        return Path(image)

    for directory in DEFAULT_SEARCH_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
                return path

    raise SystemExit(
        "No sample image found. Pass --image <path> or place a fixture under one of: "
        + ", ".join(str(path) for path in DEFAULT_SEARCH_DIRS)
    )


def _expected_card_from_args(
    *,
    name: str | None,
    set_code: str | None,
    collector_number: str | None,
) -> ExpectedCard | None:
    if not name:
        return None
    return ExpectedCard(
        name=name,
        set_code=set_code,
        collector_number=collector_number,
    )


if __name__ == "__main__":
    raise SystemExit(main())
