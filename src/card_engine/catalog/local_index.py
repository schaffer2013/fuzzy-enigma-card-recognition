import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from card_engine.utils.text_normalize import normalize_text


@dataclass
class CatalogRecord:
    name: str
    normalized_name: str
    scryfall_id: str | None = None
    oracle_id: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    layout: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    flavor_text: str | None = None
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
                set_code=record.set_code,
                collector_number=record.collector_number,
                layout=record.layout,
                type_line=record.type_line.strip() if record.type_line else None,
                oracle_text=record.oracle_text.strip() if record.oracle_text else None,
                flavor_text=record.flavor_text.strip() if record.flavor_text else None,
                image_uri=record.image_uri.strip() if record.image_uri else None,
                aliases=sorted({alias.strip() for alias in (record.aliases or []) if alias and alias.strip()}),
            )
            for record in records
        ]
        self._by_normalized_name: dict[str, list[CatalogRecord]] = {}
        self._by_normalized_alias: dict[str, list[CatalogRecord]] = {}
        for record in self.records:
            self._by_normalized_name.setdefault(record.normalized_name, []).append(record)
            for alias in record.aliases or []:
                normalized_alias = normalize_text(alias)
                self._by_normalized_alias.setdefault(normalized_alias, []).append(record)

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
            image_uri_select = "cards.image_uri" if "image_uri" in columns else "NULL"
            rows = conn.execute(
                f"""
                SELECT
                    cards.name,
                    cards.normalized_name,
                    cards.scryfall_id,
                    cards.oracle_id,
                    cards.set_code,
                    cards.collector_number,
                    cards.layout,
                    {type_line_select},
                    {oracle_text_select},
                    {flavor_text_select},
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
                    cards.set_code,
                    cards.collector_number,
                    cards.layout,
                    {type_line_select},
                    {oracle_text_select},
                    {flavor_text_select},
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
                    set_code=set_code,
                    collector_number=collector_number,
                    layout=layout,
                    type_line=type_line,
                    oracle_text=oracle_text,
                    flavor_text=flavor_text,
                    image_uri=image_uri,
                    aliases=aliases.split("\u001f") if aliases else [],
                )
                for name, normalized_name, scryfall_id, oracle_id, set_code, collector_number, layout, type_line, oracle_text, flavor_text, image_uri, aliases in rows
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

        ranked: list[CatalogMatch] = []
        for record in self.records:
            candidates = [record.normalized_name]
            candidates.extend(normalize_text(alias) for alias in (record.aliases or []))
            usable_candidates = [candidate for candidate in candidates if candidate]
            if not usable_candidates:
                continue
            score = max(_fuzzy_score(normalized_query, candidate) for candidate in usable_candidates)
            if score < 0.55:
                continue
            ranked.append(CatalogMatch(record=record, score=score, match_type="fuzzy"))

        ranked.sort(key=lambda match: (-match.score, match.record.name))
        return ranked[:limit]

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


def _fuzzy_score(query: str, candidate: str) -> float:
    ratio = SequenceMatcher(None, query, candidate).ratio()

    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens) if query_tokens else 0.0

    prefix_bonus = 0.05 if candidate.startswith(query) or query.startswith(candidate) else 0.0
    return min(0.99, (ratio * 0.75) + (overlap * 0.25) + prefix_bonus)
