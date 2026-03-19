from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy


@dataclass(frozen=True)
class LoadedImage:
    path: Path
    image_format: str
    width: int
    height: int
    layout_hint: str | None = None
    ocr_text_by_roi: dict[str, Any] = field(default_factory=dict)
    image_array: Any | None = None

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.height, self.width, 3)


def load_image(path: str | Path) -> LoadedImage:
    image_path = Path(path)
    data = image_path.read_bytes()
    image_format, width, height = _read_image_metadata(data)
    metadata = _read_sidecar_metadata(image_path)
    return LoadedImage(
        path=image_path,
        image_format=image_format,
        width=width,
        height=height,
        layout_hint=_coerce_optional_string(metadata.get("layout_hint")),
        ocr_text_by_roi=_coerce_roi_mapping(metadata.get("ocr_text_by_roi")),
        image_array=_decode_image_array(data),
    )


def _read_image_metadata(data: bytes) -> tuple[str, int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height

    if data.startswith((b"GIF87a", b"GIF89a")) and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "gif", width, height

    if data.startswith(b"BM") and len(data) >= 26:
        width = struct.unpack("<I", data[18:22])[0]
        height = abs(struct.unpack("<i", data[22:26])[0])
        return "bmp", width, height

    if data.startswith(b"\xff\xd8"):
        return _read_jpeg_metadata(data)

    raise ValueError("Unsupported image format")


def _read_jpeg_metadata(data: bytes) -> tuple[str, int, int]:
    index = 2
    start_of_frame_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }

    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue

        while index < len(data) and data[index] == 0xFF:
            index += 1

        if index >= len(data):
            break

        marker = data[index]
        index += 1

        if marker in {0xD8, 0xD9}:
            continue

        if index + 2 > len(data):
            break

        segment_length = struct.unpack(">H", data[index : index + 2])[0]
        if segment_length < 2 or index + segment_length > len(data):
            break

        if marker in start_of_frame_markers and segment_length >= 7:
            height, width = struct.unpack(">HH", data[index + 3 : index + 7])
            return "jpeg", width, height

        index += segment_length

    raise ValueError("Unsupported or malformed JPEG image")


def _read_sidecar_metadata(image_path: Path) -> dict[str, Any]:
    sidecar_path = image_path.with_suffix(".json")
    if not sidecar_path.exists():
        return {}

    try:
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def _coerce_optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _coerce_roi_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _decode_image_array(data: bytes) -> Any | None:
    try:
        buffer = numpy.frombuffer(data, dtype=numpy.uint8)
        decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except Exception:
        return None
    return decoded
