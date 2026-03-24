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
                    "games": ["paper", "mtgo"],
                    "layout": "normal",
                    "mana_cost": "{R}",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "type_line": "Instant",
                    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                    "rarity": "common",
                    "flavor_text": "The sparkmage shrieked, calling on the rage of the storms of his youth.",
                    "artist": "Christopher Moeller",
                    "released_at": "2010-07-16",
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
                    "games": ["paper"],
                    "layout": "split",
                    "colors": ["R", "U"],
                    "color_identity": ["R", "U"],
                    "flavor_text": "Double trouble.",
                    "rarity": "rare",
                    "artist": "Kev Walker",
                    "released_at": "2022-12-02",
                    "card_faces": [
                        {
                            "name": "Fire",
                            "printed_name": "Fire",
                            "mana_cost": "{1}{R}",
                            "type_line": "Instant",
                            "oracle_text": "Fire deals 2 damage divided as you choose among one or two targets.",
                            "image_uris": {"png": "https://img.example/fire.png"},
                        },
                        {
                            "name": "Ice",
                            "printed_name": "Ice",
                            "mana_cost": "{1}{U}",
                            "type_line": "Instant",
                            "oracle_text": "Tap target permanent. Draw a card.",
                        },
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
                    "id": "arena-only",
                    "oracle_id": "oracle-arena",
                    "name": "Arena Only",
                    "set": "Y24",
                    "collector_number": "2",
                    "lang": "en",
                    "games": ["arena"],
                    "layout": "normal",
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
            """
            SELECT
                name,
                mana_cost,
                colors,
                color_identity,
                rarity,
                layout,
                type_line,
                oracle_text,
                flavor_text,
                artist,
                released_at,
                games,
                image_uri
            FROM cards
            ORDER BY name
            """
        ).fetchall()
        printed_count = conn.execute("SELECT COUNT(*) FROM printed_cards").fetchone()[0]
        oracle_count = conn.execute("SELECT COUNT(*) FROM oracle_cards").fetchone()[0]
        aliases = conn.execute("SELECT alias, normalized_alias FROM aliases ORDER BY alias").fetchall()
        metadata = dict(conn.execute("SELECT key, value FROM catalog_metadata").fetchall())

    assert cards == [
        (
            "Fire // Ice",
            "{1}{R} // {1}{U}",
            '["R", "U"]',
            '["R", "U"]',
            "rare",
            "split",
            "Instant // Instant",
            "Fire deals 2 damage divided as you choose among one or two targets. // Tap target permanent. Draw a card.",
            "Double trouble.",
            "Kev Walker",
            "2022-12-02",
            '["paper"]',
            "https://img.example/fire.png",
        ),
        (
            "Lightning Bolt",
            "{R}",
            '["R"]',
            '["R"]',
            "common",
            "normal",
            "Instant",
            "Lightning Bolt deals 3 damage to any target.",
            "The sparkmage shrieked, calling on the rage of the storms of his youth.",
            "Christopher Moeller",
            "2010-07-16",
            '["paper", "mtgo"]',
            "https://img.example/bolt.png",
        ),
    ]
    assert printed_count == 2
    assert oracle_count == 2
    assert aliases == [
        ("Fire", "fire"),
        ("Ice", "ice"),
    ]
    assert metadata["card_count"] == "2"
    assert metadata["oracle_card_count"] == "2"
    assert metadata["alias_count"] == "2"
    assert metadata["schema_version"] == "4"
