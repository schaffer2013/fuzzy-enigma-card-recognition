from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .catalog.local_index import CatalogRecord, LocalCatalogIndex

RecognitionMode = Literal["default", "greenfield", "reevaluation", "small_pool", "confirmation"]
VALID_RECOGNITION_MODES: tuple[RecognitionMode, ...] = (
    "default",
    "greenfield",
    "reevaluation",
    "small_pool",
    "confirmation",
)


@dataclass(frozen=True)
class ExpectedCard:
    name: str
    set_code: str | None = None
    collector_number: str | None = None


@dataclass(frozen=True)
class CandidatePool:
    records: tuple[CatalogRecord, ...]

    @classmethod
    def from_records(cls, records: list[CatalogRecord]) -> "CandidatePool":
        return cls(tuple(records))

    @classmethod
    def from_catalog(cls, catalog: LocalCatalogIndex) -> "CandidatePool":
        return cls(tuple(catalog.records))

    def to_catalog(self) -> LocalCatalogIndex:
        return LocalCatalogIndex.from_records(list(self.records))


@dataclass(frozen=True)
class ResolvedOperationalMode:
    requested_mode: RecognitionMode
    effective_mode: RecognitionMode
    catalog: LocalCatalogIndex
    skip_secondary_ocr: bool
    implementation_note: str | None = None


def resolve_operational_mode(
    full_catalog: LocalCatalogIndex,
    *,
    mode: str | None = None,
    candidate_pool: CandidatePool | LocalCatalogIndex | None = None,
    expected_card: ExpectedCard | None = None,
) -> ResolvedOperationalMode:
    resolved_mode = normalize_recognition_mode(mode)

    if resolved_mode in {"default", "greenfield"}:
        return ResolvedOperationalMode(
            requested_mode=resolved_mode,
            effective_mode=resolved_mode,
            catalog=full_catalog,
            skip_secondary_ocr=False,
        )

    if resolved_mode == "small_pool":
        constrained_catalog = _resolve_constrained_catalog(
            full_catalog,
            candidate_pool=candidate_pool,
            expected_card=expected_card,
        )
        return ResolvedOperationalMode(
            requested_mode=resolved_mode,
            effective_mode=resolved_mode,
            catalog=constrained_catalog,
            skip_secondary_ocr=True,
        )

    if expected_card is None:
        raise ValueError(f"Mode '{resolved_mode}' requires an expected_card.")

    if resolved_mode == "reevaluation":
        return ResolvedOperationalMode(
            requested_mode=resolved_mode,
            effective_mode="greenfield",
            catalog=full_catalog,
            skip_secondary_ocr=False,
            implementation_note="Uses the greenfield path until expectation-aware reranking lands.",
        )

    constrained_catalog = _resolve_constrained_catalog(
        full_catalog,
        candidate_pool=candidate_pool,
        expected_card=expected_card,
    )
    return ResolvedOperationalMode(
        requested_mode=resolved_mode,
        effective_mode="small_pool",
        catalog=constrained_catalog,
        skip_secondary_ocr=True,
        implementation_note="Uses the small-pool path until a dedicated confirmation scorer lands.",
    )


def normalize_recognition_mode(mode: str | None) -> RecognitionMode:
    if mode is None:
        return "default"
    normalized = str(mode).strip().lower()
    if normalized not in VALID_RECOGNITION_MODES:
        raise ValueError(f"Unknown recognition mode: {mode}")
    return normalized  # type: ignore[return-value]


def expected_card_from_values(
    *,
    name: str | None,
    set_code: str | None = None,
    collector_number: str | None = None,
) -> ExpectedCard | None:
    if not name:
        return None
    return ExpectedCard(
        name=name,
        set_code=set_code,
        collector_number=collector_number,
    )


def _resolve_constrained_catalog(
    full_catalog: LocalCatalogIndex,
    *,
    candidate_pool: CandidatePool | LocalCatalogIndex | None,
    expected_card: ExpectedCard | None,
) -> LocalCatalogIndex:
    if isinstance(candidate_pool, LocalCatalogIndex):
        return candidate_pool
    if isinstance(candidate_pool, CandidatePool):
        return candidate_pool.to_catalog()
    if expected_card is None or not expected_card.name:
        raise ValueError("Constrained modes require candidate_pool or expected_card.")

    same_name_records = full_catalog.exact_lookup(expected_card.name)
    if not same_name_records:
        raise ValueError(f"No catalog records found for expected card: {expected_card.name}")
    return LocalCatalogIndex.from_records(
        [
            CatalogRecord(
                name=record.name,
                normalized_name=record.normalized_name,
                set_code=record.set_code,
                collector_number=record.collector_number,
                layout=record.layout,
                type_line=record.type_line,
                oracle_text=record.oracle_text,
                flavor_text=record.flavor_text,
                image_uri=record.image_uri,
                aliases=list(record.aliases or []),
            )
            for record in same_name_records
        ]
    )
