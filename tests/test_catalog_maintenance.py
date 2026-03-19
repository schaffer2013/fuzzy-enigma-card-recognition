import sqlite3
from pathlib import Path

from card_engine.catalog.maintenance import catalog_refresh_needed, ensure_catalog_ready


def test_catalog_refresh_needed_when_missing(tmp_path):
    needed, age_days = catalog_refresh_needed(db_path=str(tmp_path / "cards.sqlite3"), max_age_days=7)

    assert needed is True
    assert age_days is None


def test_catalog_refresh_needed_when_schema_version_missing(tmp_path):
    db_path = tmp_path / "cards.sqlite3"
    db_path.write_text("db", encoding="utf-8")

    needed, age_days = catalog_refresh_needed(db_path=str(db_path), max_age_days=7)

    assert needed is True
    assert age_days is not None


def test_ensure_catalog_ready_reuses_recent_catalog(tmp_path):
    db_path = tmp_path / "cards.sqlite3"
    source_path = tmp_path / "default-cards.json"
    source_path.write_text("[]", encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE catalog_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO catalog_metadata (key, value) VALUES ('schema_version', '2')"
        )
        conn.commit()

    messages: list[str] = []
    status = ensure_catalog_ready(
        db_path=str(db_path),
        source_json_path=str(source_path),
        max_age_days=7,
        progress_callback=messages.append,
    )

    assert status.refreshed is False
    assert status.action == "reuse"
    assert messages


def test_ensure_catalog_ready_downloads_and_builds_when_missing(tmp_path, monkeypatch):
    db_path = tmp_path / "cards.sqlite3"
    source_path = tmp_path / "default-cards.json"
    calls: list[str] = []

    def fake_sync(output_path: str):
        calls.append(f"sync:{output_path}")
        path = Path(output_path)
        path.write_text("[]", encoding="utf-8")
        return path

    def fake_build(output_db: str, input_json: str):
        calls.append(f"build:{output_db}:{input_json}")
        Path(output_db).write_text("sqlite", encoding="utf-8")
        return type(
            "DummyStats",
            (),
            {
                "card_count": 12,
                "alias_count": 2,
                "source_path": source_path,
                "database_path": db_path,
            },
        )()

    monkeypatch.setattr("card_engine.catalog.maintenance.sync_bulk_data", fake_sync)
    monkeypatch.setattr("card_engine.catalog.maintenance.build_catalog", fake_build)

    status = ensure_catalog_ready(
        db_path=str(db_path),
        source_json_path=str(source_path),
        max_age_days=7,
    )

    assert status.refreshed is True
    assert status.action == "missing"
    assert calls == [
        f"sync:{source_path}",
        f"build:{db_path}:{source_path}",
    ]
