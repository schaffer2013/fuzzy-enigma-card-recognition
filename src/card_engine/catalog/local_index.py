import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import json

from card_engine.utils.text_normalize import normalize_text


@dataclass
class CatalogRecord:
    name: str
    normalized_name: str
    scryfall_id: str | None = None
    oracle_id: str | None = None
    mana_cost: str | None = None
    colors: tuple[str, ...] = ()
    color_identity: tuple[str, ...] = ()
    set_code: str | None = None
    collector_number: str | None = None
    rarity: str | None = None
    layout: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    flavor_text: str | None = None
    artist: str | None = None
    released_at: str | None = None
    games: tuple[str, ...] = ()
    image_uri: str | None = None
    aliases: list[str] | None = None


@dataclass(frozen=True)
class CatalogMatch:
    record: CatalogRecord
    score: float
    match_type: str


class LocalCatalogIndex:
    def __init__(self, records: list[CatalogRecord]):
        self.records = [
            CatalogRecord(
                name=record.name,
                normalized_name=normalize_text(record.normalized_name or record.name),
                scryfall_id=record.scryfall_id.strip() if record.scryfall_id else None,
                oracle_id=record.oracle_id.strip() if record.oracle_id else None,
                mana_cost=record.mana_cost.strip() if record.mana_cost else None,
                colors=tuple(record.colors or ()),
                color_identity=tuple(record.color_identity or ()),
                set_code=record.set_code,
                collector_number=record.collector_number,
                rarity=record.rarity.strip() if record.rarity else None,
                layout=record.layout,
                type_line=record.type_line.strip() if record.type_line else None,
                oracle_text=record.oracle_text.strip() if record.oracle_text else None,
                flavor_text=record.flavor_text.strip() if record.flavor_text else None,
                artist=record.artist.strip() if record.artist else None,
                released_at=record.released_at.strip() if record.released_at else None,
                games=tuple(record.games or ()),
                image_uri=record.image_uri.strip() if record.image_uri else None,
                aliases=sorted({alias.strip() for alias in (record.aliases or []) if alias and alias.strip()}),
            )
            for record in records
        ]
        self._by_normalized_name: dict[str, list[CatalogRecord]] = {}
        self._by_normalized_alias: dict[str, list[CatalogRecord]] = {}
        self._by_scryfall_id: dict[str, CatalogRecord] = {}
        self._by_oracle_id: dict[str, list[CatalogRecord]] = {}
        self._records_by_oracle_key: dict[str, list[CatalogRecord]] = {}
        self._oracle_search_records: list[tuple[str, CatalogRecord]] = []
        for record in self.records:
            self._by_normalized_name.setdefault(record.normalized_name, []).append(record)
            if record.scryfall_id:
                self._by_scryfall_id.setdefault(record.scryfall_id.lower(), record)
            if record.oracle_id:
                self._by_oracle_id.setdefault(record.oracle_id.lower(), []).append(record)
            for alias in record.aliases or []:
                normalized_alias = normalize_text(alias)
                self._by_normalized_alias.setdefault(normalized_alias, []).append(record)
            oracle_key = record.oracle_id or f"name:{record.normalized_name}"
            self._records_by_oracle_key.setdefault(oracle_key, []).append(record)
        self._oracle_search_records = self._build_oracle_search_records()

    @classmethod
    def from_records(cls, records: list[CatalogRecord]) -> "LocalCatalogIndex":
        return cls(records)

    @classmethod
    def from_sqlite(cls, db_path: str) -> "LocalCatalogIndex":
        path = Path(db_path)
        if not path.exists():
            return cls([])

        with sqlite3.connect(path) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(cards)").fetchall()
            }
            type_line_select = "cards.type_line" if "type_line" in columns else "NULL"
            oracle_text_select = "cards.oracle_text" if "oracle_text" in columns else "NULL"
            flavor_text_select = "cards.flavor_text" if "flavor_text" in columns else "NULL"
            mana_cost_select = "cards.mana_cost" if "mana_cost" in columns else "NULL"
            colors_select = "cards.colors" if "colors" in columns else "'[]'"
            color_identity_select = "cards.color_identity" if "color_identity" in columns else "'[]'"
            rarity_select = "cards.rarity" if "rarity" in columns else "NULL"
            artist_select = "cards.artist" if "artist" in columns else "NULL"
            released_at_select = "cards.released_at" if "released_at" in columns else "NULL"
            games_select = "cards.games" if "games" in columns else "'[]'"
            image_uri_select = "cards.image_uri" if "image_uri" in columns else "NULL"
            rows = conn.execute(
                f"""
                SELECT
                    cards.name,
                    cards.normalized_name,
                    cards.scryfall_id,
                    cards.oracle_id,
                    {mana_cost_select},
                    {colors_select},
                    {color_identity_select},
                    cards.set_code,
                    cards.collector_number,
                    {rarity_select},
                    cards.layout,
                    {type_line_select},
                    {oracle_text_select},
                    {flavor_text_select},
                    {artist_select},
                    {released_at_select},
                    {games_select},
                    {image_uri_select},
                    GROUP_CONCAT(aliases.alias, '\u001f') AS aliases
                FROM cards
                LEFT JOIN aliases ON aliases.card_id = cards.id
                GROUP BY
                    cards.id,
                    cards.name,
                    cards.normalized_name,
                    cards.scryfall_id,
                    cards.oracle_id,
                    {mana_cost_select},
                    {colors_select},
                    {color_identity_select},
                    cards.set_code,
                    cards.collector_number,
                    {rarity_select},
                    cards.layout,
                    {type_line_select},
                    {oracle_text_select},
                    {flavor_text_select},
                    {artist_select},
                    {released_at_select},
                    {games_select},
                    {image_uri_select}
                """
            ).fetchall()

        return cls.from_records(
            [
                CatalogRecord(
                    name=name,
                    normalized_name=normalized_name,
                    scryfall_id=scryfall_id,
                    oracle_id=oracle_id,
                    mana_cost=mana_cost,
                    colors=_decode_string_list(colors),
                    color_identity=_decode_string_list(color_identity),
                    set_code=set_code,
                    collector_number=collector_number,
                    rarity=rarity,
                    layout=layout,
                    type_line=type_line,
                    oracle_text=oracle_text,
                    flavor_text=flavor_text,
                    artist=artist,
                    released_at=released_at,
                    games=_decode_string_list(games),
                    image_uri=image_uri,
                    aliases=aliases.split("\u001f") if aliases else [],
                )
                for name, normalized_name, scryfall_id, oracle_id, mana_cost, colors, color_identity, set_code, collector_number, rarity, layout, type_line, oracle_text, flavor_text, artist, released_at, games, image_uri, aliases in rows
            ]
        )

    def exact_lookup(self, query: str) -> list[CatalogRecord]:
        normalized_query = normalize_text(query)
        results: list[CatalogRecord] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for group in (
            self._by_normalized_name.get(normalized_query, []),
            self._by_normalized_alias.get(normalized_query, []),
        ):
            for record in group:
                key = (record.name, record.set_code, record.collector_number)
                if key in seen:
                    continue
                seen.add(key)
                results.append(record)
        return results

    def search_name(self, query: str, limit: int = 5) -> list[CatalogMatch]:
        normalized_query = normalize_text(query)
        if not normalized_query:
            return []

        exact_matches = self.exact_lookup(normalized_query)
        if exact_matches:
            return [
                CatalogMatch(record=record, score=1.0, match_type="exact")
                for record in exact_matches
            ]

        ranked: list[tuple[str, CatalogRecord, float]] = []
        for oracle_key, record in self._oracle_search_records:
            candidates = [record.normalized_name]
            candidates.extend(normalize_text(alias) for alias in (record.aliases or []))
            usable_candidates = [candidate for candidate in candidates if candidate]
            if not usable_candidates:
                continue
            score = max(_fuzzy_score(normalized_query, candidate) for candidate in usable_candidates)
            if score < 0.55:
                continue
            ranked.append((oracle_key, record, score))

        ranked.sort(key=lambda entry: (-entry[2], entry[1].name))
        return [
            CatalogMatch(record=record, score=score, match_type="fuzzy")
            for _oracle_key, record, score in ranked[:limit]
        ]

    def find_record(
        self,
        *,
        name: str,
        set_code: str | None = None,
        collector_number: str | None = None,
    ) -> CatalogRecord | None:
        normalized_name = normalize_text(name)
        matches = self._by_normalized_name.get(normalized_name, [])
        if not matches:
            return None

        if set_code is None and collector_number is None:
            return matches[0] if len(matches) == 1 else None

        normalized_set_code = (set_code or "").lower()
        normalized_collector = str(collector_number).lower() if collector_number is not None else ""
        for record in matches:
            if set_code is not None and (record.set_code or "").lower() != normalized_set_code:
                continue
            if collector_number is not None and str(record.collector_number or "").lower() != normalized_collector:
                continue
            return record
        return None

    def find_record_by_scryfall_id(self, scryfall_id: str) -> CatalogRecord | None:
        normalized_id = str(scryfall_id or "").strip().lower()
        if not normalized_id:
            return None
        return self._by_scryfall_id.get(normalized_id)

    def records_for_oracle_id(self, oracle_id: str) -> list[CatalogRecord]:
        normalized_id = str(oracle_id or "").strip().lower()
        if not normalized_id:
            return []
        return list(self._by_oracle_id.get(normalized_id, []))

    def _build_oracle_search_records(self) -> list[tuple[str, CatalogRecord]]:
        search_records: list[tuple[str, CatalogRecord]] = []
        for oracle_key, records in self._records_by_oracle_key.items():
            representative = records[0]
            alias_set = {
                alias.strip()
                for record in records
                for alias in (record.aliases or [])
                if alias and alias.strip()
            }
            search_records.append(
                (
                    oracle_key,
                    CatalogRecord(
                        name=representative.name,
                        normalized_name=representative.normalized_name,
                        scryfall_id=None,
                        oracle_id=representative.oracle_id,
                        mana_cost=representative.mana_cost,
                        colors=representative.colors,
                        color_identity=representative.color_identity,
                        set_code=None,
                        collector_number=None,
                        rarity=None,
                        layout=representative.layout,
                        type_line=representative.type_line,
                        oracle_text=representative.oracle_text,
                        flavor_text=None,
                        artist=None,
                        released_at=None,
                        games=(),
                        image_uri=None,
                        aliases=sorted(alias_set),
                    ),
                )
            )
        return search_records


def _fuzzy_score(query: str, candidate: str) -> float:
    ratio = SequenceMatcher(None, query, candidate).ratio()

    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens) if query_tokens else 0.0

    prefix_bonus = 0.05 if candidate.startswith(query) or query.startswith(candidate) else 0.0
    return min(0.99, (ratio * 0.75) + (overlap * 0.25) + prefix_bonus)


def _decode_string_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    try:
        payload = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(str(item).strip() for item in payload if str(item).strip())
