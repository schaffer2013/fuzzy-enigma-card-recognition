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
                    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                    "flavor_text": "The sparkmage shrieked, calling on the rage of the storms of his youth.",
                    "image_uris": {"png": "https://img.example/bolt.png"},
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
                    "oracle_text": "Choose one or both.",
                    "flavor_text": "Double trouble.",
                    "card_faces": [
                        {"name": "Fire", "printed_name": "Fire", "image_uris": {"png": "https://img.example/fire.png"}},
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
        cards = conn.execute(
            "SELECT name, layout, type_line, oracle_text, flavor_text, image_uri FROM cards ORDER BY name"
        ).fetchall()
        aliases = conn.execute("SELECT alias, normalized_alias FROM aliases ORDER BY alias").fetchall()
        metadata = dict(conn.execute("SELECT key, value FROM catalog_metadata").fetchall())

    assert cards == [
        ("Fire // Ice", "split", "Instant", "Choose one or both.", "Double trouble.", "https://img.example/fire.png"),
        (
            "Lightning Bolt",
            "normal",
            "Instant",
            "Lightning Bolt deals 3 damage to any target.",
            "The sparkmage shrieked, calling on the rage of the storms of his youth.",
            "https://img.example/bolt.png",
        ),
    ]
    assert aliases == [
        ("Fire", "fire"),
        ("Ice", "ice"),
    ]
    assert metadata["card_count"] == "2"
    assert metadata["alias_count"] == "2"
    assert metadata["schema_version"] == "3"
