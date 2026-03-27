import json

from scripts.report_split_family_metrics import build_family_rows


def test_build_family_rows_groups_by_split_family(tmp_path):
    classic_image = tmp_path / "fire-ice.png"
    classic_image.write_bytes(b"")
    classic_image.with_suffix(".json").write_text(
        json.dumps({"split_family": "classic_split"}),
        encoding="utf-8",
    )

    room_image = tmp_path / "bottomless-pool.png"
    room_image.write_bytes(b"")
    room_image.with_suffix(".json").write_text(
        json.dumps({"split_family": "room"}),
        encoding="utf-8",
    )

    report = {
        "mode_results": [
            {
                "mode_name": "greenfield",
                "summary": {
                    "fixtures": [
                        {
                            "path": str(classic_image),
                            "top1_hit": True,
                            "runtime_seconds": 1.5,
                        },
                        {
                            "path": str(room_image),
                            "top1_hit": False,
                            "runtime_seconds": 2.5,
                        },
                    ]
                },
            }
        ]
    }

    rows = build_family_rows(report)

    assert rows == [
        {
            "mode_name": "greenfield",
            "split_family": "classic_split",
            "fixture_count": 1,
            "correct": 1,
            "incorrect": 0,
            "top1_accuracy": 1.0,
            "average_runtime_seconds": 1.5,
        },
        {
            "mode_name": "greenfield",
            "split_family": "room",
            "fixture_count": 1,
            "correct": 0,
            "incorrect": 1,
            "top1_accuracy": 0.0,
            "average_runtime_seconds": 2.5,
        },
    ]


def test_build_family_rows_uses_unknown_when_sidecar_missing(tmp_path):
    image_path = tmp_path / "missing-sidecar.png"
    image_path.write_bytes(b"")

    report = {
        "mode_results": [
            {
                "mode_name": "small_pool",
                "summary": {
                    "fixtures": [
                        {
                            "path": str(image_path),
                            "top1_hit": True,
                            "runtime_seconds": 0.75,
                        }
                    ]
                },
            }
        ]
    }

    rows = build_family_rows(report)

    assert rows == [
        {
            "mode_name": "small_pool",
            "split_family": "unknown",
            "fixture_count": 1,
            "correct": 1,
            "incorrect": 0,
            "top1_accuracy": 1.0,
            "average_runtime_seconds": 0.75,
        }
    ]
