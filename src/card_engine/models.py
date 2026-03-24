from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    name: str
    score: float
    scryfall_id: str | None = None
    oracle_id: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    notes: list[str] | None = None


@dataclass
class RecognitionResult:
    bbox: tuple[int, int, int, int] | None
    best_name: str | None
    confidence: float
    ocr_lines: list[str] = field(default_factory=list)
    top_k_candidates: list[Candidate] = field(default_factory=list)
    active_roi: str | None = None
    tried_rois: list[str] = field(default_factory=list)
    debug: dict[str, Any] = field(default_factory=dict)
