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
}


def ordered_roi_groups(enabled_groups: list[str], cycle_order: list[str]) -> list[str]:
    enabled = set(enabled_groups)
    ordered = [group for group in cycle_order if group in enabled]
    remainder = sorted(enabled - set(ordered))
    return ordered + remainder
