from dataclasses import dataclass, field
from typing import Any


@dataclass
class OCRResult:
    lines: list[str] = field(default_factory=list)
    confidence: float = 0.0
    debug: dict[str, Any] = field(default_factory=dict)


def run_ocr(image: Any, roi_label: str | None = None) -> OCRResult:
    _ = image
    return OCRResult(lines=[], confidence=0.0, debug={"roi_label": roi_label, "method": "placeholder"})
