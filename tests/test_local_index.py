import sqlite3

from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex


def test_exact_lookup_normalizes_case_and_punctuation():
    index = LocalCatalogIndex.from_records(
        [CatalogRecord(name="Nicol Bolas, Dragon-God", normalized_name="")]
    )

    matches = index.exact_lookup("nicol bolas dragon god")

    assert [record.name for record in matches] == ["Nicol Bolas, Dragon-God"]


def test_search_name_returns_best_fuzzy_match_first():
    index = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Lightning Bolt", normalized_name=""),
            CatalogRecord(name="Chain Lightning", normalized_name=""),
            CatalogRecord(name="Lightning Helix", normalized_name=""),
        ]
    )

    matches = index.search_name("lightning bot", limit=2)

    assert matches[0].record.name == "Lightning Bolt"
    assert matches[0].match_type == "fuzzy"
    assert len(matches) == 2


def test_from_sqlite_loads_catalog_rows(tmp_path):
    db_path = tmp_path / "cards.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE cards (
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
        conn.execute(
            """
            INSERT INTO cards (name, normalized_name, set_code, collector_number, layout)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("Opt", "opt", "XLN", "65", "normal"),
        )
        conn.commit()

    index = LocalCatalogIndex.from_sqlite(str(db_path))

    matches = index.exact_lookup("Opt")
    assert [record.name for record in matches] == ["Opt"]
    assert matches[0].collector_number == "65"
