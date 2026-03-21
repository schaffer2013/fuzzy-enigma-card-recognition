import json

from card_engine.config import EngineConfig


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
