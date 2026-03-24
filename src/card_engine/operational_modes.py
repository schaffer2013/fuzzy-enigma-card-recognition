from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .models import Candidate

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


REEVALUATION_PROMOTION_WINDOW = 0.08
REEVALUATION_SUPPORT_PROMOTION_WINDOW = 0.16
CONFIRMATION_MAX_MARGIN_BONUS = 0.12
CONFIRMATION_STRONG_CONTRADICTION_THRESHOLD = 0.05


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
            effective_mode=resolved_mode,
            catalog=full_catalog,
            skip_secondary_ocr=False,
            implementation_note="Biases the expected card while still allowing disagreement recovery.",
        )

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
        implementation_note="Scores agreement with the expected printing and surfaces the strongest contradiction.",
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
                scryfall_id=record.scryfall_id,
                oracle_id=record.oracle_id,
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


def apply_expected_mode_bias(
    candidates: list[Candidate],
    *,
    mode: str,
    expected_card: ExpectedCard | None,
) -> tuple[list[Candidate], dict]:
    if mode != "reevaluation" or expected_card is None or not candidates:
        return candidates, {"used": False, "reason": "not_applicable"}

    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    expected_index = next(
        (index for index, candidate in enumerate(ranked) if _candidate_matches_expected(candidate, expected_card)),
        None,
    )
    if expected_index is None:
        return ranked, {
            "used": False,
            "reason": "expected_not_in_candidates",
            "expected_name": expected_card.name,
        }

    expected_candidate = ranked[expected_index]
    best_candidate = ranked[0]
    gap = round(best_candidate.score - expected_candidate.score, 4)
    support_count = _supporting_signal_count(expected_candidate)

    promoted = False
    if expected_index > 0 and (
        gap <= REEVALUATION_PROMOTION_WINDOW
        or (gap <= REEVALUATION_SUPPORT_PROMOTION_WINDOW and support_count >= 1)
    ):
        promoted_candidate = _with_candidate_score(
            expected_candidate,
            min(1.0, round(best_candidate.score + 0.0001, 4)),
            "expected_card_bias",
        )
        ranked[expected_index] = promoted_candidate
        ranked.sort(key=lambda candidate: candidate.score, reverse=True)
        promoted = True
        expected_candidate = promoted_candidate

    return ranked, {
        "used": True,
        "expected_name": expected_card.name,
        "expected_set_code": expected_card.set_code,
        "expected_collector_number": expected_card.collector_number,
        "expected_rank": next(
            index + 1
            for index, candidate in enumerate(ranked)
            if _candidate_matches_expected(candidate, expected_card)
        ),
        "expected_score": expected_candidate.score,
        "best_candidate_before": _candidate_payload(best_candidate),
        "score_gap_before": gap,
        "support_count": support_count,
        "promoted": promoted,
        "agrees_with_expected": _candidate_matches_expected(ranked[0], expected_card),
    }


def score_confirmation_against_expected(
    candidates: list[Candidate],
    *,
    expected_card: ExpectedCard | None,
) -> tuple[str | None, float, dict]:
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    best_name = ranked[0].name if ranked else (expected_card.name if expected_card else None)
    if expected_card is None:
        return best_name, 0.0, {"used": False, "reason": "missing_expected_card"}

    expected_index = next(
        (index for index, candidate in enumerate(ranked) if _candidate_matches_expected(candidate, expected_card)),
        None,
    )
    if expected_index is None:
        contradiction = ranked[0] if ranked else None
        return best_name, 0.0, {
            "used": True,
            "matches_expected": False,
            "expected_present": False,
            "expected_name": expected_card.name,
            "expected_set_code": expected_card.set_code,
            "expected_collector_number": expected_card.collector_number,
            "strongest_contradiction": _candidate_payload(contradiction) if contradiction else None,
        }

    expected_candidate = ranked[expected_index]
    best_other_score = max(
        (candidate.score for index, candidate in enumerate(ranked) if index != expected_index),
        default=0.0,
    )
    margin = round(expected_candidate.score - best_other_score, 4)
    support_notes = set(expected_candidate.notes or [])
    confidence = expected_candidate.score
    confidence += min(CONFIRMATION_MAX_MARGIN_BONUS, max(0.0, margin) * 0.3)
    if "exact" in support_notes:
        confidence += 0.03
    if "set_symbol_match" in support_notes:
        confidence += 0.05
    if "art_match" in support_notes:
        confidence += 0.05
    if "type_line_match" in support_notes:
        confidence += 0.025
    if "lower_text_match" in support_notes:
        confidence += 0.025
    if expected_index != 0:
        confidence -= 0.2 + min(0.2, abs(margin) * 0.5)
    elif _has_strong_printing_contradiction(ranked, expected_index):
        confidence -= 0.08
    confidence = max(0.0, min(1.0, round(confidence, 4)))

    best_other = next(
        (candidate for index, candidate in enumerate(ranked) if index != expected_index),
        None,
    )
    return best_name, confidence, {
        "used": True,
        "matches_expected": expected_index == 0,
        "expected_present": True,
        "expected_name": expected_card.name,
        "expected_set_code": expected_card.set_code,
        "expected_collector_number": expected_card.collector_number,
        "expected_rank": expected_index + 1,
        "expected_score": expected_candidate.score,
        "best_other_score": best_other_score,
        "score_margin": margin,
        "supporting_signals": sorted(note for note in support_notes if note.endswith("match") or note == "exact"),
        "strongest_contradiction": _candidate_payload(best_other) if best_other else None,
    }


def _candidate_matches_expected(candidate: Candidate, expected_card: ExpectedCard) -> bool:
    if candidate.name != expected_card.name:
        return False
    if expected_card.set_code is not None and (candidate.set_code or "").lower() != expected_card.set_code.lower():
        return False
    if expected_card.collector_number is not None and str(candidate.collector_number or "").lower() != str(expected_card.collector_number).lower():
        return False
    return True


def _supporting_signal_count(candidate: Candidate) -> int:
    notes = set(candidate.notes or [])
    return sum(
        1
        for note in ("set_symbol_match", "art_match", "type_line_match", "lower_text_match")
        if note in notes
    )


def _with_candidate_score(candidate: Candidate, score: float, note: str) -> Candidate:
    notes = list(candidate.notes or [])
    if note not in notes:
        notes.append(note)
    return Candidate(
        name=candidate.name,
        score=score,
        scryfall_id=candidate.scryfall_id,
        oracle_id=candidate.oracle_id,
        set_code=candidate.set_code,
        collector_number=candidate.collector_number,
        notes=notes,
    )


def _candidate_payload(candidate: Candidate | None) -> dict | None:
    if candidate is None:
        return None
    return {
        "name": candidate.name,
        "scryfall_id": candidate.scryfall_id,
        "oracle_id": candidate.oracle_id,
        "set_code": candidate.set_code,
        "collector_number": candidate.collector_number,
        "score": candidate.score,
        "notes": list(candidate.notes or []),
    }


def _has_strong_printing_contradiction(ranked: list[Candidate], expected_index: int) -> bool:
    expected_candidate = ranked[expected_index]
    for index, candidate in enumerate(ranked):
        if index == expected_index:
            continue
        if candidate.name != expected_candidate.name:
            continue
        if _is_distinct_printing(candidate, expected_candidate) and (
            expected_candidate.score - candidate.score
        ) <= CONFIRMATION_STRONG_CONTRADICTION_THRESHOLD:
            return True
    return False


def _is_distinct_printing(left: Candidate, right: Candidate) -> bool:
    return (
        left.set_code != right.set_code
        or left.collector_number != right.collector_number
    )
