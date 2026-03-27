from card_engine.normalize import normalize_card


class DummyImage:
    shape = (100, 80, 3)


def test_normalize_card_returns_canonical_descriptor_and_crops(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})
    result = normalize_card(
        DummyImage(),
        (8, 12, 63, 88),
        quad=((8, 12), (69, 10), (71, 100), (10, 102)),
    )

    assert result.normalized_image.shape == (880, 630, 3)
    assert result.normalized_image.source_bbox == (8, 12, 63, 88)
    assert result.normalized_image.destination_quad == ((0, 0), (630, 0), (630, 880), (0, 880))
    assert "standard:title_band" in result.crops
    assert result.crops["standard:title_band"].shape == (106, 529, 3)
    assert result.debug_outputs["warp_method"] == "quad_to_canonical"
    assert result.debug_outputs["source_quad"] == ((8, 12), (69, 10), (71, 100), (10, 102))


def test_normalize_card_expands_rois_from_center(monkeypatch):
    monkeypatch.setattr("card_engine.roi.repo_roi_overrides", lambda config_path=None: {})

    baseline = normalize_card(
        DummyImage(),
        (8, 12, 63, 88),
        quad=((8, 12), (69, 10), (71, 100), (10, 102)),
        roi_groups=["standard"],
    )
    expanded = normalize_card(
        DummyImage(),
        (8, 12, 63, 88),
        quad=((8, 12), (69, 10), (71, 100), (10, 102)),
        roi_groups=["standard"],
        expand_long_factor=1.1,
        expand_short_factor=1.3,
    )

    baseline_bbox = baseline.crops["standard:title_band"].bbox
    expanded_bbox = expanded.crops["standard:title_band"].bbox
    assert expanded_bbox[2] > baseline_bbox[2]
    assert expanded_bbox[3] > baseline_bbox[3]
    assert expanded_bbox[0] <= baseline_bbox[0]
    assert expanded_bbox[1] <= baseline_bbox[1]
