from dataclasses import dataclass
from typing import Any

from card_engine.config import EngineConfig
from card_engine.models import Candidate, RecognitionResult
from card_engine.operational_modes import ExpectedCard
from card_engine.session import RecognitionSession, TrackedPoolEntry


@dataclass
class SortingMachineOutput:
    card_name: str | None
    confidence: float


@dataclass
class SortingMachineDetailedOutput(SortingMachineOutput):
    scryfall_id: str | None
    oracle_id: str | None
    bbox: tuple[int, int, int, int] | None
    ocr_lines: list[str]
    top_k_candidates: list[Candidate]
    active_roi: str | None
    tried_rois: list[str]
    debug: dict[str, Any]
    raw_result: RecognitionResult


class SortingMachineRecognizer:
    def __init__(self, config: EngineConfig | None = None, *, auto_track_results: bool = False):
        self.config = config or EngineConfig()
        self.session = RecognitionSession(
            config=self.config,
            auto_track_results=auto_track_results,
        )

    def recognize_top_card(
        self,
        frame: Any,
        *,
        mode: str | None = None,
        expected_card: ExpectedCard | None = None,
        use_tracked_pool: bool | None = None,
        prefer_visual_small_pool: bool = False,
        track_result: bool | None = None,
        detailed: bool = False,
    ) -> SortingMachineOutput | SortingMachineDetailedOutput:
        result = self.session.recognize(
            frame,
            mode=mode,
            expected_card=expected_card,
            use_tracked_pool=use_tracked_pool,
            prefer_visual_small_pool=prefer_visual_small_pool,
            track_result=track_result,
        )
        if not detailed:
            return SortingMachineOutput(card_name=result.best_name, confidence=result.confidence)
        best_candidate = result.top_k_candidates[0] if result.top_k_candidates else None
        return SortingMachineDetailedOutput(
            card_name=result.best_name,
            confidence=result.confidence,
            scryfall_id=best_candidate.scryfall_id if best_candidate else None,
            oracle_id=best_candidate.oracle_id if best_candidate else None,
            bbox=result.bbox,
            ocr_lines=list(result.ocr_lines),
            top_k_candidates=list(result.top_k_candidates),
            active_roi=result.active_roi,
            tried_rois=list(result.tried_rois),
            debug=dict(result.debug),
            raw_result=result,
        )

    def add_expected_card(self, expected_card: ExpectedCard) -> bool:
        return self.session.add_expected_card(expected_card)

    def get_tracked_pool_entries(self) -> list[TrackedPoolEntry]:
        return self.session.get_tracked_pool_entries()

    def clear_tracked_pool(self) -> None:
        self.session.clear_tracked_pool()
