from dataclasses import dataclass
from typing import Any

from card_engine.api import recognize_card
from card_engine.config import EngineConfig


@dataclass
class SortingMachineOutput:
    card_name: str | None
    confidence: float


class SortingMachineRecognizer:
    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig()

    def recognize_top_card(self, frame: Any) -> SortingMachineOutput:
        result = recognize_card(frame, config=self.config)
        return SortingMachineOutput(card_name=result.best_name, confidence=result.confidence)
