from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .adapters.mossmachine import DEFAULT_MOSS_MACHINE_REPO, MossMachineSettings, run_moss_machine_recognition
from .catalog.local_index import CatalogRecord, LocalCatalogIndex
from .config import EngineConfig
from .models import Candidate, RecognitionResult, VisualPoolCandidate
from .operational_modes import (
    CandidatePool,
    ExpectedCard,
    apply_expected_mode_bias,
    normalize_recognition_mode,
    score_confirmation_against_expected,
)
from .scorer import score_candidates

DEFAULT_BACKEND = "fuzzy_enigma"
MOSS_BACKEND = "moss_machine"
SUPPORTED_BACKENDS = (DEFAULT_BACKEND, MOSS_BACKEND)


def resolve_requested_backend(*, config: EngineConfig | None, backend: str | None = None) -> str:
    configured = backend or os.getenv("CARD_ENGINE_BACKEND") or getattr(config, "recognition_backend", None) or DEFAULT_BACKEND
    normalized = str(configured).strip().lower()
    if normalized in {"ours", "default", "native"}:
        return DEFAULT_BACKEND
    if normalized in {"moss", "moss_machine", "moss-machine"}:
        return MOSS_BACKEND
    return DEFAULT_BACKEND


def choose_effective_backend(
    *,
    requested_backend: str,
    image: Any,
    mode: str | None,
    candidate_pool: Any,
    visual_pool_candidates: list[VisualPoolCandidate] | None,
    expected_card: ExpectedCard | None,
    skip_secondary_ocr: bool,
    catalog: Any,
    config: EngineConfig | None,
) -> tuple[str, str | None]:
    if requested_backend != MOSS_BACKEND:
        return DEFAULT_BACKEND, None

    unsupported_reason = moss_unsupported_reason(
        image=image,
        mode=mode,
        candidate_pool=candidate_pool,
        visual_pool_candidates=visual_pool_candidates,
        expected_card=expected_card,
        skip_secondary_ocr=skip_secondary_ocr,
        catalog=catalog,
    )
    if unsupported_reason is None:
        return MOSS_BACKEND, None

    if config is not None and not getattr(config, "recognition_backend_fallback", True):
        return MOSS_BACKEND, unsupported_reason

    return DEFAULT_BACKEND, unsupported_reason


