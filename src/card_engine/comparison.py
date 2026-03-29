from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api import recognize_card
from .adapters.mossmachine import (
    MossMachineCandidate,
    MossMachineRunResult,
    MossMachineSettings,
    run_moss_machine_recognition,
)


@dataclass(frozen=True)
class ComparisonCandidate:
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    confidence: float = 0.0
    distance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComparisonEngineResult:
    engine: str
    available: bool
    best_name: str | None
    confidence: float
    runtime_seconds: float
    failure_code: str | None = None
    candidates: list[ComparisonCandidate] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ParallelRecognitionComparison:
    image_path: str | None
    ours: ComparisonEngineResult | None = None
    moss: ComparisonEngineResult | None = None


def compare_recognition_pipelines(
    image: Any,
    *,
    run_ours: bool = True,
    run_moss: bool = True,
    ours_kwargs: dict[str, Any] | None = None,
    moss_settings: MossMachineSettings | None = None,
) -> ParallelRecognitionComparison:
    image_path = _extract_image_path(image)
    ours_result = None
    moss_result = None

    if run_ours:
        ours_result = _run_our_pipeline(image, ours_kwargs=ours_kwargs or {})
    if run_moss:
        if image_path is None:
            moss_result = ComparisonEngineResult(
                engine="moss_machine",
                available=False,
                best_name=None,
                confidence=0.0,
                runtime_seconds=0.0,
                failure_code="image_path_required",
                notes=["Moss Machine comparison currently requires a real image path on disk."],
            )
        else:
            moss_result = _normalize_moss_result(
                run_moss_machine_recognition(image_path, settings=moss_settings)
            )

    return ParallelRecognitionComparison(
        image_path=str(image_path) if image_path is not None else None,
        ours=ours_result,
        moss=moss_result,
    )


def _run_our_pipeline(image: Any, *, ours_kwargs: dict[str, Any]) -> ComparisonEngineResult:
    result = recognize_card(image, **ours_kwargs)
    stage_timings = dict(result.debug.get("timings") or {})
    runtime_seconds = float(stage_timings.get("total") or 0.0)
    return ComparisonEngineResult(
        engine="fuzzy_enigma",
        available=True,
        best_name=result.best_name,
        confidence=result.confidence,
        runtime_seconds=runtime_seconds,
        failure_code=result.failure_code,
        candidates=[
            ComparisonCandidate(
                name=candidate.name,
                set_code=candidate.set_code,
                collector_number=candidate.collector_number,
                confidence=candidate.score,
                metadata={
                    "scryfall_id": candidate.scryfall_id,
                    "oracle_id": candidate.oracle_id,
                    "notes": list(candidate.notes or []),
                },
            )
            for candidate in result.top_k_candidates
        ],
        debug=dict(result.debug),
        notes=[] if result.review_reason is None else [f"review_reason={result.review_reason}"],
    )


def _normalize_moss_result(result: MossMachineRunResult) -> ComparisonEngineResult:
    return ComparisonEngineResult(
        engine="moss_machine",
        available=result.available,
        best_name=result.best_name,
        confidence=result.confidence,
        runtime_seconds=result.runtime_seconds,
        failure_code=result.failure_code,
        candidates=[_normalize_moss_candidate(candidate) for candidate in result.candidates],
        debug=dict(result.debug),
        notes=list(result.notes),
    )


def _normalize_moss_candidate(candidate: MossMachineCandidate) -> ComparisonCandidate:
    return ComparisonCandidate(
        name=candidate.name,
        set_code=candidate.set_code,
        collector_number=candidate.collector_number,
        confidence=candidate.confidence,
        distance=candidate.distance,
        metadata=dict(candidate.metadata),
    )


def _extract_image_path(image: Any) -> Path | None:
    if isinstance(image, (str, Path)):
        return Path(image)
    path = getattr(image, "path", None)
    if path is None:
        return None
    return Path(path)
