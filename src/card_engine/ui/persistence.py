from __future__ import annotations

import json
from pathlib import Path

from card_engine.utils.geometry import Quad

from .state import RelativeROI


def load_ui_overrides(path: str | Path) -> tuple[dict[Path, Quad], dict[str, dict[str, RelativeROI]]]:
    override_path = Path(path)
    if not override_path.exists():
        return {}, {}

    payload = json.loads(override_path.read_text(encoding="utf-8"))
    manual_quads = {
        Path(key): tuple((int(point[0]), int(point[1])) for point in value)
        for key, value in payload.get("manual_quads", {}).items()
    }
    manual_roi_overrides = _load_roi_overrides(payload.get("manual_roi_overrides", {}))
    return manual_quads, manual_roi_overrides


def save_ui_overrides(
    path: str | Path,
    *,
    manual_quads: dict[Path, Quad],
    manual_roi_overrides: dict[str, dict[str, RelativeROI]] | None = None,
) -> Path:
    override_path = Path(path)
    override_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "manual_quads": {
            str(key): [[point[0], point[1]] for point in value]
            for key, value in manual_quads.items()
        },
    }
    if manual_roi_overrides is not None:
        payload["manual_roi_overrides"] = {
            group_name: {
                label: list(roi_value)
                for label, roi_value in group_value.items()
            }
            for group_name, group_value in manual_roi_overrides.items()
        }
    override_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return override_path


def _load_roi_overrides(raw_overrides: dict) -> dict[str, dict[str, RelativeROI]]:
    if not isinstance(raw_overrides, dict):
        return {}

    if _looks_like_global_roi_override_map(raw_overrides):
        return {
            group_name: {
                label: tuple(float(component) for component in roi_value)
                for label, roi_value in group_value.items()
            }
            for group_name, group_value in raw_overrides.items()
        }

    migrated: dict[str, dict[str, RelativeROI]] = {}
    for _path_key, path_value in raw_overrides.items():
        if not isinstance(path_value, dict):
            continue
        for group_name, group_value in path_value.items():
            if not isinstance(group_value, dict):
                continue
            migrated[group_name] = {
                label: tuple(float(component) for component in roi_value)
                for label, roi_value in group_value.items()
            }
    return migrated


def _looks_like_global_roi_override_map(raw_overrides: dict) -> bool:
    if not raw_overrides:
        return True

    first_value = next(iter(raw_overrides.values()))
    if not isinstance(first_value, dict) or not first_value:
        return False

    nested_value = next(iter(first_value.values()))
    return isinstance(nested_value, (list, tuple))