def run_moss_backend(
    image: Any,
    *,
    mode: str | None,
    candidate_pool: CandidatePool | LocalCatalogIndex | None = None,
    expected_card: ExpectedCard | None = None,
    unsupported_reason: str | None = None,
    progress_callback=None,
    config: EngineConfig,
) -> RecognitionResult:
    image_path = _extract_image_path(image)
    requested_mode = normalize_recognition_mode(mode)
    if unsupported_reason is not None:
        return _moss_failure_result(
            requested_mode=requested_mode,
            failure_code=unsupported_reason,
            note=f"Moss backend cannot satisfy this request: {unsupported_reason}.",
        )
    if image_path is None:
        return _moss_failure_result(
            requested_mode=requested_mode,
            failure_code="image_path_required",
            note="Moss backend requires an on-disk image path.",
        )

    if progress_callback is not None:
        progress_callback("Running Moss Machine backend...")

    settings = MossMachineSettings(
        repo_path=Path(config.moss_repo_path) if config.moss_repo_path else DEFAULT_MOSS_MACHINE_REPO,
        db_path=Path(config.moss_db_path) if config.moss_db_path else None,
        threshold=float(config.moss_threshold),
        top_n=_resolve_moss_top_n(config, candidate_pool=candidate_pool, expected_card=expected_card),
        cache_enabled=bool(config.moss_cache_enabled),
        active_games=tuple(config.moss_active_games or ()),
        keep_staged_assets=bool(getattr(config, "moss_keep_staged_assets", False)),
    )
    moss_result = run_moss_machine_recognition(image_path, settings=settings)

    candidate_records = _candidate_records(candidate_pool)
    candidates = [
        _candidate_from_moss_candidate(candidate, candidate_records=candidate_records, expected_card=expected_card)
        for candidate in moss_result.candidates
    ]
    if requested_mode == "small_pool":
        candidates = _filter_moss_small_pool_candidates(
            candidates,
            candidate_records=candidate_records,
            expected_card=expected_card,
        )
    expectation_debug = {"used": False, "reason": "not_applicable"}
    confirmation_debug = {"used": False, "reason": "not_applicable"}
    if requested_mode == "reevaluation":
        candidates, expectation_debug = apply_expected_mode_bias(
            candidates,
            mode=requested_mode,
            expected_card=expected_card,
        )
    if requested_mode == "confirmation":
        best_name, confidence, confirmation_debug = score_confirmation_against_expected(
            candidates,
            expected_card=expected_card,
        )
    else:
        best_name, confidence = score_candidates(candidates)
        if requested_mode in {"default", "greenfield", "small_pool"} and candidates:
            best_name = candidates[0].name
            confidence = candidates[0].score

    failure_code = moss_result.failure_code
    if moss_result.failure_code is None and not candidates:
        failure_code = "candidate_pool_miss" if requested_mode == "small_pool" else "no_matches"
    review_reason = moss_result.failure_code
    if requested_mode == "confirmation" and confirmation_debug.get("matches_expected") is False:
        review_reason = "expected_card_contradicted"
    elif failure_code == "no_matches":
        review_reason = "ocr_weak"
    elif failure_code is not None:
        review_reason = failure_code

    moss_debug = dict(moss_result.debug)
    moss_timings = dict(moss_debug.get("timings") or {})
    wall_total = float(moss_timings.get("wall_total") or moss_result.runtime_seconds)
    debug = {
        "backend": {
            "requested": MOSS_BACKEND,
            "effective": MOSS_BACKEND,
        },
        "mode": {
            "requested": requested_mode,
            "effective": requested_mode,
        },
        "moss_machine": moss_debug,
        "expectation": expectation_debug,
        "confirmation": confirmation_debug,
        "timings": {
            "total": wall_total,
            "moss_machine": wall_total,
        },
    }
    if moss_result.notes:
        debug["moss_machine"]["notes"] = list(moss_result.notes)

    return RecognitionResult(
        bbox=_extract_card_bbox(image),
        best_name=best_name,
        confidence=confidence,
        ocr_lines=[],
        top_k_candidates=candidates,
        active_roi="moss_machine",
        tried_rois=["moss_machine"],
        requested_mode=requested_mode,
        effective_mode=requested_mode,
        mode_flags={
            "has_expected_card": expected_card is not None,
            "has_candidate_pool": candidate_pool is not None,
            "used_tracked_pool": False,
            "used_visual_small_pool": False,
        },
        pipeline_summary={
            "resolution_path": "moss_machine",
            "active_title_roi": "moss_machine",
            "title_rois_with_text": [],
            "secondary_rois_with_text": [],
            "used_secondary_ocr": False,
            "used_set_symbol_compare": False,
            "used_art_match_compare": False,
            "used_expected_bias": expectation_debug.get("used") is True,
            "used_confirmation_scoring": confirmation_debug.get("used") is True,
            "used_visual_small_pool": False,
            "used_split_full_fallback": False,
            "branches_fired": ["moss_machine"],
        },
        failure_code=failure_code,
        review_reason=review_reason,
        debug=debug,
    )


def moss_unsupported_reason(
    *,
    image: Any,
    mode: str | None,
    candidate_pool: Any,
    visual_pool_candidates: list[VisualPoolCandidate] | None,
    expected_card: ExpectedCard | None,
    skip_secondary_ocr: bool,
    catalog: Any,
) -> str | None:
    if _extract_image_path(image) is None:
        return "image_path_required"
    if visual_pool_candidates:
        return "moss_backend_visual_pool_unsupported"
    if catalog is not None:
        return "moss_backend_injected_catalog_unsupported"
    requested_mode = normalize_recognition_mode(mode)
    if requested_mode in {"reevaluation", "confirmation"} and expected_card is None:
        return "missing_expected_card"
    if requested_mode == "small_pool" and candidate_pool is None and expected_card is None:
        return "missing_candidate_pool_or_expected_card"
    return None


