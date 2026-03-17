from card_engine.utils.image_io import load_image


def test_load_image_reads_png_dimensions(tmp_path):
    image_path = tmp_path / "fixture.png"
    image_path.write_bytes(_minimal_png(width=63, height=88))

    image = load_image(image_path)

    assert image.image_format == "png"
    assert image.width == 63
    assert image.height == 88
    assert image.shape == (88, 63, 3)


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
