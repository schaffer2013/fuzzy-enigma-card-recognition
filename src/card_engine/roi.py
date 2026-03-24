from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

RelativeROI = tuple[float, float, float, float]
DEFAULT_HASH_ROI_CONFIG_PATH = Path("data") / "config" / "hash_rois.json"


@dataclass(frozen=True)
class ROI:
    label: str
    x: float
    y: float
    w: float
    h: float


ROI_PRESETS: dict[str, list[ROI]] = {
    "standard": [ROI("title_band", 0.08, 0.05, 0.84, 0.12)],
    "art_match": [ROI("art_box", 0.08, 0.13, 0.84, 0.4)],
    "type_line": [ROI("type_line", 0.08, 0.19, 0.84, 0.08)],
    "set_symbol": [ROI("set_symbol", 0.81, 0.19, 0.1, 0.09)],
    "lower_text": [ROI("lower_text", 0.08, 0.75, 0.84, 0.18)],
    "split_left": [ROI("left_panel_title", 0.05, 0.08, 0.4, 0.12)],
    "split_right": [ROI("right_panel_title", 0.55, 0.08, 0.4, 0.12)],
    "adventure": [ROI("adventure_title", 0.53, 0.64, 0.37, 0.1)],
    "transform_back": [ROI("back_title", 0.08, 0.08, 0.84, 0.12)],
}

DEFAULT_ENABLED_ROI_GROUPS = ["standard", "art_match", "type_line", "set_symbol", "lower_text"]
DEFAULT_ROI_CYCLE_ORDER = ["standard", "art_match", "type_line", "set_symbol", "lower_text", "split_left", "split_right", "adventure", "transform_back"]
LAYOUT_TO_ROI_GROUPS: dict[str, list[str]] = {
    "normal": ["standard", "art_match", "type_line", "set_symbol", "lower_text"],
    "split": ["split_left", "split_right", "art_match", "type_line", "set_symbol", "lower_text"],
    "adventure": ["standard", "art_match", "type_line", "set_symbol", "adventure", "lower_text"],
    "transform": ["standard", "art_match", "type_line", "set_symbol", "transform_back", "lower_text"],
    "modal_dfc": ["standard", "art_match", "type_line", "set_symbol", "transform_back", "lower_text"],
}


def ordered_roi_groups(
    enabled_groups: list[str],
    cycle_order: list[str],
) -> list[str]:
    enabled = [group for group in enabled_groups if group in ROI_PRESETS]
    ordered = [group for group in cycle_order if group in enabled]
    remainder = sorted(set(enabled) - set(ordered))
    return ordered + remainder


def resolve_roi_groups_for_layout(
    layout: str | None,
    *,
    enabled_groups: list[str] | None = None,
    cycle_order: list[str] | None = None,
) -> list[str]:
    cycle = cycle_order or DEFAULT_ROI_CYCLE_ORDER
    base_enabled = enabled_groups or DEFAULT_ENABLED_ROI_GROUPS
    layout_groups = LAYOUT_TO_ROI_GROUPS.get((layout or "normal").lower(), [])
    merged = [*base_enabled, *layout_groups]
    deduped = list(dict.fromkeys(group for group in merged if group in ROI_PRESETS))
    return ordered_roi_groups(deduped, cycle)


def roi_group_bboxes(
    card_bbox: tuple[int, int, int, int],
    group_name: str,
    *,
    overrides: dict[str, RelativeROI] | None = None,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    left, top, width, height = card_bbox
    rois = resolved_group_rois(group_name, overrides=overrides)
    bboxes: list[tuple[str, tuple[int, int, int, int]]] = []
    for roi in rois:
        roi_left = left + int(round(width * roi.x))
        roi_top = top + int(round(height * roi.y))
        roi_width = max(1, int(round(width * roi.w)))
        roi_height = max(1, int(round(height * roi.h)))
        bboxes.append((roi.label, (roi_left, roi_top, roi_width, roi_height)))
    return bboxes


def grouped_roi_bboxes(
    card_bbox: tuple[int, int, int, int],
    group_names: list[str],
    *,
    overrides: dict[str, dict[str, RelativeROI]] | None = None,
) -> dict[str, list[tuple[str, tuple[int, int, int, int]]]]:
    return {
        group_name: roi_group_bboxes(card_bbox, group_name, overrides=(overrides or {}).get(group_name))
        for group_name in group_names
        if group_name in ROI_PRESETS
    }


def resolved_group_rois(
    group_name: str,
    *,
    overrides: dict[str, RelativeROI] | None = None,
) -> list[ROI]:
    base_rois = ROI_PRESETS.get(group_name, [])
    merged: dict[str, ROI] = {roi.label: roi for roi in base_rois}
    for label, values in repo_roi_overrides().get(group_name, {}).items():
        merged[label] = ROI(label, *values)
    for label, values in (overrides or {}).items():
        merged[label] = ROI(label, *values)
    return list(merged.values())


def repo_roi_overrides(config_path: str | Path = DEFAULT_HASH_ROI_CONFIG_PATH) -> dict[str, dict[str, RelativeROI]]:
    config_path = Path(config_path)
    try:
        mtime_ns = config_path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return _repo_roi_overrides_cached(str(config_path), mtime_ns)


def save_repo_roi_overrides(
    overrides: dict[str, dict[str, RelativeROI]],
    config_path: str | Path = DEFAULT_HASH_ROI_CONFIG_PATH,
) -> Path:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        group_name: {
            label: [float(component) for component in values]
            for label, values in sorted(group_value.items())
            if _looks_like_relative_roi(values)
        }
        for group_name, group_value in sorted(overrides.items())
        if isinstance(group_value, dict) and group_value
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _repo_roi_overrides_cached.cache_clear()
    return path


@lru_cache(maxsize=8)
def _repo_roi_overrides_cached(config_path: str, mtime_ns: int) -> dict[str, dict[str, RelativeROI]]:
    path = Path(config_path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}

    loaded: dict[str, dict[str, RelativeROI]] = {}
    for group_name, group_value in payload.items():
        if not isinstance(group_value, dict):
            continue
        entries: dict[str, RelativeROI] = {}
        for label, raw_value in group_value.items():
            if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 4:
                continue
            try:
                entries[str(label)] = tuple(float(component) for component in raw_value)
            except (TypeError, ValueError):
                continue
        if entries:
            loaded[str(group_name)] = entries
    return loaded


def _looks_like_relative_roi(value: object) -> bool:
    return isinstance(value, (list, tuple)) and len(value) == 4


def roi_group_signature(group_name: str) -> str:
    rois = resolved_group_rois(group_name)
    payload = [
        {
            "label": roi.label,
            "x": round(roi.x, 6),
            "y": round(roi.y, 6),
            "w": round(roi.w, 6),
            "h": round(roi.h, 6),
        }
        for roi in rois
    ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