def _moss_failure_result(*, requested_mode: str, failure_code: str, note: str) -> RecognitionResult:
    return RecognitionResult(
        bbox=None,
        best_name=None,
        confidence=0.0,
        ocr_lines=[],
        top_k_candidates=[],
        active_roi="moss_machine",
        tried_rois=["moss_machine"],
        requested_mode=requested_mode,
        effective_mode=requested_mode,
        mode_flags={
            "has_expected_card": False,
            "has_candidate_pool": False,
            "used_tracked_pool": False,
            "used_visual_small_pool": False,
        },
        pipeline_summary={
            "resolution_path": "moss_machine_failed",
            "active_title_roi": "moss_machine",
            "title_rois_with_text": [],
            "secondary_rois_with_text": [],
            "used_secondary_ocr": False,
            "used_set_symbol_compare": False,
            "used_art_match_compare": False,
            "used_expected_bias": False,
            "used_confirmation_scoring": False,
            "used_visual_small_pool": False,
            "used_split_full_fallback": False,
            "branches_fired": ["moss_machine"],
        },
        failure_code=failure_code,
        review_reason=failure_code,
        debug={
            "backend": {
                "requested": MOSS_BACKEND,
                "effective": MOSS_BACKEND,
            },
            "mode": {
                "requested": requested_mode,
                "effective": requested_mode,
            },
            "moss_machine": {
                "notes": [note],
            },
            "timings": {
                "total": 0.0,
                "moss_machine": 0.0,
            },
        },
    )


def _extract_image_path(image: Any) -> Path | None:
    if isinstance(image, (str, Path)):
        return Path(image)
    path = getattr(image, "path", None)
    if path is None:
        return None
    return Path(path)


def _extract_card_bbox(image: Any) -> tuple[int, int, int, int] | None:
    bbox = getattr(image, "card_bbox", None)
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            return tuple(int(value) for value in bbox)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    return None


def _resolve_moss_top_n(
    config: EngineConfig,
    *,
    candidate_pool: CandidatePool | LocalCatalogIndex | None,
    expected_card: ExpectedCard | None,
) -> int:
    configured = max(1, int(config.moss_top_n))
    records = _candidate_records(candidate_pool)
    if records:
        return max(configured, min(100, len(records) * 3))
    if expected_card is not None:
        return max(configured, 20)
    return configured


def _candidate_records(candidate_pool: CandidatePool | LocalCatalogIndex | None) -> list[CatalogRecord]:
    if isinstance(candidate_pool, CandidatePool):
        return list(candidate_pool.records)
    if isinstance(candidate_pool, LocalCatalogIndex):
        return list(candidate_pool.records)
    return []


def _candidate_from_moss_candidate(
    candidate: Any,
    *,
    candidate_records: list[CatalogRecord],
    expected_card: ExpectedCard | None,
) -> Candidate:
    set_code = _normalize_set_code(getattr(candidate, "set_code", None))
    collector_number = _normalize_collector_number(getattr(candidate, "collector_number", None))
    name = str(getattr(candidate, "name", "") or "")
    matched_record = _find_matching_record(
        name=name,
        set_code=set_code,
        collector_number=collector_number,
        candidate_records=candidate_records,
        expected_card=expected_card,
    )
    expected_identity_match = expected_card is not None and _moss_identity_matches_expected(
        name=name,
        set_code=set_code,
        collector_number=collector_number,
        expected_card=expected_card,
    )
    return Candidate(
        name=matched_record.name if matched_record is not None else (expected_card.name if expected_identity_match and expected_card.name else name),
        score=float(getattr(candidate, "confidence", 0.0) or 0.0),
        scryfall_id=matched_record.scryfall_id if matched_record is not None else None,
        oracle_id=matched_record.oracle_id if matched_record is not None else None,
        set_code=matched_record.set_code if matched_record is not None else (_normalize_set_code(expected_card.set_code) if expected_identity_match and expected_card.set_code else set_code),
        collector_number=matched_record.collector_number if matched_record is not None else (expected_card.collector_number if expected_identity_match and expected_card.collector_number else collector_number),
        notes=_build_moss_candidate_notes(getattr(candidate, "distance", None)),
    )


