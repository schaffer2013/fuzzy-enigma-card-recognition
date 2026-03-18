from dataclasses import dataclass, field

from .roi import DEFAULT_ENABLED_ROI_GROUPS, DEFAULT_ROI_CYCLE_ORDER


@dataclass
class EngineConfig:
    catalog_path: str = "data/catalog/cards.sqlite3"
    debug_enabled: bool = False
    candidate_count: int = 5
    detection_min_area_ratio: float = 0.2
    max_image_edge: int = 1600
    enabled_roi_groups: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_ROI_GROUPS))
    roi_cycle_order: list[str] = field(default_factory=lambda: list(DEFAULT_ROI_CYCLE_ORDER))
    layout_heuristics_enabled: bool = True
