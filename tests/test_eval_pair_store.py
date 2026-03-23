from datetime import datetime, timedelta, timezone
import sqlite3

from card_engine.eval_pair_store import SimulatedPairStore


def test_record_pair_increments_seen_count_and_returns_prior_total(tmp_path):
    db_path = tmp_path / "pairs.sqlite3"
    with SimulatedPairStore(db_path) as store:
        first_seen_before = store.record_pair(
            expected_card_id="printing:lea:233",
            actual_card_id="printing:lea:233",
        )
        second_seen_before = store.record_pair(
            expected_card_id="printing:lea:233",
            actual_card_id="printing:lea:233",
        )

    assert first_seen_before == 0
    assert second_seen_before == 1

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT seen_count FROM simulated_card_pairs WHERE expected_card_id = ? AND actual_card_id = ?",
            ("printing:lea:233", "printing:lea:233"),
        ).fetchone()

    assert row == (2,)


def test_record_pair_prunes_oldest_unique_pairs_when_capacity_is_exceeded(tmp_path):
    db_path = tmp_path / "pairs.sqlite3"
    base_time = datetime(2026, 3, 23, tzinfo=timezone.utc)
    with SimulatedPairStore(db_path, max_unique_pairs=2) as store:
        store.record_pair(
            expected_card_id="printing:a:1",
            actual_card_id="printing:a:1",
            seen_at=base_time,
        )
        store.record_pair(
            expected_card_id="printing:b:1",
            actual_card_id="printing:b:1",
            seen_at=base_time + timedelta(seconds=1),
        )
        store.record_pair(
            expected_card_id="printing:c:1",
            actual_card_id="printing:c:1",
            seen_at=base_time + timedelta(seconds=2),
        )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT expected_card_id, actual_card_id, seen_count
            FROM simulated_card_pairs
            ORDER BY expected_card_id
            """
        ).fetchall()

    assert rows == [
        ("printing:b:1", "printing:b:1", 1),
        ("printing:c:1", "printing:c:1", 1),
    ]
