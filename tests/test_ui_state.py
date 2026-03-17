from card_engine.ui.state import cycle_active_roi, cycle_fixture_index


def test_cycle_fixture_index_wraps_both_directions():
    assert cycle_fixture_index(0, -1, 3) == 2
    assert cycle_fixture_index(2, 1, 3) == 0


def test_cycle_active_roi_advances_and_wraps():
    rois = ["standard", "lower_text", "alt"]
    assert cycle_active_roi("standard", rois) == "lower_text"
    assert cycle_active_roi("alt", rois) == "standard"
