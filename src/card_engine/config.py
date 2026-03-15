from dataclasses import dataclass, field


@dataclass
class EngineConfig:
    catalog_path: str = "data/catalog/cards.sqlite3"
    debug_enabled: bool = False
    candidate_count: int = 5
    detection_min_area_ratio: float = 0.2
    max_image_edge: int = 1600
    enabled_roi_groups: list[str] = field(default_factory=lambda: ["standard"])
    roi_cycle_order: list[str] = field(default_factory=lambda: ["standard"])
    layout_heuristics_enabled: bool = True
