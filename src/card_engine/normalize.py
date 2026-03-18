from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .roi import ROI_PRESETS

CANONICAL_CARD_SIZE = (880, 630)  # height, width


@dataclass(frozen=True)
class CropRegion:
    label: str
    bbox: tuple[int, int, int, int]
    shape: tuple[int, int, int]


@dataclass(frozen=True)
class NormalizedCardImage:
    shape: tuple[int, int, int]
    source_bbox: tuple[int, int, int, int] | None
    source_shape: tuple[int, int, int] | None
    path: str | None = None


@dataclass
class NormalizationResult:
    normalized_image: Any
    crops: dict[str, CropRegion]


def normalize_card(image: Any, bbox: tuple[int, int, int, int] | None) -> NormalizationResult:
    """Normalize the detected region into a canonical card-sized descriptor."""
    if bbox is None:
        return NormalizationResult(normalized_image=image, crops={})

    source_shape = getattr(image, "shape", None)
    normalized_image = NormalizedCardImage(
        shape=(CANONICAL_CARD_SIZE[0], CANONICAL_CARD_SIZE[1], 3),
        source_bbox=bbox,
        source_shape=source_shape,
        path=str(getattr(image, "path", "")) or None,
    )

    crops = _build_roi_crops(normalized_image.shape)
    return NormalizationResult(normalized_image=normalized_image, crops=crops)


def _build_roi_crops(normalized_shape: tuple[int, int, int]) -> dict[str, CropRegion]:
    height, width, _ = normalized_shape
    crops: dict[str, CropRegion] = {}

    for group_name, rois in ROI_PRESETS.items():
        for roi in rois:
            crop_width = max(1, int(round(width * roi.w)))
            crop_height = max(1, int(round(height * roi.h)))
            crop_left = max(0, int(round(width * roi.x)))
            crop_top = max(0, int(round(height * roi.y)))
            crops[f"{group_name}:{roi.label}"] = CropRegion(
                label=roi.label,
                bbox=(crop_left, crop_top, crop_width, crop_height),
                shape=(crop_height, crop_width, 3),
            )

    return crops
