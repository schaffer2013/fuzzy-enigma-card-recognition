from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from card_engine.utils.geometry import Quad


@dataclass(frozen=True)
class EditableLoadedImage:
    path: Path
    image_format: str
    width: int
    height: int
    layout_hint: str | None
    content_hash: str | None
    image_array: object | None
    card_quad: Quad | None
    roi_overrides: dict[str, dict[str, tuple[float, float, float, float]]]

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.height, self.width, 3)
