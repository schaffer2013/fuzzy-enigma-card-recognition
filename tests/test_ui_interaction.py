from card_engine.ui.interaction import (
    PreviewTransform,
    relative_roi_from_bboxes,
    update_bbox_corner_axis_aligned,
    canvas_to_source_point,
    nearest_quad_corner,
    source_to_canvas_point,
    update_quad_corner,
)


def test_source_and_canvas_point_conversion_round_trip():
    transform = PreviewTransform(
        offset_x=10,
        offset_y=20,
        rendered_width=200,
        rendered_height=100,
        source_width=100,
        source_height=50,
    )

    canvas_point = source_to_canvas_point(transform, (25, 10))
    source_point = canvas_to_source_point(transform, canvas_point)

    assert canvas_point == (60.0, 40.0)
    assert source_point == (25, 10)


def test_nearest_quad_corner_returns_closest_index():
    quad = ((10, 10), (90, 10), (90, 90), (10, 90))

    assert nearest_quad_corner(quad, (12, 14)) == 0
    assert nearest_quad_corner(quad, (88, 80)) == 2


def test_update_quad_corner_clamps_to_frame():
    quad = ((10, 10), (90, 10), (90, 90), (10, 90))

    updated = update_quad_corner(quad, 1, (150, -20), frame_width=100, frame_height=100)

    assert updated == ((10, 10), (100, 0), (90, 90), (10, 90))


def test_update_bbox_corner_axis_aligned_keeps_edges_parallel():
    bbox = (20, 30, 50, 40)

    updated = update_bbox_corner_axis_aligned(bbox, 2, (90, 100), frame_width=120, frame_height=120)

    assert updated == (20, 30, 70, 70)


def test_relative_roi_from_bboxes_returns_card_relative_values():
    relative = relative_roi_from_bboxes((10, 20, 100, 200), (35, 70, 40, 60))

    assert relative == (0.25, 0.25, 0.4, 0.3)
