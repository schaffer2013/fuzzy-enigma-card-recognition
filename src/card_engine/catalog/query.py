from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from card_engine.utils.text_normalize import normalize_text


@dataclass(frozen=True)
class OracleCardRow:
    oracle_id: str
    name: str
    normalized_name: str
    layout: str | None
    mana_cost: str | None
    type_line: str | None
    oracle_text: str | None
    colors: tuple[str, ...]
    color_identity: tuple[str, ...]


@dataclass(frozen=True)
class PrintedCardRow:
    scryfall_id: str
    oracle_id: str
    name: str
    normalized_name: str
    printed_name: str | None
    set_code: str | None
    collector_number: str | None
    language: str
    rarity: str | None
    layout: str | None
    type_line: str | None
    oracle_text: str | None
    flavor_text: str | None
    artist: str | None
    released_at: str | None
    image_uri: str | None
    games: tuple[str, ...]
    colors: tuple[str, ...]
    color_identity: tuple[str, ...]


class OfflineCatalogQuery:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @classmethod
    def from_sqlite(cls, db_path: str | Path) -> "OfflineCatalogQuery":
        return cls(db_path)

    def get_oracle_card(self, oracle_id: str) -> OracleCardRow | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT oracle_id, name, normalized_name, layout, mana_cost, type_line, oracle_text, colors, color_identity
                FROM oracle_cards
                WHERE oracle_id = ?
                """,
                (oracle_id,),
            ).fetchone()
        return _oracle_row(row) if row else None

    def find_oracle_cards(self, name_query: str, *, limit: int = 20) -> list[OracleCardRow]:
        normalized = normalize_text(name_query)
        if not normalized:
            return []
        with self._connect() as conn:
            exact_rows = conn.execute(
                """
                SELECT oracle_id, name, normalized_name, layout, mana_cost, type_line, oracle_text, colors, color_identity
                FROM oracle_cards
                WHERE normalized_name = ?
                ORDER BY name, oracle_id
                LIMIT ?
                """,
                (normalized, limit),
            ).fetchall()
            if exact_rows:
                return [_oracle_row(row) for row in exact_rows]
            fuzzy_rows = conn.execute(
                """
                SELECT oracle_id, name, normalized_name, layout, mana_cost, type_line, oracle_text, colors, color_identity
                FROM oracle_cards
                WHERE normalized_name LIKE ?
                ORDER BY name, oracle_id
                LIMIT ?
                """,
                (f"%{normalized}%", limit),
            ).fetchall()
        return [_oracle_row(row) for row in fuzzy_rows]

    def get_printed_card(self, scryfall_id: str) -> PrintedCardRow | None:
        with self._connect() as conn:
            row = conn.execute(_PRINTED_CARD_SELECT + " WHERE printed_cards.scryfall_id = ?", (scryfall_id,)).fetchone()
        return _printed_row(row) if row else None

    def resolve_card_identity(
        self,
        *,
        name_query: str | None = None,
        oracle_id: str | None = None,
        scryfall_id: str | None = None,
        set_code: str | None = None,
        collector_number: str | None = None,
    ) -> dict[str, object] | None:
        if scryfall_id:
            printed = self.get_printed_card(scryfall_id)
            if printed is None:
                return None
            oracle = self.get_oracle_card(printed.oracle_id)
            return {"oracle": oracle, "printing": printed}

        resolved_oracle_id = oracle_id
        if resolved_oracle_id is None and name_query:
            oracle_rows = self.find_oracle_cards(name_query=name_query, limit=1)
            if not oracle_rows:
                return None
            resolved_oracle_id = oracle_rows[0].oracle_id
        if resolved_oracle_id is None:
            return None

        oracle = self.get_oracle_card(resolved_oracle_id)
        if oracle is None:
            return None
        printings = self.find_printed_cards(
            oracle_id=resolved_oracle_id,
            set_code=set_code,
            collector_number=collector_number,
            limit=50,
        )
        return {"oracle": oracle, "printings": printings}

    def find_printing_candidates(
        self,
        *,
        name_query: str,
        set_code: str | None = None,
        collector_number: str | None = None,
        limit: int = 50,
    ) -> list[PrintedCardRow]:
        return self.find_printed_cards(
            name_query=name_query,
            set_code=set_code,
            collector_number=collector_number,
            limit=limit,
        )

    def printings_for_oracle(self, oracle_id: str, *, limit: int | None = None) -> list[PrintedCardRow]:
        query = _PRINTED_CARD_SELECT + " WHERE printed_cards.oracle_id = ? ORDER BY printed_cards.released_at DESC, printed_cards.set_code, printed_cards.collector_number"
        params: list[object] = [oracle_id]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_printed_row(row) for row in rows]

    def printings_for_name(self, name_query: str, *, limit: int | None = None) -> list[PrintedCardRow]:
        normalized = normalize_text(name_query)
        if not normalized:
            return []
        query = (
            _PRINTED_CARD_SELECT
            + " WHERE cards.normalized_name = ? ORDER BY printed_cards.released_at DESC, printed_cards.set_code, printed_cards.collector_number"
        )
        params: list[object] = [normalized]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_printed_row(row) for row in rows]

    def find_printed_cards(
        self,
        *,
        name_query: str | None = None,
        oracle_id: str | None = None,
        set_code: str | None = None,
        collector_number: str | None = None,
        limit: int = 50,
    ) -> list[PrintedCardRow]:
        clauses: list[str] = []
        params: list[object] = []
        if name_query:
            normalized = normalize_text(name_query)
            if not normalized:
                return []
            clauses.append("cards.normalized_name = ?")
            params.append(normalized)
        if oracle_id:
            clauses.append("printed_cards.oracle_id = ?")
            params.append(oracle_id)
        if set_code:
            clauses.append("LOWER(printed_cards.set_code) = ?")
            params.append(set_code.lower())
        if collector_number:
            clauses.append("LOWER(printed_cards.collector_number) = ?")
            params.append(str(collector_number).lower())

        where_clause = ""
        if clauses:
            where_clause = " WHERE " + " AND ".join(clauses)
        query = (
            _PRINTED_CARD_SELECT
            + where_clause
            + " ORDER BY printed_cards.released_at DESC, printed_cards.set_code, printed_cards.collector_number LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_printed_row(row) for row in rows]

    def count_hashable_printed_cards(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM printed_cards
                WHERE image_uri IS NOT NULL
                  AND TRIM(image_uri) != ''
                """
            ).fetchone()
        return int(row[0]) if row else 0

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


