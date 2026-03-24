from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from card_engine.utils.text_normalize import normalize_text

CATALOG_SCHEMA_VERSION = "4"


@dataclass(frozen=True)
class CatalogBuildStats:
    card_count: int
    alias_count: int
    source_path: Path
    database_path: Path


def build_catalog(db_path: str, source_path: str) -> CatalogBuildStats:
    source = Path(source_path)
    database = Path(db_path)
    database.parent.mkdir(parents=True, exist_ok=True)

    oracle_cards, printed_cards, aliases = _load_catalog_rows(source)

    temp_path = database.with_suffix(f"{database.suffix}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    conn = sqlite3.connect(temp_path)
    try:
        _create_schema(conn)
        conn.executemany(
            """
            INSERT INTO oracle_cards (
                oracle_id,
                name,
                normalized_name,
                layout,
                mana_cost,
                type_line,
                oracle_text,
                colors,
                color_identity
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            oracle_cards,
        )
        conn.executemany(
            """
            INSERT INTO printed_cards (
                scryfall_id,
                oracle_id,
                printed_name,
                set_code,
                collector_number,
                language,
                rarity,
                flavor_text,
                artist,
                released_at,
                image_uri,
                games
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            printed_cards,
        )
        conn.executemany(
            """
            INSERT INTO aliases (
                card_id,
                alias,
                normalized_alias
            )
            SELECT id, ?, ?
            FROM printed_cards
            WHERE scryfall_id = ?
            """,
            aliases,
        )
        conn.execute(
            """
            INSERT INTO catalog_metadata (key, value)
            VALUES
                ('source_path', ?),
                ('card_count', ?),
                ('oracle_card_count', ?),
                ('alias_count', ?),
                ('schema_version', ?)
            """,
            (
                str(source),
                str(len(printed_cards)),
                str(len(oracle_cards)),
                str(len(aliases)),
                CATALOG_SCHEMA_VERSION,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    temp_path.replace(database)
    return CatalogBuildStats(
        card_count=len(printed_cards),
        alias_count=len(aliases),
        source_path=source,
        database_path=database,
    )


def _load_catalog_rows(
    source_path: Path,
) -> tuple[
    list[tuple[str, str, str, str | None, str | None, str | None, str, str, str]],
    list[tuple[str, str, str | None, str | None, str | None, str, str | None, str | None, str | None, str | None, str | None, str]],
    list[tuple[str, str, str]],
]:
    raw_cards = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw_cards, list):
        raise ValueError("Catalog source JSON must contain a top-level list")

    oracle_cards_by_id: dict[str, tuple[str, str, str, str | None, str | None, str | None, str, str, str]] = {}
    printed_cards: list[tuple[str, str, str | None, str | None, str | None, str, str | None, str | None, str | None, str | None, str | None, str]] = []
    aliases: list[tuple[str, str, str]] = []

    for card in raw_cards:
        if not isinstance(card, dict):
            continue
        if card.get("lang") != "en":
            continue
        if not _is_paper_printing(card):
            continue

        scryfall_id = str(card.get("id") or "").strip()
        name = str(card.get("name") or "").strip()
        if not scryfall_id or not name:
            continue

        oracle_id = _derive_oracle_id(card, scryfall_id)
        if oracle_id not in oracle_cards_by_id:
            oracle_cards_by_id[oracle_id] = (
                oracle_id,
                name,
                normalize_text(name),
                _clean_optional(card.get("layout")),
                _extract_joined_face_text(card, "mana_cost"),
                _extract_joined_face_text(card, "type_line"),
                _extract_joined_face_text(card, "oracle_text"),
                _encode_string_list(_extract_string_list(card, "colors")),
                _encode_string_list(_extract_string_list(card, "color_identity")),
            )

        printed_cards.append(
            (
                scryfall_id,
                oracle_id,
                _clean_optional(card.get("printed_name")),
                _clean_optional(card.get("set")),
                _clean_optional(card.get("collector_number")),
                "en",
                _clean_optional(card.get("rarity")),
                _clean_optional(card.get("flavor_text")),
                _clean_optional(card.get("artist")),
                _clean_optional(card.get("released_at")),
                _extract_image_uri(card),
                _encode_string_list(_extract_string_list(card, "games")),
            )
        )

        for alias in sorted(_extract_aliases(card)):
            aliases.append((alias, normalize_text(alias), scryfall_id))

    oracle_cards = list(oracle_cards_by_id.values())
    return oracle_cards, printed_cards, aliases


def _extract_aliases(card: dict) -> set[str]:
    aliases: set[str] = set()

    for key in ("printed_name",):
        value = card.get(key)
        if isinstance(value, str) and value.strip():
            aliases.add(value.strip())

    card_faces = card.get("card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if not isinstance(face, dict):
                continue
            for key in ("name", "printed_name"):
                value = face.get(key)
                if isinstance(value, str) and value.strip():
                    aliases.add(value.strip())

    name = str(card.get("name") or "").strip()
    aliases.discard(name)
    return aliases


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE oracle_cards (
            id INTEGER PRIMARY KEY,
            oracle_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            layout TEXT,
            mana_cost TEXT,
            type_line TEXT,
            oracle_text TEXT,
            colors TEXT NOT NULL DEFAULT '[]',
            color_identity TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE printed_cards (
            id INTEGER PRIMARY KEY,
            scryfall_id TEXT NOT NULL UNIQUE,
            oracle_id TEXT NOT NULL,
            printed_name TEXT,
            set_code TEXT,
            collector_number TEXT,
            language TEXT DEFAULT 'en',
            rarity TEXT,
            flavor_text TEXT,
            artist TEXT,
            released_at TEXT,
            image_uri TEXT,
            games TEXT NOT NULL DEFAULT '[]',
            FOREIGN KEY(oracle_id) REFERENCES oracle_cards(oracle_id) ON DELETE CASCADE
        );

        CREATE TABLE aliases (
            id INTEGER PRIMARY KEY,
            card_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            FOREIGN KEY(card_id) REFERENCES printed_cards(id) ON DELETE CASCADE
        );

        CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX idx_oracle_cards_normalized_name ON oracle_cards(normalized_name);
        CREATE INDEX idx_oracle_cards_layout ON oracle_cards(layout);
        CREATE INDEX idx_printed_cards_oracle_id ON printed_cards(oracle_id);
        CREATE INDEX idx_printed_cards_set_code ON printed_cards(set_code);
        CREATE INDEX idx_aliases_normalized_alias ON aliases(normalized_alias);

        CREATE VIEW cards AS
        SELECT
            printed_cards.id AS id,
            printed_cards.scryfall_id AS scryfall_id,
            printed_cards.oracle_id AS oracle_id,
            oracle_cards.name AS name,
            oracle_cards.normalized_name AS normalized_name,
            printed_cards.set_code AS set_code,
            printed_cards.collector_number AS collector_number,
            printed_cards.language AS language,
            oracle_cards.layout AS layout,
            oracle_cards.mana_cost AS mana_cost,
            oracle_cards.type_line AS type_line,
            oracle_cards.oracle_text AS oracle_text,
            printed_cards.rarity AS rarity,
            printed_cards.flavor_text AS flavor_text,
            printed_cards.artist AS artist,
            printed_cards.released_at AS released_at,
            printed_cards.image_uri AS image_uri,
            printed_cards.games AS games,
            oracle_cards.colors AS colors,
            oracle_cards.color_identity AS color_identity
        FROM printed_cards
        INNER JOIN oracle_cards ON oracle_cards.oracle_id = printed_cards.oracle_id;
        """
    )


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_image_uri(card: dict) -> str | None:
    image_uris = card.get("image_uris")
    if isinstance(image_uris, dict):
        for key in ("png", "large", "normal"):
            if image_uris.get(key):
                return _clean_optional(image_uris.get(key))

    card_faces = card.get("card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if not isinstance(face, dict):
                continue
            face_uris = face.get("image_uris")
            if not isinstance(face_uris, dict):
                continue
            for key in ("png", "large", "normal"):
                if face_uris.get(key):
                    return _clean_optional(face_uris.get(key))

    return None


def _derive_oracle_id(card: dict[str, Any], scryfall_id: str) -> str:
    oracle_id = _clean_optional(card.get("oracle_id"))
    return oracle_id or f"printing:{scryfall_id}"


def _is_paper_printing(card: dict[str, Any]) -> bool:
    extracted_games = _extract_string_list(card, "games")
    games = {game.casefold() for game in extracted_games}
    if "paper" in games:
        return True
    if extracted_games:
        return False
    if card.get("digital"):
        return False
    return True


def _extract_string_list(card: dict[str, Any], key: str) -> list[str]:
    value = card.get(key)
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    card_faces = card.get("card_faces")
    if not isinstance(card_faces, list):
        return []

    collected: list[str] = []
    for face in card_faces:
        if not isinstance(face, dict):
            continue
        face_value = face.get(key)
        if isinstance(face_value, list):
            for item in face_value:
                text = str(item).strip()
                if text and text not in collected:
                    collected.append(text)
    return collected


def _extract_joined_face_text(card: dict[str, Any], key: str) -> str | None:
    direct = _clean_optional(card.get(key))
    if direct:
        return direct

    card_faces = card.get("card_faces")
    if not isinstance(card_faces, list):
        return None

    parts: list[str] = []
    for face in card_faces:
        if not isinstance(face, dict):
            continue
        value = _clean_optional(face.get(key))
        if value:
            parts.append(value)
    if not parts:
        return None
    return " // ".join(parts)


def _encode_string_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=True)
