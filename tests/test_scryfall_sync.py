import json
import os
from pathlib import Path

from card_engine.catalog.scryfall_sync import fetch_random_card_image, prune_random_card_cache, sync_bulk_data


class DummyRandomCard:
    name = "Black Lotus"
    id = "abc12345-0000-0000-0000-000000000000"
    lang = "en"
    games = ["paper"]
    set = "lea"
    collector_number = "233"
    type_line = "Artifact"
    oracle_text = "Lots of mana."
    layout = "normal"
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
    sidecar = json.loads(output_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["expected_name"] == "Black Lotus"
    assert sidecar["expected_language"] == "en"
    assert sidecar["expected_games"] == ["paper"]
    assert sidecar["expected_set_code"] == "lea"
    assert sidecar["expected_collector_number"] == "233"
    assert len(sidecar["image_sha256"]) == 64
    assert sidecar["layout_hint"] == "normal"
    assert sidecar["ocr_text_by_roi"]["standard"] == "Black Lotus"
    assert sidecar["ocr_text_by_roi"]["type_line"] == "Artifact"
    assert sidecar["ocr_text_by_roi"]["lower_text"] == "Lots of mana."


def test_fetch_random_card_image_passes_english_query_to_client_factory(tmp_path):
    recorded: dict[str, str] = {}

    def fake_client_factory(*, q):
        recorded["q"] = q
        return DummyRandomCard()

    output_path = fetch_random_card_image(
        tmp_path,
        client_factory=fake_client_factory,
        downloader=lambda image_url, output_path: output_path.write_bytes(b"png"),
    )

    assert output_path.exists()
    assert recorded["q"] == "game:paper lang:en"


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


def test_prune_random_card_cache_removes_oldest_card_groups(tmp_path):
    newest = tmp_path / "newest-card.png"
    newest.write_bytes(b"png")
    newest.with_suffix(".json").write_text("{}", encoding="utf-8")

    middle = tmp_path / "middle-card.png"
    middle.write_bytes(b"png")
    middle.with_suffix(".json").write_text("{}", encoding="utf-8")

    oldest = tmp_path / "oldest-card.png"
    oldest.write_bytes(b"png")
    oldest.with_suffix(".json").write_text("{}", encoding="utf-8")

    os.utime(oldest, (1, 1))
    os.utime(oldest.with_suffix(".json"), (1, 1))
    os.utime(middle, (2, 2))
    os.utime(middle.with_suffix(".json"), (2, 2))
    os.utime(newest, (3, 3))
    os.utime(newest.with_suffix(".json"), (3, 3))

    removed = prune_random_card_cache(tmp_path, max_cards=2)

    assert removed == 1
    assert newest.exists()
    assert newest.with_suffix(".json").exists()
    assert middle.exists()
    assert middle.with_suffix(".json").exists()
    assert not oldest.exists()
    assert not oldest.with_suffix(".json").exists()


def test_fetch_random_card_image_prunes_cache_after_download(tmp_path):
    old_path = tmp_path / "old-card-deadbeef.png"
    old_path.write_bytes(b"png")
    old_path.with_suffix(".json").write_text("{}", encoding="utf-8")
    os.utime(old_path, (1, 1))
    os.utime(old_path.with_suffix(".json"), (1, 1))

    output_path = fetch_random_card_image(
        tmp_path,
        client_factory=lambda: DummyRandomCard(),
        downloader=lambda image_url, output_path: output_path.write_bytes(b"png"),
        max_cached_cards=1,
    )

    assert output_path.exists()
    assert output_path.with_suffix(".json").exists()
    assert not old_path.exists()
    assert not old_path.with_suffix(".json").exists()
