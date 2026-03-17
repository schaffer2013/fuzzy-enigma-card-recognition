from pathlib import Path

from card_engine.api import recognize_card


class DummyImage:
    shape = (100, 80, 3)


def test_recognize_card_returns_result_shape():
    result = recognize_card(DummyImage())
    assert result.bbox == (0, 0, 80, 100)
    assert result.active_roi == "standard"


def test_recognize_card_accepts_image_path(tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(_minimal_png(width=80, height=100))

    result = recognize_card(image_path)

    assert result.bbox == (0, 0, 80, 100)
    assert result.debug["image"]["source"] == str(image_path)
    assert result.debug["image"]["shape"] == (100, 80, 3)


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
