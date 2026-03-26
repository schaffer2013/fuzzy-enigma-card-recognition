import json

from card_engine.catalog.local_index import CatalogRecord, LocalCatalogIndex
from card_engine.split_fixtures import (
    build_split_fixture_set_from_catalog,
    split_face_names,
    split_layout_records,
)


def test_split_face_names_parses_standard_split_name():
    assert split_face_names("Fire // Ice") == ("Fire", "Ice")
    assert split_face_names("Cromat") is None


def test_split_layout_records_only_returns_split_printings():
    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(name="Fire // Ice", normalized_name="", set_code="UMA", collector_number="225", layout="split", image_uri="https://example.com/fire-ice.png"),
            CatalogRecord(name="Opt", normalized_name="", set_code="XLN", collector_number="65", layout="normal", image_uri="https://example.com/opt.png"),
            CatalogRecord(name="Boom // Bust", normalized_name="", set_code="TSR", collector_number="156", layout="split", image_uri="https://example.com/boom-bust.png"),
        ]
    )

    records = split_layout_records(catalog)

    assert [record.name for record in records] == ["Boom // Bust", "Fire // Ice"]


def test_build_split_fixture_set_from_catalog_writes_sidecars(tmp_path):
    downloaded: list[tuple[str, str]] = []

    def fake_downloader(url: str, output_path):
        downloaded.append((url, output_path.name))
        output_path.write_bytes(_minimal_png())

    catalog = LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name="Fire // Ice",
                normalized_name="",
                set_code="UMA",
                collector_number="225",
                layout="split",
                type_line="Instant // Instant",
                oracle_text="Fire deals 2 damage divided as you choose among one or two targets. // Tap target permanent. Draw a card.",
                image_uri="https://example.com/fire-ice.png",
                games=("paper",),
            ),
        ]
    )

    written = build_split_fixture_set_from_catalog(catalog, output_dir=tmp_path, downloader=fake_downloader)

    assert len(written) == 1
    assert written[0].name == "fire-ice-uma-225.png"
    payload = json.loads(written[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["expected_name"] == "Fire // Ice"
    assert payload["layout_hint"] == "split"
    assert payload["ocr_text_by_roi"]["planar_title"] == "Fire"
    assert payload["ocr_text_by_roi"]["split_right"] == "Ice"
    assert downloaded == [("https://example.com/fire-ice.png", "fire-ice-uma-225.png")]


def _minimal_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01"
        b"\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\x0cIDATx\x9cc`\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00"
        b"\xc9\xfe\x92\xef"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
