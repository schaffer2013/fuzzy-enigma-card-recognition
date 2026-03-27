import json
import pytest

from card_engine.config import EngineConfig, parse_roi_expand_factors


def test_engine_config_from_file_reads_lazy_optimization_settings(tmp_path):
    config_path = tmp_path / "engine.json"
    config_path.write_text(
        json.dumps(
            {
                "lazy_group_basic_land_printings": True,
                "lazy_default_printing_by_name": False,
                "max_visual_tiebreak_candidates": 3,
                "max_visual_tiebreak_seconds_per_card": 12.5,
                "reference_download_timeout_seconds": 4.0,
                "roi_expand_long_factor": 1.1,
                "roi_expand_short_factor": 1.3,
            }
        ),
        encoding="utf-8",
    )

    config = EngineConfig.from_file(config_path)

    assert config.lazy_group_basic_land_printings is True
    assert config.lazy_default_printing_by_name is False
    assert config.max_visual_tiebreak_candidates == 3
    assert config.max_visual_tiebreak_seconds_per_card == 12.5
    assert config.reference_download_timeout_seconds == 4.0
    assert config.roi_expand_long_factor == 1.1
    assert config.roi_expand_short_factor == 1.3


def test_parse_roi_expand_factors_accepts_uniform_and_axis_values():
    assert parse_roi_expand_factors([1.1]) == (1.1, 1.1)
    assert parse_roi_expand_factors([1.1, 1.3]) == (1.1, 1.3)


def test_parse_roi_expand_factors_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_roi_expand_factors([0.0])
    with pytest.raises(ValueError):
        parse_roi_expand_factors([1.0, -1.0])
    with pytest.raises(ValueError):
        parse_roi_expand_factors([1.0, 1.1, 1.2])
