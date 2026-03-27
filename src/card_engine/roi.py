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
    "planar_title": [ROI("plane_title", 0.03, 0.05, 0.12, 0.84)],
    "split_full": [ROI("full_card", 0.0, 0.0, 1.0, 1.0)],
    "standard": [ROI("title_band", 0.08, 0.05, 0.84, 0.12)],
    "art_match": [ROI("art_box", 0.08, 0.13, 0.84, 0.4)],
    "type_line": [ROI("type_line", 0.08, 0.19, 0.84, 0.08)],
    "set_symbol": [ROI("set_symbol", 0.81, 0.19, 0.1, 0.09)],
    "lower_text": [ROI("lower_text", 0.08, 0.75, 0.84, 0.18)],
    "split_left": [ROI("left_panel_title", 0.03, 0.59, 0.12, 0.4)],
    "split_right": [ROI("right_panel_title", 0.03, 0.10, 0.12, 0.4)],
    "adventure": [ROI("adventure_title", 0.53, 0.64, 0.37, 0.1)],
    "transform_back": [ROI("back_title", 0.08, 0.08, 0.84, 0.12)],
}

DEFAULT_ENABLED_ROI_GROUPS = ["standard", "art_match", "type_line", "set_symbol", "lower_text"]
DEFAULT_ROI_CYCLE_ORDER = ["planar_title", "split_full", "standard", "art_match", "type_line", "set_symbol", "lower_text", "adventure", "transform_back", "split_left", "split_right"]
LAYOUT_TO_ROI_GROUPS: dict[str, list[str]] = {
    "normal": ["standard", "art_match", "type_line", "set_symbol", "lower_text"],
    "split": ["planar_title", "split_full", "art_match", "type_line", "set_symbol", "lower_text"],
    "adventure": ["standard", "art_match", "type_line", "set_symbol", "adventure", "lower_text"],
    "transform": ["standard", "art_match", "type_line", "set_symbol", "transform_back", "lower_text"],
    "modal_dfc": ["standard", "art_match", "type_line", "set_symbol", "transform_back", "lower_text"],
    "planar": ["planar_title", "art_match", "lower_text"],
}
OCR_EXPANDABLE_ROI_GROUPS = {
    "planar_title",
    "split_full",
    "standard",
    "type_line",
    "lower_text",
    "split_left",
    "split_right",
    "adventure",
    "transform_back",
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
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> list[tuple[str, tuple[int, int, int, int]]]:
    left, top, width, height = card_bbox
    rois = resolved_group_rois(group_name, overrides=overrides)
    bboxes: list[tuple[str, tuple[int, int, int, int]]] = []
    effective_long_factor, effective_short_factor = roi_group_expand_factors(
        group_name,
        expand_long_factor=expand_long_factor,
        expand_short_factor=expand_short_factor,
    )
    for roi in rois:
        roi_left, roi_top, roi_width, roi_height = scaled_roi_bbox_within_bounds(
            frame_width=width,
            frame_height=height,
            roi=roi,
            expand_long_factor=effective_long_factor,
            expand_short_factor=effective_short_factor,
        )
        roi_left += left
        roi_top += top
        bboxes.append((roi.label, (roi_left, roi_top, roi_width, roi_height)))
    return bboxes


def grouped_roi_bboxes(
    card_bbox: tuple[int, int, int, int],
    group_names: list[str],
    *,
    overrides: dict[str, dict[str, RelativeROI]] | None = None,
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> dict[str, list[tuple[str, tuple[int, int, int, int]]]]:
    return {
        group_name: roi_group_bboxes(
            card_bbox,
            group_name,
            overrides=(overrides or {}).get(group_name),
            expand_long_factor=expand_long_factor,
            expand_short_factor=expand_short_factor,
        )
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


def roi_group_signature(
    group_name: str,
    *,
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> str:
    rois = resolved_group_rois(group_name)
    effective_long_factor, effective_short_factor = roi_group_expand_factors(
        group_name,
        expand_long_factor=expand_long_factor,
        expand_short_factor=expand_short_factor,
    )
    payload = {
        "expand_long_factor": round(float(effective_long_factor), 6),
        "expand_short_factor": round(float(effective_short_factor), 6),
        "rois": [
            {
                "label": roi.label,
                "x": round(roi.x, 6),
                "y": round(roi.y, 6),
                "w": round(roi.w, 6),
                "h": round(roi.h, 6),
            }
            for roi in rois
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def roi_group_expand_factors(
    group_name: str,
    *,
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> tuple[float, float]:
    if group_name not in OCR_EXPANDABLE_ROI_GROUPS:
        return (1.0, 1.0)
    return (expand_long_factor, expand_short_factor)


def scaled_roi_bbox_within_bounds(
    *,
    frame_width: int,
    frame_height: int,
    roi: ROI,
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> tuple[int, int, int, int]:
    base_width = max(1, int(round(frame_width * roi.w)))
    base_height = max(1, int(round(frame_height * roi.h)))
    base_left = max(0, int(round(frame_width * roi.x)))
    base_top = max(0, int(round(frame_height * roi.y)))
    base_right = min(frame_width, base_left + base_width)
    base_bottom = min(frame_height, base_top + base_height)
    base_width = max(1, base_right - base_left)
    base_height = max(1, base_bottom - base_top)

    if base_width >= base_height:
        target_width = base_width * expand_long_factor
        target_height = base_height * expand_short_factor
    else:
        target_width = base_width * expand_short_factor
        target_height = base_height * expand_long_factor

    center_x = base_left + (base_width / 2.0)
    center_y = base_top + (base_height / 2.0)
    left = int(round(center_x - (target_width / 2.0)))
    top = int(round(center_y - (target_height / 2.0)))
    right = int(round(center_x + (target_width / 2.0)))
    bottom = int(round(center_y + (target_height / 2.0)))

    left = max(0, left)
    top = max(0, top)
    right = min(frame_width, right)
    bottom = min(frame_height, bottom)

    width = max(1, right - left)
    height = max(1, bottom - top)
    return (left, top, width, height)
