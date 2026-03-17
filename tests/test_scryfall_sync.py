from pathlib import Path

from card_engine.catalog.scryfall_sync import fetch_random_card_image


class DummyRandomCard:
    name = "Black Lotus"
    id = "abc12345-0000-0000-0000-000000000000"
    image_uris = {
        "png": "https://cards.scryfall.io/png/front/a/b/abc12345.png",
    }


def test_fetch_random_card_image_downloads_to_cache(tmp_path):
    downloaded: dict[str, str] = {}

    def fake_downloader(image_url: str, output_path: Path) -> None:
        downloaded["url"] = image_url
        output_path.write_bytes(b"png")

    output_path = fetch_random_card_image(
        tmp_path,
        client_factory=lambda: DummyRandomCard(),
        downloader=fake_downloader,
    )

    assert output_path.name == "black-lotus-abc12345.png"
    assert output_path.read_bytes() == b"png"
    assert downloaded["url"].endswith(".png")
