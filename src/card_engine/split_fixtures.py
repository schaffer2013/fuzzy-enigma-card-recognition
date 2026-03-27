from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .catalog.scryfall_sync import REQUEST_HEADERS
from .fixture_cache import ensure_image_prehash

DEFAULT_SPLIT_FIXTURES_DIR = Path("data") / "sample_outputs" / "split_layout_eval_cards"

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def build_split_fixture_set(
    *,
    catalog_path: str | Path,
    output_dir: str | Path = DEFAULT_SPLIT_FIXTURES_DIR,
    family: str | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    downloader=None,
    progress_callback=None,
) -> list[Path]:
    catalog = LocalCatalogIndex.from_sqlite(str(catalog_path))
    return build_split_fixture_set_from_catalog(
        catalog,
        output_dir=output_dir,
        family=family,
        limit=limit,
        overwrite=overwrite,
        downloader=downloader,
        progress_callback=progress_callback,
    )


def build_split_fixture_set_from_catalog(
    catalog: LocalCatalogIndex,
    *,
    output_dir: str | Path = DEFAULT_SPLIT_FIXTURES_DIR,
    family: str | None = None,
    limit: int | None = None,
    overwrite: bool = False,
    downloader=None,
    progress_callback=None,
) -> list[Path]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    downloader = downloader or _download_to_path

    records = split_layout_records(catalog, family=family)
    if limit is not None:
        records = records[: max(0, limit)]

    written_paths: list[Path] = []
    total = len(records)
    for index, record in enumerate(records, start=1):
        _notify(
            progress_callback,
            f"[split-fixtures] {index}/{total}: {record.name} [{record.set_code or '?'} {record.collector_number or '?'}]",
        )
        output_path = _fixture_image_path(output_root, record)
        sidecar_path = output_path.with_suffix(".json")
        if overwrite or not output_path.exists():
            downloader(record.image_uri or "", output_path)
        sidecar_path.write_text(json.dumps(_build_split_sidecar(record), indent=2, sort_keys=True), encoding="utf-8")
        written_paths.append(output_path)
    return written_paths


def split_layout_records(catalog: LocalCatalogIndex, *, family: str | None = None) -> list[CatalogRecord]:
    normalized_family = (family or "").strip().lower()
    records = [
        record
        for record in catalog.records
        if (record.layout or "").lower() == "split"
        and record.image_uri
        and (not normalized_family or split_layout_family(record) == normalized_family)
    ]
    records.sort(
        key=lambda record: (
            record.released_at or "",
            record.name.lower(),
            (record.set_code or "").lower(),
            (record.collector_number or "").lower(),
        )
    )
    return records


def split_face_names(name: str | None) -> tuple[str, str] | None:
    if not name:
        return None
    if " // " not in name:
        return None
    left, right = name.split(" // ", 1)
    left = left.strip()
    right = right.strip()
    if not left or not right:
        return None
    return left, right


def split_layout_family(record: CatalogRecord) -> str:
    name = record.name or ""
    type_line = (record.type_line or "").casefold()
    oracle_text = (record.oracle_text or "").casefold()
    face_count = name.count(" // ") + 1 if name else 1

    if "room" in type_line:
        return "room"
    if face_count >= 3:
        return "multi_split"
    if "aftermath" in oracle_text:
        return "aftermath"
    if "fuse" in oracle_text:
        return "fuse"
    if face_count == 2:
        return "classic_split"
    return "other_split"


def _build_split_sidecar(record: CatalogRecord) -> dict:
    ocr_text_by_roi: dict[str, str] = {"standard": record.name}
    if record.type_line:
        ocr_text_by_roi["type_line"] = record.type_line
    if record.oracle_text:
        ocr_text_by_roi["lower_text"] = record.oracle_text

    face_names = split_face_names(record.name)
    if face_names is not None:
        left_name, right_name = face_names
        ocr_text_by_roi["planar_title"] = left_name
        ocr_text_by_roi["split_left"] = left_name
        ocr_text_by_roi["split_right"] = right_name

    sidecar = {
        "expected_name": record.name,
        "expected_set_code": record.set_code,
        "expected_collector_number": record.collector_number,
        "expected_games": list(record.games or ()) or ["paper"],
        "layout_hint": record.layout or "split",
        "split_family": split_layout_family(record),
        "ocr_text_by_roi": ocr_text_by_roi,
    }
    return sidecar


def _fixture_image_path(output_root: Path, record: CatalogRecord) -> Path:
    parsed = urlparse(record.image_uri or "")
    suffix = Path(parsed.path).suffix or ".png"
    file_name = "-".join(
        [
            _slugify(record.name),
            _slugify(record.set_code or "set"),
            _slugify(record.collector_number or "card")[:24],
        ]
    )
    return output_root / f"{file_name}{suffix}"


def _slugify(value: str) -> str:
    return _NON_ALNUM.sub("-", (value or "").lower()).strip("-") or "card"


def _notify(callback, message: str) -> None:
    if callback is None:
        return
    try:
        callback(message)
    except UnicodeEncodeError:
        callback(str(message).encode("ascii", "replace").decode("ascii"))


def _download_to_path(image_url: str, output_path: Path) -> None:
    request = Request(image_url, headers=REQUEST_HEADERS)
    with urlopen(request, timeout=30) as response:
        output_path.write_bytes(response.read())
    ensure_image_prehash(output_path)
