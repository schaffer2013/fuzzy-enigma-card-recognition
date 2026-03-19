from pathlib import Path
import json

from card_engine.ui.persistence import load_ui_overrides, save_ui_overrides


def test_save_and_load_ui_overrides_round_trip(tmp_path):
    path = tmp_path / "ui_overrides.json"
    manual_quads = {
        Path("fixture-a.png"): ((1, 2), (3, 4), (5, 6), (7, 8)),
    }
    manual_roi_overrides = {
        "standard": {
            "title_band": (0.1, 0.2, 0.3, 0.4),
        }
    }

    save_ui_overrides(
        path,
        manual_quads=manual_quads,
        manual_roi_overrides=manual_roi_overrides,
    )

    loaded_quads, loaded_rois = load_ui_overrides(path)

    assert loaded_quads == manual_quads
    assert loaded_rois == manual_roi_overrides


def test_load_ui_overrides_migrates_legacy_per_image_roi_format(tmp_path):
    path = tmp_path / "ui_overrides.json"
    path.write_text(
        json.dumps(
            {
                "manual_quads": {},
                "manual_roi_overrides": {
                    "data/cache/random_cards/card-a.png": {
                        "standard": {
                            "title_band": [0.1, 0.2, 0.3, 0.4],
                        }
                    },
                    "data/cache/random_cards/card-b.png": {
                        "type_line": {
                            "type_line": [0.5, 0.6, 0.2, 0.1],
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    loaded_quads, loaded_rois = load_ui_overrides(path)

    assert loaded_quads == {}
    assert loaded_rois == {
        "standard": {"title_band": (0.1, 0.2, 0.3, 0.4)},
        "type_line": {"type_line": (0.5, 0.6, 0.2, 0.1)},
    }
