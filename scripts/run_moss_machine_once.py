from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one isolated Moss Machine recognition pass.")
    parser.add_argument("--repo-path", required=True, help="Path to the Moss Machine git submodule root.")
    parser.add_argument("--image", required=True, help="Image file to scan.")
    parser.add_argument("--db-path", default=None, help="Path to a Moss Machine SQLite database.")
    parser.add_argument("--threshold", type=float, default=10.0, help="Average RGB pHash distance threshold.")
    parser.add_argument("--top-n", type=int, default=5, help="Number of candidate matches to keep.")
    parser.add_argument("--cache", action="store_true", help="Enable Moss Machine hash caching.")
    parser.add_argument("--game", action="append", default=[], help="Optional game filter. Can be used multiple times.")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    payload = run_once(
        repo_path=Path(args.repo_path),
        image_path=Path(args.image),
        db_path=Path(args.db_path) if args.db_path else None,
        threshold=args.threshold,
        top_n=args.top_n,
        cache_enabled=args.cache,
        active_games=tuple(args.game),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def run_once(
    *,
    repo_path: Path,
    image_path: Path,
    db_path: Path | None,
    threshold: float,
    top_n: int,
    cache_enabled: bool,
    active_games: tuple[str, ...],
) -> dict:
    if not repo_path.exists():
        return _failure_payload("moss_repo_missing", f"Repo path not found: {repo_path}")
    if not image_path.exists():
        return _failure_payload("image_missing", f"Image path not found: {image_path}")

    current_version = repo_path / "Current version"
    scanner_path = current_version / "optimized_scanner.py"
    default_db_path = current_version / "recognition_data" / "unified_card_database.db"
    resolved_db_path = db_path or default_db_path

    if not scanner_path.exists():
        return _failure_payload("scanner_missing", f"Scanner file not found: {scanner_path}")
    if not resolved_db_path.exists():
        return _failure_payload(
            "database_missing",
            (
                "Moss Machine database not found. "
                f"Expected {resolved_db_path}. Download it separately before running comparisons."
            ),
        )

    import_buffer = io.StringIO()
    run_buffer = io.StringIO()
    scanner = None
    try:
        module = _load_moss_module(scanner_path, current_version, import_buffer)
        with contextlib.redirect_stdout(run_buffer), contextlib.redirect_stderr(run_buffer):
            scanner = module.OptimizedCardScanner(
                db_path=str(resolved_db_path),
                cache_enabled=cache_enabled,
                enable_collection=False,
                prompt_for_details=False,
                serial_port=None,
            )
            if active_games:
                scanner.set_active_games(list(active_games))
            matches, elapsed = scanner.scan_from_file(
                str(image_path),
                threshold=threshold,
                top_n=top_n,
            )
    except Exception as exc:  # pragma: no cover - exercised through parent wrapper
        return {
            "available": False,
            "best_name": None,
            "confidence": 0.0,
            "runtime_seconds": 0.0,
            "failure_code": "moss_runtime_error",
            "candidates": [],
            "notes": [str(exc)],
            "debug": {
                "import_log": import_buffer.getvalue(),
                "run_log": run_buffer.getvalue(),
            },
        }
    finally:
        if scanner is not None and hasattr(scanner, "close"):
            with contextlib.suppress(Exception):
                with contextlib.redirect_stdout(run_buffer), contextlib.redirect_stderr(run_buffer):
                    scanner.close()

    normalized_candidates = [_normalize_candidate(match) for match in matches]
    best_candidate = normalized_candidates[0] if normalized_candidates else None
    failure_code = None if normalized_candidates else "no_matches"
    return {
        "available": True,
        "best_name": best_candidate["name"] if best_candidate else None,
        "confidence": best_candidate["confidence"] if best_candidate else 0.0,
        "runtime_seconds": round(float(elapsed or 0.0), 4),
        "failure_code": failure_code,
        "candidates": normalized_candidates,
        "notes": [],
        "debug": {
            "db_path": str(resolved_db_path),
            "active_games": list(active_games),
            "cache_enabled": cache_enabled,
            "import_log": import_buffer.getvalue(),
            "run_log": run_buffer.getvalue(),
        },
    }


def _load_moss_module(scanner_path: Path, current_version: Path, import_buffer: io.StringIO):
    sys.path.insert(0, str(current_version))
    try:
        spec = importlib.util.spec_from_file_location("moss_machine_optimized_scanner", scanner_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load module spec for {scanner_path}")
        module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(import_buffer), contextlib.redirect_stderr(import_buffer):
            spec.loader.exec_module(module)
        return module
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(current_version))


def _normalize_candidate(match: dict) -> dict:
    confidence_pct = float(match.get("confidence") or 0.0)
    return {
        "name": str(match.get("name") or ""),
        "set_code": _coerce_optional_string(match.get("set_code") or match.get("set")),
        "collector_number": _coerce_optional_string(match.get("number")),
        "confidence": round(confidence_pct / 100.0, 4),
        "distance": _coerce_optional_float(match.get("distance")),
        "metadata": {
            "game": match.get("game"),
            "product_id": match.get("product_id"),
            "raw_confidence_percent": confidence_pct,
        },
    }


def _failure_payload(code: str, note: str) -> dict:
    return {
        "available": False,
        "best_name": None,
        "confidence": 0.0,
        "runtime_seconds": 0.0,
        "failure_code": code,
        "candidates": [],
        "notes": [note],
        "debug": {},
    }


def _coerce_optional_string(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
