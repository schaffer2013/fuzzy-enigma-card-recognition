import json

from card_engine.catalog.build_catalog import build_catalog
from card_engine.catalog.query import OfflineCatalogQuery


def test_offline_catalog_query_returns_oracle_and_printing_rows(tmp_path):
    db_path = tmp_path / "cards.sqlite3"
    source_path = tmp_path / "default-cards.json"
    source_path.write_text(
        json.dumps(
            [
                {
                    "id": "printing-opt-xln",
                    "oracle_id": "oracle-opt",
                    "name": "Opt",
                    "set": "xln",
                    "collector_number": "65",
                    "lang": "en",
                    "layout": "normal",
                    "mana_cost": "{U}",
                    "type_line": "Instant",
                    "oracle_text": "Scry 1. Draw a card.",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "rarity": "common",
                    "artist": "Volkan Baga",
                    "released_at": "2017-09-29",
                    "games": ["paper"],
                    "image_uris": {"png": "https://img.example/opt-xln.png"},
                },
                {
                    "id": "printing-opt-inv",
                    "oracle_id": "oracle-opt",
                    "name": "Opt",
                    "set": "inv",
                    "collector_number": "64",
                    "lang": "en",
                    "layout": "normal",
                    "mana_cost": "{U}",
                    "type_line": "Instant",
                    "oracle_text": "Scry 1. Draw a card.",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "rarity": "common",
                    "artist": "Volkan Baga",
                    "released_at": "2000-10-02",
                    "games": ["paper", "mtgo"],
                    "image_uris": {"png": "https://img.example/opt-inv.png"},
                },
                {
                    "id": "printing-arena",
                    "oracle_id": "oracle-digital",
                    "name": "Arena Only",
                    "set": "j21",
                    "collector_number": "2",
                    "lang": "en",
                    "layout": "normal",
                    "games": ["arena"],
                    "image_uris": {"png": "https://img.example/arena-only.png"},
                },
            ]
        ),
        encoding="utf-8",
    )

    build_catalog(str(db_path), str(source_path))
    query = OfflineCatalogQuery.from_sqlite(db_path)

    oracle = query.get_oracle_card("oracle-opt")
    assert oracle is not None
    assert oracle.name == "Opt"
    assert oracle.colors == ("U",)

    printings = query.printings_for_oracle("oracle-opt")
    assert [(row.set_code, row.collector_number) for row in printings] == [("xln", "65"), ("inv", "64")]

    by_name = query.printings_for_name("Opt")
    assert len(by_name) == 2
    assert all(row.oracle_id == "oracle-opt" for row in by_name)

    exact = query.get_printed_card("printing-opt-xln")
    assert exact is not None
    assert exact.name == "Opt"
    assert exact.games == ("paper",)

    search = query.find_printed_cards(name_query="Opt", set_code="inv")
    assert [(row.set_code, row.collector_number) for row in search] == [("inv", "64")]


def test_offline_catalog_query_finds_oracle_cards_by_name(tmp_path):
    db_path = tmp_path / "cards.sqlite3"
    source_path = tmp_path / "default-cards.json"
    source_path.write_text(
        json.dumps(
            [
                {
                    "id": "printing-fireice",
                    "oracle_id": "oracle-fireice",
                    "name": "Fire // Ice",
                    "set": "apc",
                    "collector_number": "128",
                    "lang": "en",
                    "layout": "split",
                    "oracle_text": "Fire text",
                    "games": ["paper"],
                    "image_uris": {"png": "https://img.example/fireice.png"},
                }
            ]
        ),
        encoding="utf-8",
    )

    build_catalog(str(db_path), str(source_path))
    query = OfflineCatalogQuery.from_sqlite(db_path)

    rows = query.find_oracle_cards("Fire // Ice")
    assert len(rows) == 1
    assert rows[0].oracle_id == "oracle-fireice"
