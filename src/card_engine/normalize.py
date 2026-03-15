from dataclasses import dataclass
from typing import Any


@dataclass
class NormalizationResult:
    normalized_image: Any
    crops: dict[str, Any]


def normalize_card(image: Any, bbox: tuple[int, int, int, int] | None) -> NormalizationResult:
    """Placeholder normalizer that forwards the input image and no crops."""
    _ = bbox
    return NormalizationResult(normalized_image=image, crops={})
