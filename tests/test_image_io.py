import json

from card_engine.utils.image_io import load_image


def test_load_image_reads_png_dimensions(tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(_minimal_png(width=63, height=88))

    image = load_image(image_path)

    assert image.image_format == "png"
    assert image.width == 63
    assert image.height == 88
    assert image.shape == (88, 63, 3)
    assert image.content_hash is not None


def test_load_image_reads_sidecar_ocr_metadata(tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(_minimal_png(width=63, height=88))
    image_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "layout_hint": "normal",
                "ocr_text_by_roi": {
                    "standard": "Lightning Bolt",
                    "type_line": "Instant",
                    "lower_text": "Deal 3 damage to any target.",
                },
            }
        ),
        encoding="utf-8",
    )

    image = load_image(image_path)

    assert image.layout_hint == "normal"
    assert image.ocr_text_by_roi["standard"] == "Lightning Bolt"
    assert image.ocr_text_by_roi["type_line"] == "Instant"


def test_load_image_reads_saved_detection_by_prehash(tmp_path, monkeypatch):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(_minimal_png(width=63, height=88))
    image_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "saved_detection": {
                    "card_bbox": [1, 2, 30, 40],
                    "card_quad": [[1, 2], [31, 2], [31, 42], [1, 42]],
                },
            }
        ),
        encoding="utf-8",
    )

    reloaded = load_image(image_path)

    assert reloaded.card_bbox == (1, 2, 30, 40)
    assert reloaded.card_quad == ((1, 2), (31, 2), (31, 42), (1, 42))


def _minimal_png(*, width: int, height: int) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"\x00\x00\x00\x00"
        + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
