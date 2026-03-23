from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .utils.text_normalize import normalize_text

DEFAULT_SIMULATED_PAIR_DB_PATH = Path("data") / "cache" / "simulated_card_pairs.sqlite3"
MAX_TRACKED_SIMULATED_PAIRS = 10_000


def build_observed_card_id(
    *,
    name: str | None,
    set_code: str | None,
    collector_number: str | None,
    missing_label: str,
) -> str:
    normalized_set_code = _normalize_id_part(set_code)
    normalized_collector_number = _normalize_id_part(collector_number)
    if normalized_set_code and normalized_collector_number:
        return f"printing:{normalized_set_code}:{normalized_collector_number}"

    if name:
        normalized_name = normalize_text(name)
        if normalized_name:
            return f"name:{normalized_name}"

    return missing_label


class SimulatedPairStore:
    def __init__(
        self,
        db_path: str | Path = DEFAULT_SIMULATED_PAIR_DB_PATH,
        *,
        max_unique_pairs: int = MAX_TRACKED_SIMULATED_PAIRS,
    ) -> None:
        if max_unique_pairs < 1:
            raise ValueError("max_unique_pairs must be at least 1.")
        self.db_path = Path(db_path)
        self.max_unique_pairs = max_unique_pairs
        self._connection: sqlite3.Connection | None = None

    def __enter__(self) -> "SimulatedPairStore":
        self._connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is None:
            return
        self._connection.close()
        self._connection = None

    def record_pair(
        self,
        *,
        expected_card_id: str,
        actual_card_id: str,
        seen_at: datetime | None = None,
    ) -> int:
        connection = self._connect()
        timestamp = (seen_at or datetime.now(timezone.utc)).isoformat()
        row = connection.execute(
            """
            SELECT seen_count
            FROM simulated_card_pairs
            WHERE expected_card_id = ? AND actual_card_id = ?
            """,
            (expected_card_id, actual_card_id),
        ).fetchone()
        seen_before = int(row[0]) if row else 0
        connection.execute(
            """
            INSERT INTO simulated_card_pairs (
                expected_card_id,
                actual_card_id,
                seen_count,
                first_seen_utc,
                last_seen_utc
            )
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(expected_card_id, actual_card_id) DO UPDATE SET
                seen_count = simulated_card_pairs.seen_count + 1,
                last_seen_utc = excluded.last_seen_utc
            """,
            (expected_card_id, actual_card_id, timestamp, timestamp),
        )
        self._prune_if_needed(connection)
        connection.commit()
        return seen_before

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(self.db_path)
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS simulated_card_pairs (
                    expected_card_id TEXT NOT NULL,
                    actual_card_id TEXT NOT NULL,
                    seen_count INTEGER NOT NULL DEFAULT 0,
                    first_seen_utc TEXT NOT NULL,
                    last_seen_utc TEXT NOT NULL,
                    PRIMARY KEY (expected_card_id, actual_card_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_simulated_card_pairs_last_seen
                ON simulated_card_pairs (last_seen_utc, first_seen_utc)
                """
            )
            self._connection.commit()
        return self._connection

    def _prune_if_needed(self, connection: sqlite3.Connection) -> None:
        row = connection.execute("SELECT COUNT(*) FROM simulated_card_pairs").fetchone()
        pair_count = int(row[0]) if row else 0
        overflow = pair_count - self.max_unique_pairs
        if overflow <= 0:
            return

        connection.execute(
            """
            DELETE FROM simulated_card_pairs
            WHERE rowid IN (
                SELECT rowid
                FROM simulated_card_pairs
                ORDER BY last_seen_utc ASC, first_seen_utc ASC, expected_card_id ASC, actual_card_id ASC
                LIMIT ?
            )
            """,
            (overflow,),
        )


def _normalize_id_part(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).strip().split()).casefold()
    return normalized or None
