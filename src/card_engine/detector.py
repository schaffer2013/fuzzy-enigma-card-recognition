from dataclasses import dataclass
from typing import Any


@dataclass
class DetectionResult:
    bbox: tuple[int, int, int, int] | None
    score: float
    debug: dict[str, Any]


def detect_card(image: Any) -> DetectionResult:
    """Placeholder detector.

    Returns a full-frame bbox when shape metadata is available.
    """
    height = getattr(image, "shape", [0, 0])[0] if image is not None else 0
    width = getattr(image, "shape", [0, 0])[1] if image is not None else 0

    if width > 0 and height > 0:
        return DetectionResult(bbox=(0, 0, width, height), score=0.1, debug={"method": "placeholder_full_frame"})

    return DetectionResult(bbox=None, score=0.0, debug={"method": "placeholder_none"})
