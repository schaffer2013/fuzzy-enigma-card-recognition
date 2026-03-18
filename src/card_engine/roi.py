from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ROI:
    label: str
    x: float
    y: float
    w: float
    h: float


ROI_PRESETS: dict[str, list[ROI]] = {
    "standard": [ROI("title_band", 0.08, 0.05, 0.84, 0.12)],
    "lower_text": [ROI("lower_text", 0.08, 0.75, 0.84, 0.18)],
    "split_left": [ROI("left_panel_title", 0.05, 0.08, 0.4, 0.12)],
    "split_right": [ROI("right_panel_title", 0.55, 0.08, 0.4, 0.12)],
    "adventure": [ROI("adventure_title", 0.53, 0.64, 0.37, 0.1)],
    "transform_back": [ROI("back_title", 0.08, 0.08, 0.84, 0.12)],
}

DEFAULT_ENABLED_ROI_GROUPS = ["standard", "lower_text"]
DEFAULT_ROI_CYCLE_ORDER = ["standard", "lower_text", "split_left", "split_right", "adventure", "transform_back"]
LAYOUT_TO_ROI_GROUPS: dict[str, list[str]] = {
    "normal": ["standard", "lower_text"],
    "split": ["split_left", "split_right", "lower_text"],
    "adventure": ["standard", "adventure", "lower_text"],
    "transform": ["standard", "transform_back", "lower_text"],
    "modal_dfc": ["standard", "transform_back", "lower_text"],
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
) -> list[tuple[str, tuple[int, int, int, int]]]:
    left, top, width, height = card_bbox
    rois = ROI_PRESETS.get(group_name, [])
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
) -> dict[str, list[tuple[str, tuple[int, int, int, int]]]]:
    return {group_name: roi_group_bboxes(card_bbox, group_name) for group_name in group_names if group_name in ROI_PRESETS}
