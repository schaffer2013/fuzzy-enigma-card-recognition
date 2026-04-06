from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .adapters.mossmachine import DEFAULT_MOSS_MACHINE_REPO, MossMachineSettings, run_moss_machine_recognition
from .config import EngineConfig
from .models import Candidate, RecognitionResult, VisualPoolCandidate
from .operational_modes import CandidatePool, ExpectedCard, normalize_recognition_mode

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

    if _moss_supported_for_request(
        image=image,
        mode=mode,
        candidate_pool=candidate_pool,
        visual_pool_candidates=visual_pool_candidates,
        expected_card=expected_card,
        skip_secondary_ocr=skip_secondary_ocr,
        catalog=catalog,
    ):
        return MOSS_BACKEND, None

    if config is not None and not getattr(config, "recognition_backend_fallback", True):
        return MOSS_BACKEND, "forced_backend_unsupported_for_request"

    return DEFAULT_BACKEND, "moss_backend_unsupported_for_request"


def run_moss_backend(
    image: Any,
    *,
    mode: str | None,
    progress_callback=None,
    config: EngineConfig,
) -> RecognitionResult:
    image_path = _extract_image_path(image)
    requested_mode = normalize_recognition_mode(mode)
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
        top_n=int(config.moss_top_n),
        cache_enabled=bool(config.moss_cache_enabled),
        active_games=tuple(config.moss_active_games or ()),
    )
    moss_result = run_moss_machine_recognition(image_path, settings=settings)

    candidates = [
        Candidate(
            name=candidate.name,
            score=candidate.confidence,
            set_code=candidate.set_code,
            collector_number=candidate.collector_number,
            notes=_build_moss_candidate_notes(candidate.distance),
        )
        for candidate in moss_result.candidates
    ]
    review_reason = moss_result.failure_code
    if moss_result.failure_code == "no_matches":
        review_reason = "ocr_weak"

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
        "timings": {
            "total": wall_total,
            "moss_machine": wall_total,
        },
    }
    if moss_result.notes:
        debug["moss_machine"]["notes"] = list(moss_result.notes)

    return RecognitionResult(
        bbox=None,
        best_name=moss_result.best_name,
        confidence=moss_result.confidence,
        ocr_lines=[],
        top_k_candidates=candidates,
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
            "resolution_path": "moss_machine",
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
        failure_code=moss_result.failure_code,
        review_reason=review_reason,
        debug=debug,
    )


def _moss_supported_for_request(
    *,
    image: Any,
    mode: str | None,
    candidate_pool: Any,
    visual_pool_candidates: list[VisualPoolCandidate] | None,
    expected_card: ExpectedCard | None,
    skip_secondary_ocr: bool,
    catalog: Any,
) -> bool:
    if _extract_image_path(image) is None:
        return False
    if candidate_pool is not None or visual_pool_candidates:
        return False
    if expected_card is not None:
        return False
    if skip_secondary_ocr:
        return False
    if catalog is not None:
        return False
    return normalize_recognition_mode(mode) in {"default", "greenfield"}


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


def _build_moss_candidate_notes(distance: float | None) -> list[str]:
    notes = ["moss_machine"]
    if distance is not None:
        notes.append(f"distance={distance:.4f}")
    return notes
