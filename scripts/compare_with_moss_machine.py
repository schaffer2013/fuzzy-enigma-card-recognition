from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from card_engine.comparison import compare_recognition_pipelines
from card_engine.adapters.mossmachine import DEFAULT_MOSS_MACHINE_REPO, MossMachineSettings


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare fuzzy-enigma recognition against Moss Machine.")
    parser.add_argument("image", help="Path to the image fixture to evaluate.")
    parser.add_argument("--moss-db-path", default=None, help="Path to the Moss Machine database.")
    parser.add_argument("--moss-repo-path", default=None, help="Path to the Moss Machine submodule root.")
    parser.add_argument("--moss-threshold", type=float, default=10.0, help="Moss Machine pHash threshold.")
    parser.add_argument("--moss-top-n", type=int, default=5, help="Number of Moss Machine candidates to retain.")
    parser.add_argument("--moss-game", action="append", default=[], help="Optional Moss Machine game filter.")
    parser.add_argument("--moss-cache", action="store_true", help="Enable Moss Machine hash caching.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the text summary.")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    moss_settings = MossMachineSettings(
        repo_path=Path(args.moss_repo_path) if args.moss_repo_path else DEFAULT_MOSS_MACHINE_REPO,
        db_path=Path(args.moss_db_path) if args.moss_db_path else None,
        threshold=args.moss_threshold,
        top_n=args.moss_top_n,
        cache_enabled=args.moss_cache,
        active_games=tuple(args.moss_game),
    )
    comparison = compare_recognition_pipelines(
        Path(args.image),
        moss_settings=moss_settings,
    )

    if args.json:
        print(json.dumps(_comparison_to_json(comparison), indent=2, sort_keys=True))
    else:
        print(render_text_summary(comparison))
    return 0


def render_text_summary(comparison) -> str:
    lines = [f"Image: {comparison.image_path or '<memory>'}"]
    for result in (comparison.ours, comparison.moss):
        if result is None:
            continue
        lines.extend(
            [
                "",
                f"Engine: {result.engine}",
                f"  Available: {'yes' if result.available else 'no'}",
                f"  Best: {result.best_name or '<none>'}",
                f"  Confidence: {result.confidence:.4f}",
                f"  Runtime (s): {result.runtime_seconds:.4f}",
                f"  Failure: {result.failure_code or '<none>'}",
            ]
        )
        if result.notes:
            lines.append(f"  Notes: {' | '.join(result.notes)}")
        for index, candidate in enumerate(result.candidates[:5], start=1):
            lines.append(
                "  "
                f"{index}. {candidate.name} "
                f"[{candidate.set_code or '?'} #{candidate.collector_number or '?'}] "
                f"conf={candidate.confidence:.4f} "
                f"dist={candidate.distance if candidate.distance is not None else 'n/a'}"
            )
    return "\n".join(lines)


def _comparison_to_json(comparison) -> dict:
    return {
        "image_path": comparison.image_path,
        "ours": _result_to_json(comparison.ours),
        "moss": _result_to_json(comparison.moss),
    }


def _result_to_json(result) -> dict | None:
    if result is None:
        return None
    return {
        "engine": result.engine,
        "available": result.available,
        "best_name": result.best_name,
        "confidence": result.confidence,
        "runtime_seconds": result.runtime_seconds,
        "failure_code": result.failure_code,
        "notes": list(result.notes),
        "candidates": [
            {
                "name": candidate.name,
                "set_code": candidate.set_code,
                "collector_number": candidate.collector_number,
                "confidence": candidate.confidence,
                "distance": candidate.distance,
                "metadata": dict(candidate.metadata),
            }
            for candidate in result.candidates
        ],
        "debug": dict(result.debug),
    }


if __name__ == "__main__":
    raise SystemExit(main())
