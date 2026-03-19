from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from card_engine.utils.text_normalize import normalize_text

CATALOG_SCHEMA_VERSION = "2"


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

    cards, aliases = _load_catalog_rows(source)

    temp_path = database.with_suffix(f"{database.suffix}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    conn = sqlite3.connect(temp_path)
    try:
        _create_schema(conn)
        conn.executemany(
            """
            INSERT INTO cards (
                scryfall_id,
                oracle_id,
                name,
                normalized_name,
                set_code,
                collector_number,
                language,
                layout,
                type_line,
                oracle_text,
                flavor_text
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            cards,
        )
        conn.executemany(
            """
            INSERT INTO aliases (
                card_id,
                alias,
                normalized_alias
            )
            SELECT id, ?, ?
            FROM cards
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
                ('alias_count', ?),
                ('schema_version', ?)
            """,
            (str(source), str(len(cards)), str(len(aliases)), CATALOG_SCHEMA_VERSION),
        )
        conn.commit()
    finally:
        conn.close()

    temp_path.replace(database)
    return CatalogBuildStats(
        card_count=len(cards),
        alias_count=len(aliases),
        source_path=source,
        database_path=database,
    )


def _load_catalog_rows(source_path: Path) -> tuple[list[tuple[str, str | None, str, str, str | None, str | None, str, str | None, str | None, str | None, str | None]], list[tuple[str, str, str]]]:
    raw_cards = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(raw_cards, list):
        raise ValueError("Catalog source JSON must contain a top-level list")

    cards: list[tuple[str, str | None, str, str, str | None, str | None, str, str | None, str | None, str | None, str | None]] = []
    aliases: list[tuple[str, str, str]] = []

    for card in raw_cards:
        if not isinstance(card, dict):
            continue
        if card.get("lang") != "en":
            continue
        if card.get("digital"):
            continue

        scryfall_id = str(card.get("id") or "").strip()
        name = str(card.get("name") or "").strip()
        if not scryfall_id or not name:
            continue

        normalized_name = normalize_text(name)
        cards.append(
            (
                scryfall_id,
                _clean_optional(card.get("oracle_id")),
                name,
                normalized_name,
                _clean_optional(card.get("set")),
                _clean_optional(card.get("collector_number")),
                "en",
                _clean_optional(card.get("layout")),
                _clean_optional(card.get("type_line")),
                _clean_optional(card.get("oracle_text")),
                _clean_optional(card.get("flavor_text")),
            )
        )

        for alias in sorted(_extract_aliases(card)):
            aliases.append((alias, normalize_text(alias), scryfall_id))

    return cards, aliases


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
        CREATE TABLE cards (
            id INTEGER PRIMARY KEY,
            scryfall_id TEXT NOT NULL UNIQUE,
            oracle_id TEXT,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            set_code TEXT,
            collector_number TEXT,
            language TEXT DEFAULT 'en',
            layout TEXT,
            type_line TEXT,
            oracle_text TEXT,
            flavor_text TEXT
        );

        CREATE TABLE aliases (
            id INTEGER PRIMARY KEY,
            card_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT NOT NULL,
            FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE
        );

        CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX idx_cards_normalized_name ON cards(normalized_name);
        CREATE INDEX idx_cards_layout ON cards(layout);
        CREATE INDEX idx_aliases_normalized_alias ON aliases(normalized_alias);
        """
    )


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
