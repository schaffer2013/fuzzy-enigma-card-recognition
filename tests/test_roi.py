from card_engine.roi import ordered_roi_groups


def test_roi_ordering_respects_cycle_then_remainder():
    groups = ordered_roi_groups(["standard", "lower_text", "alt"], ["lower_text"])
    assert groups == ["lower_text", "alt", "standard"]