_PRINTED_CARD_SELECT = """
SELECT
    printed_cards.scryfall_id,
    printed_cards.oracle_id,
    cards.name,
    cards.normalized_name,
    printed_cards.printed_name,
    printed_cards.set_code,
    printed_cards.collector_number,
    printed_cards.language,
    printed_cards.rarity,
    cards.layout,
    cards.type_line,
    cards.oracle_text,
    printed_cards.flavor_text,
    printed_cards.artist,
    printed_cards.released_at,
    printed_cards.image_uri,
    printed_cards.games,
    cards.colors,
    cards.color_identity
FROM printed_cards
INNER JOIN cards ON cards.scryfall_id = printed_cards.scryfall_id
"""


def _oracle_row(row: tuple[object, ...]) -> OracleCardRow:
    return OracleCardRow(
        oracle_id=str(row[0]),
        name=str(row[1]),
        normalized_name=str(row[2]),
        layout=_clean_optional(row[3]),
        mana_cost=_clean_optional(row[4]),
        type_line=_clean_optional(row[5]),
        oracle_text=_clean_optional(row[6]),
        colors=_decode_string_list(row[7]),
        color_identity=_decode_string_list(row[8]),
    )


def _printed_row(row: tuple[object, ...]) -> PrintedCardRow:
    return PrintedCardRow(
        scryfall_id=str(row[0]),
        oracle_id=str(row[1]),
        name=str(row[2]),
        normalized_name=str(row[3]),
        printed_name=_clean_optional(row[4]),
        set_code=_clean_optional(row[5]),
        collector_number=_clean_optional(row[6]),
        language=str(row[7] or "en"),
        rarity=_clean_optional(row[8]),
        layout=_clean_optional(row[9]),
        type_line=_clean_optional(row[10]),
        oracle_text=_clean_optional(row[11]),
        flavor_text=_clean_optional(row[12]),
        artist=_clean_optional(row[13]),
        released_at=_clean_optional(row[14]),
        image_uri=_clean_optional(row[15]),
        games=_decode_string_list(row[16]),
        colors=_decode_string_list(row[17]),
        color_identity=_decode_string_list(row[18]),
    )


def _clean_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _decode_string_list(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(item).strip() for item in payload if str(item).strip())
