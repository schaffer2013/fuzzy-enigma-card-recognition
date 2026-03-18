from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .roi import ROI_PRESETS
from .utils.geometry import Quad, quad_from_bbox

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
    source_quad: Quad | None
    source_shape: tuple[int, int, int] | None
    destination_quad: Quad | None
    path: str | None = None


@dataclass
class NormalizationResult:
    normalized_image: Any
    crops: dict[str, CropRegion]
    debug_outputs: dict[str, Any]


def normalize_card(
    image: Any,
    bbox: tuple[int, int, int, int] | None,
    *,
    quad: Quad | None = None,
) -> NormalizationResult:
    """Normalize the detected region into a canonical card-sized descriptor."""
    if bbox is None:
        return NormalizationResult(normalized_image=image, crops={}, debug_outputs={})

    source_shape = getattr(image, "shape", None)
    source_quad = quad or getattr(image, "card_quad", None) or quad_from_bbox(bbox)
    rectangular_quad = quad_from_bbox(bbox)
    destination_quad = quad_from_bbox((0, 0, CANONICAL_CARD_SIZE[1], CANONICAL_CARD_SIZE[0]))
    normalized_image = NormalizedCardImage(
        shape=(CANONICAL_CARD_SIZE[0], CANONICAL_CARD_SIZE[1], 3),
        source_bbox=bbox,
        source_quad=source_quad,
        source_shape=source_shape,
        destination_quad=destination_quad,
        path=str(getattr(image, "path", "")) or None,
    )

    crops = _build_roi_crops(normalized_image.shape)
    debug_outputs = {
        "source_bbox": bbox,
        "source_quad": source_quad,
        "destination_quad": destination_quad,
        "warp_method": "quad_to_canonical" if source_quad != rectangular_quad else "bbox_to_canonical",
        "roi_bboxes": {name: crop.bbox for name, crop in crops.items()},
    }
    return NormalizationResult(normalized_image=normalized_image, crops=crops, debug_outputs=debug_outputs)


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
