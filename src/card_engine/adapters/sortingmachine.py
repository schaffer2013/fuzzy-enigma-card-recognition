from dataclasses import dataclass
from typing import Any

from card_engine.config import EngineConfig
from card_engine.operational_modes import ExpectedCard
from card_engine.session import RecognitionSession, TrackedPoolEntry


@dataclass
class SortingMachineOutput:
    card_name: str | None
    confidence: float


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
        track_result: bool | None = None,
    ) -> SortingMachineOutput:
        result = self.session.recognize(
            frame,
            mode=mode,
            expected_card=expected_card,
            use_tracked_pool=use_tracked_pool,
            track_result=track_result,
        )
        return SortingMachineOutput(card_name=result.best_name, confidence=result.confidence)

    def add_expected_card(self, expected_card: ExpectedCard) -> bool:
        return self.session.add_expected_card(expected_card)

    def get_tracked_pool_entries(self) -> list[TrackedPoolEntry]:
        return self.session.get_tracked_pool_entries()

    def clear_tracked_pool(self) -> None:
        self.session.clear_tracked_pool()
