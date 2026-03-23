from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .eval_pair_store import DEFAULT_SIMULATED_PAIR_DB_PATH, build_observed_card_id
from .evaluation import discover_fixture_paths, infer_fixture_expectation
from .utils.image_io import load_image


@dataclass(frozen=True)
class RegressionMismatch:
    expected_card_id: str
    actual_card_id: str
    seen_count: int


@dataclass(frozen=True)
class RegressionFixtureCase:
    expected_card_id: str
    fixture_path: str | None
    expected_name: str | None
    expected_set_code: str | None
    expected_collector_number: str | None
    mismatches: list[RegressionMismatch]


@dataclass(frozen=True)
class RegressionFixtureExport:
    output_dir: str
    manifest_path: str
    copied_fixture_count: int
    missing_expected_ids: list[str]
    cases: list[RegressionFixtureCase]


def export_regression_fixture_set(
    fixtures_dir: str | Path,
    output_dir: str | Path,
    *,
    db_path: str | Path = DEFAULT_SIMULATED_PAIR_DB_PATH,
    max_cases: int = 12,
    min_seen_count: int = 2,
) -> RegressionFixtureExport:
    if max_cases < 1:
        raise ValueError("max_cases must be at least 1.")
    if min_seen_count < 1:
        raise ValueError("min_seen_count must be at least 1.")

    grouped_mismatches = load_grouped_mismatches(
        db_path,
        max_cases=max_cases,
        min_seen_count=min_seen_count,
    )
    fixture_index = build_expected_fixture_index(fixtures_dir)
    output_root = Path(output_dir)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    copied_fixture_count = 0
    missing_expected_ids: list[str] = []
    cases: list[RegressionFixtureCase] = []
    for expected_card_id, mismatches in grouped_mismatches:
        source_fixture = fixture_index.get(expected_card_id)
        expectation = None
        if source_fixture is not None:
            expectation = infer_fixture_expectation(load_image(source_fixture))
            _copy_fixture_with_sidecar(source_fixture, output_root)
            copied_fixture_count += 1
            relative_fixture_path = Path(source_fixture.name).as_posix()
        else:
            missing_expected_ids.append(expected_card_id)
            relative_fixture_path = None

        cases.append(
            RegressionFixtureCase(
                expected_card_id=expected_card_id,
                fixture_path=relative_fixture_path,
                expected_name=expectation.name if expectation else None,
                expected_set_code=expectation.set_code if expectation else None,
                expected_collector_number=expectation.collector_number if expectation else None,
                mismatches=mismatches,
            )
        )

    manifest_path = output_root / "regression_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_fixtures_dir": str(Path(fixtures_dir)),
                "source_pair_db": str(Path(db_path)),
                "max_cases": max_cases,
                "min_seen_count": min_seen_count,
                "copied_fixture_count": copied_fixture_count,
                "missing_expected_ids": missing_expected_ids,
                "cases": [
                    {
                        **asdict(case),
                        "mismatches": [asdict(mismatch) for mismatch in case.mismatches],
                    }
                    for case in cases
                ],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return RegressionFixtureExport(
        output_dir=str(output_root),
        manifest_path=str(manifest_path),
        copied_fixture_count=copied_fixture_count,
        missing_expected_ids=missing_expected_ids,
        cases=cases,
    )


def load_grouped_mismatches(
    db_path: str | Path,
    *,
    max_cases: int = 12,
    min_seen_count: int = 2,
) -> list[tuple[str, list[RegressionMismatch]]]:
    if max_cases < 1:
        raise ValueError("max_cases must be at least 1.")
    if min_seen_count < 1:
        raise ValueError("min_seen_count must be at least 1.")

    database = Path(db_path)
    if not database.exists():
        return []

    with sqlite3.connect(database) as connection:
        rows = connection.execute(
            """
            SELECT expected_card_id, actual_card_id, seen_count
            FROM simulated_card_pairs
            WHERE expected_card_id != actual_card_id
              AND seen_count >= ?
            ORDER BY seen_count DESC, expected_card_id ASC, actual_card_id ASC
            """,
            (min_seen_count,),
        ).fetchall()

    grouped: dict[str, list[RegressionMismatch]] = {}
    for expected_card_id, actual_card_id, seen_count in rows:
        grouped.setdefault(str(expected_card_id), []).append(
            RegressionMismatch(
                expected_card_id=str(expected_card_id),
                actual_card_id=str(actual_card_id),
                seen_count=int(seen_count),
            )
        )

    ranked_expected_ids = sorted(
        grouped,
        key=lambda expected_card_id: (
            -max(mismatch.seen_count for mismatch in grouped[expected_card_id]),
            -sum(mismatch.seen_count for mismatch in grouped[expected_card_id]),
            expected_card_id,
        ),
    )[:max_cases]

    return [
        (
            expected_card_id,
            sorted(
                grouped[expected_card_id],
                key=lambda mismatch: (-mismatch.seen_count, mismatch.actual_card_id),
            ),
        )
        for expected_card_id in ranked_expected_ids
    ]


def build_expected_fixture_index(fixtures_dir: str | Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in discover_fixture_paths(fixtures_dir):
        expectation = infer_fixture_expectation(load_image(path))
        expected_card_id = build_observed_card_id(
            name=expectation.name,
            set_code=expectation.set_code,
            collector_number=expectation.collector_number,
            missing_label="missing_expected",
        )
        if expected_card_id == "missing_expected":
            continue
        index.setdefault(expected_card_id, path)
    return index


def render_regression_fixture_export(export: RegressionFixtureExport) -> str:
    lines = [
        f"Output directory: {export.output_dir}",
        f"Manifest: {export.manifest_path}",
        f"Copied fixtures: {export.copied_fixture_count}",
        f"Missing expected IDs: {len(export.missing_expected_ids)}",
        "",
        "Regression cases:",
    ]
    if not export.cases:
        lines.append("  - none")
        return "\n".join(lines)

    for case in export.cases:
        fixture_label = case.fixture_path or "missing"
        mismatch_summary = ", ".join(
            f"{mismatch.actual_card_id} x{mismatch.seen_count}" for mismatch in case.mismatches
        )
        lines.append(f"  - {case.expected_card_id} -> {fixture_label}")
        lines.append(f"    {mismatch_summary}")

    if export.missing_expected_ids:
        lines.append("")
        lines.append("Missing expected IDs:")
        lines.extend(f"  - {expected_card_id}" for expected_card_id in export.missing_expected_ids)
    return "\n".join(lines)


def _copy_fixture_with_sidecar(source_fixture: Path, output_dir: Path) -> None:
    destination_fixture = output_dir / source_fixture.name
    shutil.copy2(source_fixture, destination_fixture)
    source_sidecar = source_fixture.with_suffix(".json")
    if source_sidecar.exists():
        shutil.copy2(source_sidecar, output_dir / source_sidecar.name)
