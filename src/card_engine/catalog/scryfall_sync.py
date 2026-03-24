from __future__ import annotations

import importlib
import inspect
import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..fixture_cache import ensure_image_prehash


SCRYFALL_BULK_DATA_URL = "https://api.scryfall.com/bulk-data/default-cards"
USER_AGENT = "fuzzy-enigma-card-recognition/0.1.0"
DEFAULT_RANDOM_CARD_CACHE_LIMIT = 60
DEFAULT_RANDOM_CARD_QUERY = "game:paper lang:en"
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json;q=0.9,*/*;q=0.8",
}


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
    max_cached_cards: int = DEFAULT_RANDOM_CARD_CACHE_LIMIT,
    random_query: str = DEFAULT_RANDOM_CARD_QUERY,
) -> Path:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    client_factory = client_factory or _build_random_card_client
    downloader = downloader or _download_to_path

    card = _create_random_card(client_factory, random_query=random_query)
    card_name = _extract_card_value(card, "name", default="random-card")
    card_id = _extract_card_value(card, "id", default="random")
    image_url = _extract_card_image_url(card)

    parsed = urlparse(image_url)
    suffix = Path(parsed.path).suffix or ".png"
    filename = f"{_slugify(card_name)}-{str(card_id)[:8]}{suffix}"
    output_path = output_root / filename
    downloader(image_url, output_path)
    sidecar_payload = _build_fixture_sidecar(card)
    sidecar_payload["image_sha256"] = ensure_image_prehash(output_path)
    output_path.with_suffix(".json").write_text(json.dumps(sidecar_payload, indent=2, sort_keys=True), encoding="utf-8")
    prune_random_card_cache(output_root, max_cards=max_cached_cards)
    return output_path


def prune_random_card_cache(
    output_dir: str | Path,
    *,
    max_cards: int = DEFAULT_RANDOM_CARD_CACHE_LIMIT,
) -> int:
    if max_cards < 1:
        raise ValueError("max_cards must be at least 1.")

    output_root = Path(output_dir)
    if not output_root.exists():
        return 0

    grouped: dict[str, list[Path]] = {}
    for path in output_root.iterdir():
        if not path.is_file():
            continue
        grouped.setdefault(path.stem, []).append(path)

    if len(grouped) <= max_cards:
        return 0

    ordered_groups = sorted(
        grouped.items(),
        key=lambda item: max(member.stat().st_mtime for member in item[1]),
        reverse=True,
    )
    removed_count = 0
    for _stem, paths in ordered_groups[max_cards:]:
        for path in paths:
            path.unlink(missing_ok=True)
        removed_count += 1
    return removed_count


def _build_random_card_client(*, q: str = DEFAULT_RANDOM_CARD_QUERY):
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

    return scrython.cards.Random(q=q)


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
    request = Request(image_url, headers=REQUEST_HEADERS)
    with urlopen(request) as response:
        output_path.write_bytes(response.read())


def _build_fixture_sidecar(card) -> dict:
    card_name = _extract_card_value(card, "name", default="")
    type_line = _extract_card_value(card, "type_line", default="")
    oracle_text = _extract_card_value(card, "oracle_text", default="")
    layout = _extract_card_value(card, "layout", default="normal")
    language = _extract_card_value(card, "lang", default="")
    games = _extract_card_value(card, "games", default=[])
    set_code = _extract_card_value(card, "set", default="")
    collector_number = _extract_card_value(card, "collector_number", default="")
    face_payload = _extract_card_value(card, "card_faces", default=[])

    ocr_text_by_roi: dict[str, str] = {}
    if card_name:
        ocr_text_by_roi["standard"] = card_name
    if type_line:
        ocr_text_by_roi["type_line"] = type_line
    if oracle_text:
        ocr_text_by_roi["lower_text"] = oracle_text

    if isinstance(face_payload, list):
        ocr_text_by_roi.update(_face_roi_mapping(face_payload, layout))

    return {
        "expected_name": card_name or None,
        "expected_language": language or None,
        "expected_games": list(games) if isinstance(games, list) else None,
        "expected_set_code": set_code or None,
        "expected_collector_number": str(collector_number) if collector_number else None,
        "layout_hint": layout,
        "ocr_text_by_roi": ocr_text_by_roi,
    }


def _create_random_card(client_factory, *, random_query: str):
    signature = inspect.signature(client_factory)
    if "q" in signature.parameters:
        return client_factory(q=random_query)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return client_factory(q=random_query)
    return client_factory()


def _face_roi_mapping(face_payload: list, layout: str | None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    faces = [face for face in face_payload if isinstance(face, dict)]
    if not faces:
        return mapping

    normalized_layout = (layout or "").lower()
    if normalized_layout == "split":
        if len(faces) > 0 and faces[0].get("name"):
            mapping["split_left"] = faces[0]["name"]
        if len(faces) > 1 and faces[1].get("name"):
            mapping["split_right"] = faces[1]["name"]
        return mapping

    if normalized_layout == "adventure" and len(faces) > 1 and faces[1].get("name"):
        mapping["adventure"] = faces[1]["name"]
        return mapping

    if normalized_layout in {"transform", "modal_dfc"} and len(faces) > 1 and faces[1].get("name"):
        mapping["transform_back"] = faces[1]["name"]
        return mapping

    return mapping


def _fetch_json(url: str) -> dict:
    request = Request(url, headers=REQUEST_HEADERS)
    with urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise RuntimeError("Expected a JSON object from Scryfall.")
    return payload


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "-", value.strip()).strip("-").lower()
    return cleaned or "random-card"
