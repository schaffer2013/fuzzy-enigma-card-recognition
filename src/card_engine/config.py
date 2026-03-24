"""Runtime configuration for the card engine.

Relative paths in this module are resolved against the calling process's
current working directory, not the package directory. For embedded parent
applications, prefer explicit absolute paths.
"""

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

from .roi import DEFAULT_ENABLED_ROI_GROUPS, DEFAULT_ROI_CYCLE_ORDER

DEFAULT_ENGINE_CONFIG_PATH = Path("data") / "config" / "engine.json"


@dataclass
class EngineConfig:
    """Engine settings used by recognition and catalog maintenance.

    Path fields remain working-directory relative by default so standalone repo
    usage stays simple. Parent applications embedding this package should
    usually pass absolute paths instead.
    """

    catalog_path: str = "data/catalog/cards.sqlite3"
    debug_enabled: bool = False
    candidate_count: int = 5
    detection_min_area_ratio: float = 0.2
    max_image_edge: int = 1600
    enabled_roi_groups: list[str] = field(default_factory=lambda: list(DEFAULT_ENABLED_ROI_GROUPS))
    roi_cycle_order: list[str] = field(default_factory=lambda: list(DEFAULT_ROI_CYCLE_ORDER))
    layout_heuristics_enabled: bool = True
    lazy_group_basic_land_printings: bool = False
    lazy_default_printing_by_name: bool = False
    max_visual_tiebreak_candidates: int = 6
    max_visual_tiebreak_seconds_per_card: float = 30.0
    reference_download_timeout_seconds: float = 10.0

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> "EngineConfig":
        config_path = Path(path)
        if not config_path.exists():
            return cls()

        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()

        if not isinstance(payload, dict):
            return cls()

        valid_fields = {field.name for field in fields(cls)}
        kwargs = {key: value for key, value in payload.items() if key in valid_fields}
        return cls(**kwargs)


def load_engine_config(config_path: str | None = None) -> EngineConfig:
    if config_path:
        return EngineConfig.from_file(config_path)

    env_path = os.getenv("CARD_ENGINE_CONFIG_PATH")
    if env_path:
        return EngineConfig.from_file(env_path)

    if DEFAULT_ENGINE_CONFIG_PATH.exists():
        return EngineConfig.from_file(DEFAULT_ENGINE_CONFIG_PATH)

    return EngineConfig()
