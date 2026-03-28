import json

from card_engine.catalog.build_catalog import build_catalog
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
    source_path = tmp_path / "default-cards.json"
    source_path.write_text(
        json.dumps(
            [
                {
                    "id": "opt-1",
                    "oracle_id": "oracle-opt",
                    "name": "Opt",
                    "set": "XLN",
                    "collector_number": "65",
                    "lang": "en",
                    "layout": "normal",
                    "type_line": "Instant",
                    "oracle_text": "Scry 1. Draw a card.",
                    "flavor_text": "The call of the sea.",
                    "image_uris": {"png": "https://img.example/opt.png"},
                    "printed_name": "Optimum",
                }
            ]
        ),
        encoding="utf-8",
    )

    build_catalog(str(db_path), str(source_path))

    index = LocalCatalogIndex.from_sqlite(str(db_path))

    matches = index.exact_lookup("Opt")
    assert [record.name for record in matches] == ["Opt"]
    assert matches[0].scryfall_id == "opt-1"
    assert matches[0].oracle_id == "oracle-opt"
    assert matches[0].collector_number == "65"
    assert matches[0].type_line == "Instant"
    assert matches[0].oracle_text == "Scry 1. Draw a card."
    assert matches[0].flavor_text == "The call of the sea."
    assert matches[0].image_uri == "https://img.example/opt.png"
    assert matches[0].aliases == ["Optimum"]


def test_exact_lookup_uses_aliases():
    index = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Fire // Ice", normalized_name="", aliases=["Fire", "Ice"]),
        ]
    )

    matches = index.exact_lookup("fire")

    assert [record.name for record in matches] == ["Fire // Ice"]


def test_search_name_skips_records_without_usable_search_strings():
    index = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Nameless", normalized_name="", aliases=[]),
            CatalogRecord(name="Lightning Bolt", normalized_name="", aliases=[]),
        ]
    )

    matches = index.search_name("lightning bot", limit=2)

    assert matches
    assert matches[0].record.name == "Lightning Bolt"


def test_search_name_fuzzy_scans_oracle_groups_before_printing_expansion():
    index = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Elspeth, Storm Slayer",
                normalized_name="",
                oracle_id="oracle-elspeth",
                set_code="TDM",
                collector_number="11",
            ),
            CatalogRecord(
                name="Elspeth, Storm Slayer",
                normalized_name="",
                oracle_id="oracle-elspeth",
                set_code="PTDM",
                collector_number="11p",
            ),
            CatalogRecord(
                name="Elspeth Tirel",
                normalized_name="",
                oracle_id="oracle-tirel",
                set_code="SOM",
                collector_number="9",
            ),
        ]
    )

    matches = index.search_name("Elspeth Storm Siayer", limit=3)

    assert matches
    assert matches[0].record.name == "Elspeth, Storm Slayer"
    assert len([match for match in matches if match.record.name == "Elspeth, Storm Slayer"]) == 1


def test_find_record_by_scryfall_id_and_oracle_group():
    index = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Opt",
                normalized_name="",
                scryfall_id="opt-1",
                oracle_id="oracle-opt",
                set_code="XLN",
                collector_number="65",
            ),
            CatalogRecord(
                name="Opt",
                normalized_name="",
                scryfall_id="opt-2",
                oracle_id="oracle-opt",
                set_code="M11",
                collector_number="73",
            ),
        ]
    )

    record = index.find_record_by_scryfall_id("OPT-1")
    oracle_records = index.records_for_oracle_id("ORACLE-OPT")

    assert record is not None
    assert record.set_code == "XLN"
    assert len(oracle_records) == 2
