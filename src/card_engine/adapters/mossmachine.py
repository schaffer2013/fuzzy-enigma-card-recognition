from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MOSS_MACHINE_REPO = REPO_ROOT / "third_party" / "moss-machine"
DEFAULT_MOSS_MACHINE_RUNNER = REPO_ROOT / "scripts" / "run_moss_machine_once.py"
DEFAULT_MOSS_MACHINE_ASSET_CACHE = REPO_ROOT / "data" / "cache" / "moss-machine"


@dataclass(frozen=True)
class MossMachineCandidate:
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    confidence: float = 0.0
    distance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MossMachineRunResult:
    available: bool
    best_name: str | None
    confidence: float
    runtime_seconds: float
    failure_code: str | None = None
    candidates: list[MossMachineCandidate] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MossMachineSettings:
    repo_path: Path = DEFAULT_MOSS_MACHINE_REPO
    db_path: Path | None = None
    threshold: float = 10.0
    top_n: int = 5
    cache_enabled: bool = False
    active_games: tuple[str, ...] = ()
    timeout_seconds: float = 180.0
    python_executable: str = sys.executable
    runner_path: Path = DEFAULT_MOSS_MACHINE_RUNNER
    asset_cache_dir: Path = DEFAULT_MOSS_MACHINE_ASSET_CACHE
    auto_stage_assets: bool = True


