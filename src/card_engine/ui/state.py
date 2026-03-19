from dataclasses import dataclass, field
from pathlib import Path

from card_engine.models import RecognitionResult
from card_engine.utils.geometry import Quad
from card_engine.utils.image_io import LoadedImage

RelativeROI = tuple[float, float, float, float]


@dataclass
class UIState:
    fixture_index: int = 0
    active_roi: str = "standard"
    show_bbox: bool = True
    fixture_paths: list[Path] = field(default_factory=list)
    status_message: str = "Ready."
    current_image: LoadedImage | None = None
    recognition_result: RecognitionResult | None = None
    recognition_error: str | None = None
    preview_message: str = "Preview unavailable."
    manual_quads: dict[Path, Quad] = field(default_factory=dict)
    manual_roi_overrides: dict[str, dict[str, RelativeROI]] = field(default_factory=dict)


def cycle_fixture_index(current_index: int, delta: int, fixture_count: int) -> int:
    if fixture_count <= 0:
        return 0
    return (current_index + delta) % fixture_count


def cycle_active_roi(current_roi: str, available_rois: list[str]) -> str:
    if not available_rois:
        return current_roi

    try:
        current_index = available_rois.index(current_roi)
    except ValueError:
        return available_rois[0]

    return available_rois[(current_index + 1) % len(available_rois)]