def _filter_moss_small_pool_candidates(
    candidates: list[Candidate],
    *,
    candidate_records: list[CatalogRecord],
    expected_card: ExpectedCard | None,
) -> list[Candidate]:
    if candidate_records:
        filtered = [
            candidate
            for candidate in candidates
            if any(_candidate_matches_record(candidate, record) for record in candidate_records)
        ]
        return filtered
    if expected_card is not None:
        return [
            candidate
            for candidate in candidates
            if _candidate_matches_expected_soft(candidate, expected_card)
        ]
    return candidates


def _find_matching_record(
    *,
    name: str,
    set_code: str | None,
    collector_number: str | None,
    candidate_records: list[CatalogRecord],
    expected_card: ExpectedCard | None,
) -> CatalogRecord | None:
    for record in candidate_records:
        if _record_matches_moss_identity(record, name=name, set_code=set_code, collector_number=collector_number):
            return record
    if expected_card is None:
        return None
    for record in candidate_records:
        if _record_matches_expected(record, expected_card):
            return record
    return None


def _candidate_matches_record(candidate: Candidate, record: CatalogRecord) -> bool:
    return _record_matches_moss_identity(
        record,
        name=candidate.name,
        set_code=_normalize_set_code(candidate.set_code),
        collector_number=_normalize_collector_number(candidate.collector_number),
    )


def _record_matches_moss_identity(
    record: CatalogRecord,
    *,
    name: str,
    set_code: str | None,
    collector_number: str | None,
) -> bool:
    if not _name_matches_moss_name(record.name, name):
        return False
    if set_code is not None and _normalize_set_code(record.set_code) != set_code:
        return False
    if collector_number is not None and _normalize_collector_number(record.collector_number) != collector_number:
        return False
    return True


def _record_matches_expected(record: CatalogRecord, expected_card: ExpectedCard) -> bool:
    if expected_card.scryfall_id and (record.scryfall_id or "").lower() != expected_card.scryfall_id.lower():
        return False
    if expected_card.oracle_id and (record.oracle_id or "").lower() != expected_card.oracle_id.lower():
        return False
    if expected_card.name and not _name_matches_moss_name(record.name, expected_card.name):
        return False
    if expected_card.set_code and _normalize_set_code(record.set_code) != _normalize_set_code(expected_card.set_code):
        return False
    if expected_card.collector_number and _normalize_collector_number(record.collector_number) != _normalize_collector_number(expected_card.collector_number):
        return False
    return True


def _candidate_matches_expected_soft(candidate: Candidate, expected_card: ExpectedCard) -> bool:
    if expected_card.scryfall_id and (candidate.scryfall_id or "").lower() == expected_card.scryfall_id.lower():
        return True
    if expected_card.name and not _name_matches_moss_name(expected_card.name, candidate.name):
        return False
    if expected_card.set_code and _normalize_set_code(candidate.set_code) != _normalize_set_code(expected_card.set_code):
        return False
    if expected_card.collector_number and _normalize_collector_number(candidate.collector_number) != _normalize_collector_number(expected_card.collector_number):
        return False
    return expected_card.name is not None


def _moss_identity_matches_expected(
    *,
    name: str,
    set_code: str | None,
    collector_number: str | None,
    expected_card: ExpectedCard,
) -> bool:
    if expected_card.name and not _name_matches_moss_name(expected_card.name, name):
        return False
    if expected_card.set_code and _normalize_set_code(expected_card.set_code) != set_code:
        return False
    if expected_card.collector_number and _normalize_collector_number(expected_card.collector_number) != collector_number:
        return False
    return expected_card.name is not None


def _name_matches_moss_name(expected_name: str | None, moss_name: str | None) -> bool:
    expected = (expected_name or "").strip().casefold()
    observed = (moss_name or "").strip().casefold()
    if not expected or not observed:
        return False
    if expected == observed:
        return True
    faces = [part.strip() for part in expected.split("//") if part.strip()]
    return observed in faces


def _normalize_set_code(value: Any) -> str | None:
    text = str(value or "").strip()
    return text.lower() or None


def _normalize_collector_number(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _build_moss_candidate_notes(distance: float | None) -> list[str]:
    notes = ["moss_machine"]
    if distance is not None:
        notes.append(f"distance={distance:.4f}")
    return notes
