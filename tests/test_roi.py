import json

from card_engine.roi import ordered_roi_groups, repo_roi_overrides, resolve_roi_groups_for_layout, roi_group_bboxes, save_repo_roi_overrides


def test_roi_ordering_respects_cycle_then_remainder():
    groups = ordered_roi_groups(["standard", "type_line", "lower_text", "alt"], ["type_line", "lower_text"])
    assert groups == ["type_line", "lower_text", "standard"]


def test_resolve_roi_groups_for_split_layout_includes_split_panels():
    groups = resolve_roi_groups_for_layout("split")

    assert groups == ["planar_title", "split_full", "standard", "art_match", "type_line", "set_symbol", "lower_text"]


def test_roi_group_bboxes_projects_relative_rois_inside_card_bbox(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    entries = roi_group_bboxes((10, 20, 100, 200), "split_left")

    assert entries == [("left_panel_title", (13, 138, 12, 80))]


def test_roi_group_bboxes_supports_type_line_group(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    entries = roi_group_bboxes((10, 20, 100, 200), "type_line")

    assert entries == [("type_line", (18, 58, 84, 16))]


def test_roi_group_bboxes_supports_art_match_group(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    entries = roi_group_bboxes((10, 20, 100, 200), "art_match")

    assert entries == [("art_box", (18, 46, 84, 80))]


def test_roi_group_bboxes_can_expand_from_center(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    entries = roi_group_bboxes(
        (10, 20, 100, 200),
        "type_line",
        expand_long_factor=1.1,
        expand_short_factor=1.3,
    )

    assert entries == [("type_line", (14, 56, 92, 20))]


def test_roi_group_bboxes_do_not_expand_visual_regions(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    entries = roi_group_bboxes(
        (10, 20, 100, 200),
        "art_match",
        expand_long_factor=1.5,
        expand_short_factor=1.5,
    )

    assert entries == [("art_box", (18, 46, 84, 80))]


def test_roi_group_bboxes_supports_set_symbol_group(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    entries = roi_group_bboxes((10, 20, 100, 200), "set_symbol")

    assert entries == [("set_symbol", (91, 58, 10, 18))]


def test_roi_group_bboxes_applies_global_override():
    entries = roi_group_bboxes(
        (10, 20, 100, 200),
        "type_line",
        overrides={"type_line": (0.2, 0.3, 0.5, 0.1)},
    )

    assert entries == [("type_line", (30, 80, 50, 20))]


def test_save_repo_roi_overrides_round_trip(tmp_path):
    path = tmp_path / "hash_rois.json"
    overrides = {
        "standard": {"title_band": (0.1, 0.2, 0.3, 0.4)},
        "type_line": {"type_line": (0.5, 0.6, 0.2, 0.1)},
    }

    save_repo_roi_overrides(overrides, path)

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "standard": {"title_band": [0.1, 0.2, 0.3, 0.4]},
        "type_line": {"type_line": [0.5, 0.6, 0.2, 0.1]},
    }
    assert repo_roi_overrides(path) == overrides
