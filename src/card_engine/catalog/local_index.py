import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from card_engine.utils.text_normalize import normalize_text


@dataclass
class CatalogRecord:
    name: str
    normalized_name: str
    set_code: str | None = None
    collector_number: str | None = None
    layout: str | None = None


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
                set_code=record.set_code,
                collector_number=record.collector_number,
                layout=record.layout,
            )
            for record in records
        ]
        self._by_normalized_name: dict[str, list[CatalogRecord]] = {}
        for record in self.records:
            self._by_normalized_name.setdefault(record.normalized_name, []).append(record)

    @classmethod
    def from_records(cls, records: list[CatalogRecord]) -> "LocalCatalogIndex":
        return cls(records)

    @classmethod
    def from_sqlite(cls, db_path: str) -> "LocalCatalogIndex":
        path = Path(db_path)
        if not path.exists():
            return cls([])

        with sqlite3.connect(path) as conn:
            rows = conn.execute(
                """
                SELECT name, normalized_name, set_code, collector_number, layout
                FROM cards
                """
            ).fetchall()

        return cls.from_records(
            [
                CatalogRecord(
                    name=name,
                    normalized_name=normalized_name,
                    set_code=set_code,
                    collector_number=collector_number,
                    layout=layout,
                )
                for name, normalized_name, set_code, collector_number, layout in rows
            ]
        )

    def exact_lookup(self, query: str) -> list[CatalogRecord]:
        normalized_query = normalize_text(query)
        return list(self._by_normalized_name.get(normalized_query, []))

    def search_name(self, query: str, limit: int = 5) -> list[CatalogMatch]:
        normalized_query = normalize_text(query)
        if not normalized_query:
            return []

        exact_matches = self.exact_lookup(normalized_query)
        if exact_matches:
            return [
                CatalogMatch(record=record, score=1.0, match_type="exact")
                for record in exact_matches[:limit]
            ]

        ranked: list[CatalogMatch] = []
        for record in self.records:
            score = _fuzzy_score(normalized_query, record.normalized_name)
            if score < 0.55:
                continue
            ranked.append(CatalogMatch(record=record, score=score, match_type="fuzzy"))

        ranked.sort(key=lambda match: (-match.score, match.record.name))
        return ranked[:limit]


def _fuzzy_score(query: str, candidate: str) -> float:
    ratio = SequenceMatcher(None, query, candidate).ratio()

    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens) if query_tokens else 0.0

    prefix_bonus = 0.05 if candidate.startswith(query) or query.startswith(candidate) else 0.0
    return min(0.99, (ratio * 0.75) + (overlap * 0.25) + prefix_bonus)
