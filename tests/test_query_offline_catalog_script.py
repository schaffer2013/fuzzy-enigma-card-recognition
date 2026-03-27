import json

from card_engine.catalog.build_catalog import build_catalog
from scripts.query_offline_catalog import main


def test_query_offline_catalog_script_printings_for_name(tmp_path, capsys):
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

    exit_code = main(
        [
            "--catalog",
            str(db_path),
            "printings-for-name",
            "Fire // Ice",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(payload) == 1
    assert payload[0]["oracle_id"] == "oracle-fireice"
