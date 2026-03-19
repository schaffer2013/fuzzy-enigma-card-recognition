from __future__ import annotations

from dataclasses import dataclass

from card_engine.utils.geometry import Quad, clamp_quad


@dataclass(frozen=True)
class PreviewTransform:
    offset_x: float
    offset_y: float
    rendered_width: int
    rendered_height: int
    source_width: int
    source_height: int


def source_to_canvas_point(transform: PreviewTransform, point: tuple[int, int]) -> tuple[float, float]:
    x, y = point
    return (
        transform.offset_x + (x * (transform.rendered_width / max(transform.source_width, 1))),
        transform.offset_y + (y * (transform.rendered_height / max(transform.source_height, 1))),
    )


def canvas_to_source_point(transform: PreviewTransform, point: tuple[float, float]) -> tuple[int, int]:
    x, y = point
    source_x = int(round((x - transform.offset_x) * (transform.source_width / max(transform.rendered_width, 1))))
    source_y = int(round((y - transform.offset_y) * (transform.source_height / max(transform.rendered_height, 1))))
    clamped = clamp_quad(
        ((source_x, source_y), (source_x, source_y), (source_x, source_y), (source_x, source_y)),
        frame_width=transform.source_width,
        frame_height=transform.source_height,
    )[0]
    return clamped


def nearest_quad_corner(quad: Quad, point: tuple[int, int]) -> int:
    return min(range(len(quad)), key=lambda index: _distance_squared(quad[index], point))


def update_quad_corner(
    quad: Quad,
    corner_index: int,
    point: tuple[int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> Quad:
    updated = list(quad)
    updated[corner_index] = point
    return clamp_quad(tuple(updated), frame_width=frame_width, frame_height=frame_height)


def bbox_corners(bbox: tuple[int, int, int, int]) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int], tuple[int, int]]:
    left, top, width, height = bbox
    return (
        (left, top),
        (left + width, top),
        (left + width, top + height),
        (left, top + height),
    )


def update_bbox_corner_axis_aligned(
    bbox: tuple[int, int, int, int],
    corner_index: int,
    point: tuple[int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    corners = list(bbox_corners(bbox))
    opposite_corner = corners[(corner_index + 2) % 4]
    x1, y1 = opposite_corner
    x2, y2 = point

    left = max(0, min(x1, x2))
    top = max(0, min(y1, y2))
    right = min(frame_width, max(x1, x2))
    bottom = min(frame_height, max(y1, y2))
    return (left, top, max(1, right - left), max(1, bottom - top))


def relative_roi_from_bboxes(
    card_bbox: tuple[int, int, int, int],
    roi_bbox: tuple[int, int, int, int],
) -> tuple[float, float, float, float]:
    card_left, card_top, card_width, card_height = card_bbox
    roi_left, roi_top, roi_width, roi_height = roi_bbox

    if card_width <= 0 or card_height <= 0:
        return (0.0, 0.0, 1.0, 1.0)

    return (
        max(0.0, min(1.0, (roi_left - card_left) / card_width)),
        max(0.0, min(1.0, (roi_top - card_top) / card_height)),
        max(0.0, min(1.0, roi_width / card_width)),
        max(0.0, min(1.0, roi_height / card_height)),
    )


def _distance_squared(a: tuple[int, int], b: tuple[int, int]) -> int:
    return ((a[0] - b[0]) ** 2) + ((a[1] - b[1]) ** 2)
