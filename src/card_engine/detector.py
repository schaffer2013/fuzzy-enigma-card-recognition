from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .utils.geometry import (
    TARGET_CARD_RATIO,
    Quad,
    area,
    aspect_ratio,
    bbox_from_quad,
    centered_aspect_bbox,
    clamp_bbox,
    clamp_quad,
    quad_from_bbox,
)


@dataclass
class DetectionResult:
    bbox: tuple[int, int, int, int] | None
    quad: Quad | None
    score: float
    debug: dict[str, Any]


def detect_card(image: Any) -> DetectionResult:
    """Lightweight geometric detector for synthetic and metadata-driven images.

    Priority order:
    1. Explicit `card_bbox` hint on the image object.
    2. Best-scoring bbox from `candidate_bboxes`.
    3. Full-frame when the frame already looks card-shaped.
    4. Largest centered card-ratio crop inside the frame.
    """
    frame_height = getattr(image, "shape", [0, 0])[0] if image is not None else 0
    frame_width = getattr(image, "shape", [0, 0])[1] if image is not None else 0

    if frame_width <= 0 or frame_height <= 0:
        return DetectionResult(bbox=None, quad=None, score=0.0, debug={"method": "no_shape"})

    explicit_quad = getattr(image, "card_quad", None)
    if explicit_quad is not None:
        quad = clamp_quad(tuple(explicit_quad), frame_width=frame_width, frame_height=frame_height)
        bbox = bbox_from_quad(quad)
        return DetectionResult(
            bbox=bbox,
            quad=quad,
            score=_score_bbox(bbox, frame_width=frame_width, frame_height=frame_height),
            debug={"method": "explicit_quad"},
        )

    explicit_bbox = getattr(image, "card_bbox", None)
    if explicit_bbox is not None:
        bbox = clamp_bbox(tuple(explicit_bbox), frame_width=frame_width, frame_height=frame_height)
        return DetectionResult(
            bbox=bbox,
            quad=quad_from_bbox(bbox),
            score=_score_bbox(bbox, frame_width=frame_width, frame_height=frame_height),
            debug={"method": "explicit_bbox"},
        )

    candidate_quads = getattr(image, "candidate_quads", None)
    if candidate_quads:
        quads = [
            clamp_quad(tuple(candidate_quad), frame_width=frame_width, frame_height=frame_height)
            for candidate_quad in candidate_quads
        ]
        best_quad = max(
            quads,
            key=lambda candidate: _score_bbox(
                bbox_from_quad(candidate),
                frame_width=frame_width,
                frame_height=frame_height,
            ),
        )
        best_bbox = bbox_from_quad(best_quad)
        return DetectionResult(
            bbox=best_bbox,
            quad=best_quad,
            score=_score_bbox(best_bbox, frame_width=frame_width, frame_height=frame_height),
            debug={"method": "candidate_quads", "candidate_count": len(quads)},
        )

    candidate_bboxes = getattr(image, "candidate_bboxes", None)
    if candidate_bboxes:
        candidates = [
            clamp_bbox(tuple(candidate_bbox), frame_width=frame_width, frame_height=frame_height)
            for candidate_bbox in candidate_bboxes
        ]
        best_bbox = max(
            candidates,
            key=lambda candidate: _score_bbox(candidate, frame_width=frame_width, frame_height=frame_height),
        )
        return DetectionResult(
            bbox=best_bbox,
            quad=quad_from_bbox(best_bbox),
            score=_score_bbox(best_bbox, frame_width=frame_width, frame_height=frame_height),
            debug={"method": "candidate_bboxes", "candidate_count": len(candidates)},
        )

    full_frame_bbox = (0, 0, frame_width, frame_height)
    full_frame_ratio = aspect_ratio(frame_width, frame_height)
    if abs(full_frame_ratio - TARGET_CARD_RATIO) <= 0.12:
        return DetectionResult(
            bbox=full_frame_bbox,
            quad=quad_from_bbox(full_frame_bbox),
            score=_score_bbox(full_frame_bbox, frame_width=frame_width, frame_height=frame_height),
            debug={"method": "full_frame_ratio_match"},
        )

    inferred_bbox = centered_aspect_bbox(frame_width, frame_height, target_ratio=TARGET_CARD_RATIO)
    return DetectionResult(
        bbox=inferred_bbox,
        quad=quad_from_bbox(inferred_bbox),
        score=_score_bbox(inferred_bbox, frame_width=frame_width, frame_height=frame_height),
        debug={"method": "centered_aspect_crop", "target_ratio": TARGET_CARD_RATIO},
    )


def _score_bbox(
    bbox: tuple[int, int, int, int],
    *,
    frame_width: int,
    frame_height: int,
) -> float:
    _, _, width, height = bbox
    if width <= 0 or height <= 0:
        return 0.0

    ratio_error = abs(aspect_ratio(width, height) - TARGET_CARD_RATIO)
    ratio_score = max(0.0, 1.0 - (ratio_error / TARGET_CARD_RATIO))
    coverage_score = area(width, height) / max(1, area(frame_width, frame_height))
    edge_score = 1.0 if width < frame_width and height < frame_height else 0.85

    return round((ratio_score * 0.55) + (coverage_score * 0.3) + (edge_score * 0.15), 4)
