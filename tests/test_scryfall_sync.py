from pathlib import Path

from card_engine.catalog.scryfall_sync import fetch_random_card_image, sync_bulk_data


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


def test_sync_bulk_data_downloads_default_cards_json(tmp_path, monkeypatch):
    class DummyResponse:
        def __init__(self, payload: bytes):
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    calls: list[str] = []

    def fake_urlopen(request):
        url = request.full_url
        calls.append(url)
        if url.endswith("/bulk-data/default-cards"):
            return DummyResponse(b'{"download_uri":"https://example.com/default-cards.json"}')
        if url == "https://example.com/default-cards.json":
            return DummyResponse(b"[{\"id\":\"card-1\",\"name\":\"Opt\",\"lang\":\"en\"}]")
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("card_engine.catalog.scryfall_sync.urlopen", fake_urlopen)

    output_path = sync_bulk_data(str(tmp_path / "default-cards.json"))

    assert output_path.read_text(encoding="utf-8") == '[{"id":"card-1","name":"Opt","lang":"en"}]'
    assert calls == [
        "https://api.scryfall.com/bulk-data/default-cards",
        "https://example.com/default-cards.json",
    ]
