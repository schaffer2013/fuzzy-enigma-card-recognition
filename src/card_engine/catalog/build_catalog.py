import sqlite3
from pathlib import Path


def build_catalog(db_path: str) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                set_code TEXT,
                collector_number TEXT,
                language TEXT DEFAULT 'en',
                layout TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_normalized_name ON cards(normalized_name)")
        conn.commit()
    return path