def run_moss_machine_recognition(
    image_path: str | Path,
    *,
    settings: MossMachineSettings | None = None,
) -> MossMachineRunResult:
    resolved_settings = settings or MossMachineSettings()
    image_file = Path(image_path)
    if not image_file.exists():
        return MossMachineRunResult(
            available=False,
            best_name=None,
            confidence=0.0,
            runtime_seconds=0.0,
            failure_code="image_missing",
            notes=[f"Image path does not exist: {image_file}"],
        )
    if not resolved_settings.repo_path.exists():
        return MossMachineRunResult(
            available=False,
            best_name=None,
            confidence=0.0,
            runtime_seconds=0.0,
            failure_code="moss_repo_missing",
            notes=[f"Moss Machine repo not found at {resolved_settings.repo_path}"],
        )
    if not resolved_settings.runner_path.exists():
        return MossMachineRunResult(
            available=False,
            best_name=None,
            confidence=0.0,
            runtime_seconds=0.0,
            failure_code="runner_missing",
            notes=[f"Runner script not found at {resolved_settings.runner_path}"],
        )

    staged_db_path, staged_paths, staged_directories, stage_notes = _prepare_moss_runtime_assets(
        resolved_settings
    )
    command = [
        resolved_settings.python_executable,
        str(resolved_settings.runner_path),
        "--repo-path",
        str(resolved_settings.repo_path),
        "--image",
        str(image_file),
        "--threshold",
        str(resolved_settings.threshold),
        "--top-n",
        str(resolved_settings.top_n),
    ]
    if staged_db_path is not None:
        command.extend(["--db-path", str(staged_db_path)])
    if resolved_settings.cache_enabled:
        command.append("--cache")
    for game_name in resolved_settings.active_games:
        command.extend(["--game", game_name])

    try:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=max(1.0, resolved_settings.timeout_seconds),
            )
        finally:
            _cleanup_staged_moss_runtime_assets(staged_paths, staged_directories)
    except subprocess.TimeoutExpired:
        return MossMachineRunResult(
            available=False,
            best_name=None,
            confidence=0.0,
            runtime_seconds=resolved_settings.timeout_seconds,
            failure_code="timeout",
            notes=[
                *stage_notes,
                f"Moss Machine subprocess exceeded {resolved_settings.timeout_seconds:.1f}s timeout.",
            ],
        )

    if completed.returncode != 0:
        return MossMachineRunResult(
            available=False,
            best_name=None,
            confidence=0.0,
            runtime_seconds=0.0,
            failure_code="subprocess_failed",
            notes=[
                *stage_notes,
                completed.stderr.strip() or completed.stdout.strip() or "Moss Machine subprocess failed.",
            ],
            debug={
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return MossMachineRunResult(
            available=False,
            best_name=None,
            confidence=0.0,
            runtime_seconds=0.0,
            failure_code="invalid_json",
            notes=[*stage_notes, "Moss Machine runner did not return valid JSON."],
            debug={
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )

    result = _result_from_payload(payload)
    if stage_notes:
        return replace(result, notes=[*stage_notes, *result.notes])
    return result


def _result_from_payload(payload: dict[str, Any]) -> MossMachineRunResult:
    candidate_payloads = payload.get("candidates")
    candidates: list[MossMachineCandidate] = []
    if isinstance(candidate_payloads, list):
        for item in candidate_payloads:
            if not isinstance(item, dict):
                continue
            candidates.append(
                MossMachineCandidate(
                    name=str(item.get("name") or ""),
                    set_code=_coerce_optional_string(item.get("set_code")),
                    collector_number=_coerce_optional_string(item.get("collector_number")),
                    confidence=float(item.get("confidence") or 0.0),
                    distance=_coerce_optional_float(item.get("distance")),
                    metadata=dict(item.get("metadata") or {}),
                )
            )

    return MossMachineRunResult(
        available=bool(payload.get("available")),
        best_name=_coerce_optional_string(payload.get("best_name")),
        confidence=float(payload.get("confidence") or 0.0),
        runtime_seconds=float(payload.get("runtime_seconds") or 0.0),
        failure_code=_coerce_optional_string(payload.get("failure_code")),
        candidates=candidates,
        debug=dict(payload.get("debug") or {}),
        notes=[str(note) for note in payload.get("notes") or []],
    )


def _coerce_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    coerced = str(value).strip()
    return coerced or None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _prepare_moss_runtime_assets(
    settings: MossMachineSettings,
) -> tuple[Path | None, list[Path], list[Path], list[str]]:
    if not settings.auto_stage_assets:
        return settings.db_path, [], [], []

    current_version = settings.repo_path / "Current version"
    recognition_dir = current_version / "recognition_data"
    created_recognition_dir = not recognition_dir.exists()
    recognition_dir.mkdir(parents=True, exist_ok=True)

    staged_paths: list[Path] = []
    staged_names: list[str] = []
    cleanup_directories = [recognition_dir] if created_recognition_dir else []

    staged_db_path = _resolve_staged_database_path(settings, recognition_dir, staged_paths, staged_names)

    asset_cache_dir = settings.asset_cache_dir
    if asset_cache_dir.exists():
        for source_path in sorted(asset_cache_dir.glob("phash_cards_*.db")):
            target_path = recognition_dir / source_path.name
            if _stage_file_if_missing(source_path, target_path):
                staged_paths.append(target_path)
                staged_names.append(source_path.name)

    stage_notes = []
    if staged_names:
        stage_notes.append("auto_staged_assets=" + ",".join(staged_names))

    return staged_db_path, staged_paths, cleanup_directories, stage_notes


def _resolve_staged_database_path(
    settings: MossMachineSettings,
    recognition_dir: Path,
    staged_paths: list[Path],
    staged_names: list[str],
) -> Path | None:
    source_path = settings.db_path
    if source_path is None:
        default_cached_db = settings.asset_cache_dir / "unified_card_database.db"
        if default_cached_db.exists():
            source_path = default_cached_db

    if source_path is None:
        return None

    target_path = recognition_dir / source_path.name
    if _stage_file_if_missing(source_path, target_path):
        staged_paths.append(target_path)
        staged_names.append(source_path.name)
    if target_path.exists():
        return target_path
    return source_path


def _stage_file_if_missing(source_path: Path, target_path: Path) -> bool:
    if not source_path.exists():
        return False
    with contextlib.suppress(OSError):
        if source_path.resolve() == target_path.resolve():
            return False
    if target_path.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return True


def _cleanup_staged_moss_runtime_assets(staged_paths: list[Path], cleanup_directories: list[Path]) -> None:
    for path in reversed(staged_paths):
        path.unlink(missing_ok=True)
    for directory in reversed(cleanup_directories):
        with contextlib.suppress(OSError):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
