from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy

from .roi import ROI_PRESETS, resolved_group_rois, roi_group_expand_factors, scaled_roi_bbox_within_bounds
from .utils.geometry import Quad, quad_from_bbox

CANONICAL_CARD_SIZE = (880, 630)  # height, width


@dataclass(frozen=True)
class CropRegion:
    label: str
    bbox: tuple[int, int, int, int]
    shape: tuple[int, int, int]
    image_array: Any | None = None


@dataclass(frozen=True)
class NormalizedCardImage:
    shape: tuple[int, int, int]
    source_bbox: tuple[int, int, int, int] | None
    source_quad: Quad | None
    source_shape: tuple[int, int, int] | None
    destination_quad: Quad | None
    source_image: Any | None = None
    image_array: Any | None = None
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
    roi_groups: list[str] | None = None,
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> NormalizationResult:
    """Normalize the detected region into a canonical card-sized descriptor."""
    if bbox is None:
        return NormalizationResult(normalized_image=image, crops={}, debug_outputs={})

    source_shape = getattr(image, "shape", None)
    source_quad = quad or getattr(image, "card_quad", None) or quad_from_bbox(bbox)
    rectangular_quad = quad_from_bbox(bbox)
    destination_quad = quad_from_bbox((0, 0, CANONICAL_CARD_SIZE[1], CANONICAL_CARD_SIZE[0]))
    roi_overrides = getattr(image, "roi_overrides", {})
    normalized_pixels = _warp_to_canonical(
        image,
        source_quad=source_quad,
        destination_quad=destination_quad,
        fallback_bbox=bbox,
    )
    normalized_image = NormalizedCardImage(
        shape=(CANONICAL_CARD_SIZE[0], CANONICAL_CARD_SIZE[1], 3),
        source_bbox=bbox,
        source_quad=source_quad,
        source_shape=source_shape,
        destination_quad=destination_quad,
        source_image=image,
        image_array=normalized_pixels,
        path=str(getattr(image, "path", "")) or None,
    )

    active_roi_groups = [group for group in (roi_groups or list(ROI_PRESETS)) if group in ROI_PRESETS]
    crops = _build_roi_crops(
        normalized_image.shape,
        active_roi_groups,
        roi_overrides=roi_overrides,
        normalized_pixels=normalized_pixels,
        expand_long_factor=expand_long_factor,
        expand_short_factor=expand_short_factor,
    )
    debug_outputs = {
        "source_bbox": bbox,
        "source_quad": source_quad,
        "destination_quad": destination_quad,
        "warp_method": "quad_to_canonical" if source_quad != rectangular_quad else "bbox_to_canonical",
        "roi_groups": _group_crop_bboxes(crops),
    }
    return NormalizationResult(normalized_image=normalized_image, crops=crops, debug_outputs=debug_outputs)


def _build_roi_crops(
    normalized_shape: tuple[int, int, int],
    roi_groups: list[str],
    *,
    roi_overrides: dict[str, dict[str, tuple[float, float, float, float]]] | None = None,
    normalized_pixels: Any | None = None,
    expand_long_factor: float = 1.0,
    expand_short_factor: float = 1.0,
) -> dict[str, CropRegion]:
    height, width, _ = normalized_shape
    crops: dict[str, CropRegion] = {}

    for group_name in roi_groups:
        rois = resolved_group_rois(group_name, overrides=(roi_overrides or {}).get(group_name))
        effective_long_factor, effective_short_factor = roi_group_expand_factors(
            group_name,
            expand_long_factor=expand_long_factor,
            expand_short_factor=expand_short_factor,
        )
        for roi in rois:
            crop_left, crop_top, crop_width, crop_height = scaled_roi_bbox_within_bounds(
                frame_width=width,
                frame_height=height,
                roi=roi,
                expand_long_factor=effective_long_factor,
                expand_short_factor=effective_short_factor,
            )
            crops[f"{group_name}:{roi.label}"] = CropRegion(
                label=roi.label,
                bbox=(crop_left, crop_top, crop_width, crop_height),
                shape=(crop_height, crop_width, 3),
                image_array=_crop_pixels(normalized_pixels, crop_left, crop_top, crop_width, crop_height),
            )

    return crops


def _group_crop_bboxes(crops: dict[str, CropRegion]) -> dict[str, list[tuple[str, tuple[int, int, int, int]]]]:
    grouped: dict[str, list[tuple[str, tuple[int, int, int, int]]]] = {}
    for crop_name, crop in crops.items():
        group_name, _, _ = crop_name.partition(":")
        grouped.setdefault(group_name, []).append((crop.label, crop.bbox))
    return grouped


def _warp_to_canonical(
    image: Any,
    *,
    source_quad: Quad,
    destination_quad: Quad,
    fallback_bbox: tuple[int, int, int, int],
) -> Any | None:
    source_pixels = _source_pixels(image)
    if source_pixels is None:
        return None

    try:
        transform = cv2.getPerspectiveTransform(
            numpy.array(source_quad, dtype=numpy.float32),
            numpy.array(destination_quad, dtype=numpy.float32),
        )
        return cv2.warpPerspective(
            source_pixels,
            transform,
            (CANONICAL_CARD_SIZE[1], CANONICAL_CARD_SIZE[0]),
        )
    except Exception:
        left, top, width, height = fallback_bbox
        cropped = source_pixels[top : top + height, left : left + width]
        if cropped is None or getattr(cropped, "size", 0) == 0:
            return None
        return cv2.resize(cropped, (CANONICAL_CARD_SIZE[1], CANONICAL_CARD_SIZE[0]))


def _source_pixels(image: Any) -> Any | None:
    for candidate in (image, getattr(image, "source_image", None)):
        if candidate is None:
            continue
        for attr_name in ("image_array", "pixels", "array"):
            value = getattr(candidate, attr_name, None)
            if value is not None:
                return value
    return None


def _crop_pixels(
    normalized_pixels: Any | None,
    left: int,
    top: int,
    width: int,
    height: int,
) -> Any | None:
    if normalized_pixels is None:
        return None

    try:
        cropped = normalized_pixels[top : top + height, left : left + width]
    except Exception:
        return None

    if cropped is None or getattr(cropped, "size", 0) == 0:
        return None
    return cropped
