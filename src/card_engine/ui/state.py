from dataclasses import dataclass


@dataclass
class UIState:
    fixture_index: int = 0
    active_roi: str = "standard"
    show_bbox: bool = True
