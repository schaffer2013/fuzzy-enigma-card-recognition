from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .build_catalog import CATALOG_SCHEMA_VERSION, CatalogBuildStats, build_catalog
from .scryfall_sync import sync_bulk_data

ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class CatalogStatus:
    db_path: Path
    source_path: Path
    action: str
    refreshed: bool
    age_days: float | None
    build_stats: CatalogBuildStats | None = None


def catalog_refresh_needed(
    *,
    db_path: str = "data/catalog/cards.sqlite3",
    max_age_days: int = 7,
) -> tuple[bool, float | None]:
    database = Path(db_path)
    if not database.exists():
        return True, None

    if _schema_refresh_needed(database):
        return True, _age_in_days(database)

    age_days = _age_in_days(database)
    return age_days >= max_age_days, age_days


def ensure_catalog_ready(
    *,
    db_path: str = "data/catalog/cards.sqlite3",
    source_json_path: str = "data/catalog/default-cards.json",
    max_age_days: int = 7,
    progress_callback: ProgressCallback | None = None,
) -> CatalogStatus:
    database = Path(db_path)
    source = Path(source_json_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    source.parent.mkdir(parents=True, exist_ok=True)

    needs_refresh, age_days = catalog_refresh_needed(db_path=str(database), max_age_days=max_age_days)

    if not needs_refresh:
        _notify(progress_callback, f"Catalog is current ({age_days:.1f} days old).")
        return CatalogStatus(
            db_path=database,
            source_path=source,
            action="reuse",
            refreshed=False,
            age_days=age_days,
        )

    if not database.exists():
        _notify(progress_callback, "Catalog missing. Downloading bulk data...")
        reason = "missing"
    elif _schema_refresh_needed(database):
        _notify(progress_callback, "Catalog schema is outdated. Rebuilding bulk data...")
        reason = "schema"
    else:
        _notify(progress_callback, f"Catalog is {age_days:.1f} days old. Refreshing bulk data...")
        reason = "stale"

    sync_bulk_data(str(source))
    _notify(progress_callback, "Building local SQLite catalog...")
    stats = build_catalog(str(database), str(source))
    _notify(progress_callback, f"Catalog ready with {stats.card_count} cards.")

    return CatalogStatus(
        db_path=database,
        source_path=source,
        action=reason,
        refreshed=True,
        age_days=_age_in_days(database),
        build_stats=stats,
    )


def _age_in_days(path: Path) -> float:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - modified
    return age / timedelta(days=1)


def _notify(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _schema_refresh_needed(database: Path) -> bool:
    try:
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                "SELECT value FROM catalog_metadata WHERE key = 'schema_version'"
            ).fetchone()
    except sqlite3.Error:
        return True

    if row is None:
        return True
    return str(row[0]) != CATALOG_SCHEMA_VERSION
