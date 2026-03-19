from card_engine.roi import ordered_roi_groups, resolve_roi_groups_for_layout, roi_group_bboxes


def test_roi_ordering_respects_cycle_then_remainder():
    groups = ordered_roi_groups(["standard", "type_line", "lower_text", "alt"], ["type_line", "lower_text"])
    assert groups == ["type_line", "lower_text", "standard"]


def test_resolve_roi_groups_for_split_layout_includes_split_panels():
    groups = resolve_roi_groups_for_layout("split")

    assert groups == ["standard", "type_line", "lower_text", "split_left", "split_right"]


def test_roi_group_bboxes_projects_relative_rois_inside_card_bbox():
    entries = roi_group_bboxes((10, 20, 100, 200), "split_left")

    assert entries == [("left_panel_title", (15, 36, 40, 24))]


def test_roi_group_bboxes_supports_type_line_group():
    entries = roi_group_bboxes((10, 20, 100, 200), "type_line")

    assert entries == [("type_line", (18, 58, 84, 16))]


def test_roi_group_bboxes_applies_global_override():
    entries = roi_group_bboxes(
        (10, 20, 100, 200),
        "type_line",
        overrides={"type_line": (0.2, 0.3, 0.5, 0.1)},
    )

    assert entries == [("type_line", (30, 80, 50, 20))]
