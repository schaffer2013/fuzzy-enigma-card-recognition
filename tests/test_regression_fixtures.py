import json
import struct
import zlib

from card_engine.eval_pair_store import SimulatedPairStore
from card_engine.regression_fixtures import (
    build_expected_fixture_index,
    export_regression_fixture_set,
    load_grouped_mismatches,
)


def test_load_grouped_mismatches_groups_by_expected_card_and_sorts_counts(tmp_path):
    db_path = tmp_path / "pairs.sqlite3"
    with SimulatedPairStore(db_path) as store:
        for _ in range(4):
            store.record_pair(expected_card_id="printing:lea:1", actual_card_id="printing:2ed:1")
        for _ in range(2):
            store.record_pair(expected_card_id="printing:lea:1", actual_card_id="printing:3ed:1")
        for _ in range(3):
            store.record_pair(expected_card_id="printing:mh2:1", actual_card_id="unrecognized")
        store.record_pair(expected_card_id="printing:tmp:1", actual_card_id="printing:tmp:1")

    grouped = load_grouped_mismatches(db_path, max_cases=2, min_seen_count=2)

    assert [expected for expected, _ in grouped] == ["printing:lea:1", "printing:mh2:1"]
    assert [m.actual_card_id for m in grouped[0][1]] == ["printing:2ed:1", "printing:3ed:1"]
    assert [m.seen_count for m in grouped[0][1]] == [4, 2]


def test_export_regression_fixture_set_copies_matching_fixtures_and_manifest(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    matched_fixture = fixtures_dir / "armageddon-12345678.png"
    matched_fixture.write_bytes(_minimal_png(width=80, height=100))
    matched_fixture.with_suffix(".json").write_text(
        json.dumps(
            {
                "expected_name": "Armageddon",
                "expected_set_code": "5ed",
                "expected_collector_number": "7",
            }
        ),
        encoding="utf-8",
    )

    unmatched_fixture = fixtures_dir / "opt-87654321.png"
    unmatched_fixture.write_bytes(_minimal_png(width=80, height=100))
    unmatched_fixture.with_suffix(".json").write_text(
        json.dumps(
            {
                "expected_name": "Opt",
                "expected_set_code": "inv",
                "expected_collector_number": "64",
            }
        ),
        encoding="utf-8",
    )

    db_path = tmp_path / "pairs.sqlite3"
    with SimulatedPairStore(db_path) as store:
        for _ in range(3):
            store.record_pair(expected_card_id="printing:5ed:7", actual_card_id="printing:por:5")
        for _ in range(2):
            store.record_pair(expected_card_id="printing:ltr:732z", actual_card_id="unrecognized")

    fixture_index = build_expected_fixture_index(fixtures_dir)
    assert fixture_index["printing:5ed:7"].name == "armageddon-12345678.png"

    output_dir = tmp_path / "regressions"
    export = export_regression_fixture_set(
        fixtures_dir,
        output_dir,
        db_path=db_path,
        max_cases=5,
        min_seen_count=2,
    )

    assert export.copied_fixture_count == 1
    assert export.missing_expected_ids == ["printing:ltr:732z"]
    assert (output_dir / "armageddon-12345678.png").exists()
    assert (output_dir / "armageddon-12345678.json").exists()
    assert not (output_dir / "opt-87654321.png").exists()

    manifest = json.loads((output_dir / "regression_manifest.json").read_text(encoding="utf-8"))
    assert manifest["copied_fixture_count"] == 1
    assert manifest["missing_expected_ids"] == ["printing:ltr:732z"]
    assert manifest["cases"][0]["expected_card_id"] == "printing:5ed:7"
    assert manifest["cases"][0]["fixture_path"] == "armageddon-12345678.png"
    assert manifest["cases"][0]["mismatches"][0]["actual_card_id"] == "printing:por:5"


def _minimal_png(*, width: int, height: int) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    row = b"\x00" + (b"\x7f\x7f\x7f" * width)
    image_data = zlib.compress(row * height)
    idat = chunk(b"IDAT", image_data)
    iend = chunk(b"IEND", b"")
    return header + ihdr + idat + iend
