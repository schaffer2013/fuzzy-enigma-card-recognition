from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SCRYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data/default-cards"
USER_AGENT = "card-recognition-engine/0.1.0"


def sync_bulk_data(output_path: str) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    metadata = _fetch_json(SCRYFALL_BULK_DATA_URL)
    download_uri = metadata.get("download_uri")
    if not isinstance(download_uri, str) or not download_uri:
        raise RuntimeError("Scryfall bulk-data response did not include a download_uri.")

    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    _download_to_path(download_uri, temp_path)
    temp_path.replace(path)
    return path


def fetch_random_card_image(
    output_dir: str | Path,
    *,
    client_factory=None,
    downloader=None,
) -> Path:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    client_factory = client_factory or _build_random_card_client
    downloader = downloader or _download_to_path

    card = client_factory()
    card_name = _extract_card_value(card, "name", default="random-card")
    card_id = _extract_card_value(card, "id", default="random")
    image_url = _extract_card_image_url(card)

    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix or ".png"
    filename = f"{_slugify(card_name)}-{str(card_id)[:8]}{suffix}"
    output_path = output_root / filename
    downloader(image_url, output_path)
    return output_path


def _build_random_card_client():
    try:
        scrython = importlib.import_module("scrython")
    except ImportError as exc:
        raise RuntimeError("Scrython is not installed. Install it to enable random card downloads.") from exc

    try:
        request_handler_module = importlib.import_module("scrython.base")
    except ImportError:
        request_handler_module = None

    if request_handler_module is not None:
        handler = getattr(request_handler_module, "ScrythonRequestHandler", None)
        if handler is not None and hasattr(handler, "set_user_agent"):
            handler.set_user_agent(USER_AGENT)

    return scrython.cards.Random()


def _extract_card_image_url(card) -> str:
    image_url = None

    get_image_url = getattr(card, "get_image_url", None)
    if callable(get_image_url):
        for size in ("png", "large", "normal"):
            try:
                image_url = get_image_url(size=size)
            except TypeError:
                image_url = get_image_url()
            if image_url:
                return image_url

    image_uris = _extract_card_value(card, "image_uris")
    if isinstance(image_uris, dict):
        for key in ("png", "large", "normal"):
            if image_uris.get(key):
                return image_uris[key]

    card_faces = _extract_card_value(card, "card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if not isinstance(face, dict):
                continue
            face_uris = face.get("image_uris")
            if not isinstance(face_uris, dict):
                continue
            for key in ("png", "large", "normal"):
                if face_uris.get(key):
                    return face_uris[key]

    raise RuntimeError("Could not determine a downloadable image URL for the random card.")


def _extract_card_value(card, key: str, default=None):
    attribute = getattr(card, key, None)
    if callable(attribute):
        try:
            return attribute()
        except TypeError:
            return default
    if attribute is not None:
        return attribute

    to_dict = getattr(card, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict) and key in data:
            return data[key]

    raw_json = getattr(card, "scryfallJson", None)
    if isinstance(raw_json, dict):
        return raw_json.get(key, default)

    return default


def _download_to_path(image_url: str, output_path: Path) -> None:
    request = Request(image_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        output_path.write_bytes(response.read())


def _fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise RuntimeError("Expected a JSON object from Scryfall.")
    return payload


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "-", value.strip()).strip("-").lower()
    return cleaned or "random-card"
