import json
import sqlite3

from card_engine.catalog.build_catalog import build_catalog


def test_build_catalog_creates_cards_aliases_and_metadata(tmp_path):
    source_path = tmp_path / "default-cards.json"
    db_path = tmp_path / "cards.sqlite3"
    source_path.write_text(
        json.dumps(
            [
                {
                    "id": "bolt-1",
                    "oracle_id": "oracle-bolt",
                    "name": "Lightning Bolt",
                    "set": "M11",
                    "collector_number": "146",
                    "lang": "en",
                    "layout": "normal",
                    "type_line": "Instant",
                    "printed_name": "Lightning Bolt",
                },
                {
                    "id": "split-1",
                    "oracle_id": "oracle-split",
                    "name": "Fire // Ice",
                    "set": "DMR",
                    "collector_number": "200",
                    "lang": "en",
                    "layout": "split",
                    "type_line": "Instant",
                    "card_faces": [
                        {"name": "Fire", "printed_name": "Fire"},
                        {"name": "Ice", "printed_name": "Ice"},
                    ],
                },
                {
                    "id": "digital-only",
                    "name": "Ignored Card",
                    "set": "Y24",
                    "collector_number": "1",
                    "lang": "en",
                    "layout": "normal",
                    "digital": True,
                },
                {
                    "id": "foreign-card",
                    "name": "Carta",
                    "set": "ABC",
                    "collector_number": "2",
                    "lang": "es",
                    "layout": "normal",
                },
            ]
        ),
        encoding="utf-8",
    )

    stats = build_catalog(str(db_path), str(source_path))

    assert stats.card_count == 2
    assert stats.alias_count == 2

    with sqlite3.connect(db_path) as conn:
        cards = conn.execute("SELECT name, layout, type_line FROM cards ORDER BY name").fetchall()
        aliases = conn.execute("SELECT alias, normalized_alias FROM aliases ORDER BY alias").fetchall()
        metadata = dict(conn.execute("SELECT key, value FROM catalog_metadata").fetchall())

    assert cards == [
        ("Fire // Ice", "split", "Instant"),
        ("Lightning Bolt", "normal", "Instant"),
    ]
    assert aliases == [
        ("Fire", "fire"),
        ("Ice", "ice"),
    ]
    assert metadata["card_count"] == "2"
    assert metadata["alias_count"] == "2"
