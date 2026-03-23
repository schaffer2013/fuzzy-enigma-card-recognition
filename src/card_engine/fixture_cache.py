from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def ensure_image_prehash(
    image_path: str | Path,
    *,
    image_bytes: bytes | None = None,
) -> str:
    path = Path(image_path)
    payload = _read_sidecar_payload(path)
    cached_hash = payload.get("image_sha256")
    if isinstance(cached_hash, str) and len(cached_hash) == 64:
        return cached_hash

    digest = hashlib.sha256(image_bytes if image_bytes is not None else path.read_bytes()).hexdigest()
    payload["image_sha256"] = digest
    _write_sidecar_payload(path, payload)
    return digest


def lookup_saved_detection(
    image_path: str | Path,
    *,
    image_sha256: str | None,
) -> tuple[tuple[int, int, int, int] | None, tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None]:
    path = Path(image_path)
    payload = _read_sidecar_payload(path)
    record = payload.get("saved_detection")
    if not isinstance(record, dict):
        return None, None

    bbox = _coerce_bbox(record.get("card_bbox"))
    quad = _coerce_quad(record.get("card_quad"))
    return bbox, quad


def persist_saved_detection(
    image_path: str | Path,
    *,
    image_sha256: str | None,
    bbox: tuple[int, int, int, int] | None,
    quad: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None,
) -> bool:
    path = Path(image_path)
    if image_sha256 is None or bbox is None:
        return False

    payload = _read_sidecar_payload(path)
    sidecar_record = {
        "card_bbox": list(bbox),
        "card_quad": [[point[0], point[1]] for point in quad] if quad is not None else None,
    }
    changed = payload.get("saved_detection") != sidecar_record
    payload["saved_detection"] = sidecar_record
    if changed:
        payload.pop("cached_observed_fingerprints", None)
    _write_sidecar_payload(path, payload)
    return changed


def load_cached_observed_fingerprints(
    image_path: str | Path,
    *,
    image_sha256: str | None,
    bbox: tuple[int, int, int, int] | None,
    quad: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None,
) -> dict[str, dict[str, Any]]:
    payload = _read_sidecar_payload(Path(image_path))
    cached = payload.get("cached_observed_fingerprints")
    if not isinstance(cached, dict):
        return {}

    if cached.get("signature") != _fingerprint_signature(image_sha256=image_sha256, bbox=bbox, quad=quad):
        return {}

    loaded: dict[str, dict[str, Any]] = {}
    for key in ("set_symbol", "art_match"):
        value = cached.get(key)
        if isinstance(value, dict):
            loaded[key] = value
    return loaded


def persist_cached_observed_fingerprints(
    image_path: str | Path,
    *,
    image_sha256: str | None,
    bbox: tuple[int, int, int, int] | None,
    quad: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None,
    set_symbol: dict[str, Any] | None = None,
    art_match: dict[str, Any] | None = None,
) -> None:
    if image_sha256 is None or bbox is None:
        return

    payload = _read_sidecar_payload(Path(image_path))
    cached = payload.get("cached_observed_fingerprints")
    signature = _fingerprint_signature(image_sha256=image_sha256, bbox=bbox, quad=quad)
    if not isinstance(cached, dict) or cached.get("signature") != signature:
        cached = {"signature": signature}
    if set_symbol is not None:
        cached["set_symbol"] = set_symbol
    if art_match is not None:
        cached["art_match"] = art_match
    payload["cached_observed_fingerprints"] = cached
    _write_sidecar_payload(Path(image_path), payload)


def _fingerprint_signature(
    *,
    image_sha256: str | None,
    bbox: tuple[int, int, int, int] | None,
    quad: tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None,
) -> dict[str, Any]:
    return {
        "image_sha256": image_sha256,
        "card_bbox": list(bbox) if bbox is not None else None,
        "card_quad": [[point[0], point[1]] for point in quad] if quad is not None else None,
    }


def _read_sidecar_payload(image_path: Path) -> dict[str, Any]:
    sidecar_path = image_path.with_suffix(".json")
    if not sidecar_path.exists():
        return {}
    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_sidecar_payload(image_path: Path, payload: dict[str, Any]) -> None:
    sidecar_path = image_path.with_suffix(".json")
    sidecar_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _coerce_bbox(value: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return tuple(int(component) for component in value)
    except (TypeError, ValueError):
        return None


def _coerce_quad(value: Any) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return tuple((int(point[0]), int(point[1])) for point in value)
    except (TypeError, ValueError, IndexError):
        return None
