#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from card_engine.api import _rotated_crop_region
from card_engine.detector import detect_card
from card_engine.normalize import CropRegion, normalize_card
from card_engine.ocr import run_ocr
from card_engine.roi import resolve_roi_groups_for_layout
from card_engine.split_fixtures import DEFAULT_SPLIT_FIXTURES_DIR, split_face_names
from card_engine.utils.image_io import load_image
from card_engine.utils.text_normalize import normalize_text

ROTATIONS = (90, 270)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze vertical title hotspots across split-card fixtures using whole-card rotated OCR.",
    )
    parser.add_argument(
        "--fixtures-dir",
        default=str(DEFAULT_SPLIT_FIXTURES_DIR),
        help="Fixture directory to analyze.",
    )
    parser.add_argument(
        "--output-json",
        default="data/sample_outputs/split_title_hotspots.json",
        help="Where to write the hotspot summary JSON.",
    )
    parser.add_argument(
        "--output-csv",
        default="data/sample_outputs/split_title_hotspots_boxes.csv",
        help="Where to write the matched-box CSV.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit on fixture count for faster experimentation.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    fixtures_dir = Path(args.fixtures_dir)
    output_json = Path(args.output_json)
    output_csv = Path(args.output_csv)

    image_paths = sorted(
        path
        for path in fixtures_dir.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    if args.limit > 0:
        image_paths = image_paths[: args.limit]

    observations: list[dict] = []
    fixture_summaries: list[dict] = []
    by_rotation: dict[int, list[dict]] = defaultdict(list)
    by_set_rotation: dict[str, Counter] = defaultdict(Counter)
    total = len(image_paths)

    for index, image_path in enumerate(image_paths, start=1):
        sidecar_path = image_path.with_suffix(".json")
        if not sidecar_path.exists():
            continue
        payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
        face_names = split_face_names(payload.get("expected_name"))
        if face_names is None:
            continue
        expected_faces = {
            "left": normalize_text(face_names[0]),
            "right": normalize_text(face_names[1]),
        }

        image = load_image(str(image_path))
        detection = detect_card(image)
        normalized = normalize_card(
            image,
            detection.bbox,
            quad=detection.quad,
            roi_groups=resolve_roi_groups_for_layout("split"),
        )
        image_array = normalized.normalized_image.image_array
        full_crop = CropRegion(
            label="full_card",
            bbox=(0, 0, image_array.shape[1], image_array.shape[0]),
            shape=image_array.shape,
            image_array=image_array,
        )

        fixture_rotation_hits = []
        for rotation in ROTATIONS:
            rotated_crop = _rotated_crop_region(full_crop, rotation)
            result = run_ocr(normalized.normalized_image, roi_label="full_card", crop_region=rotated_crop)
            matched_boxes: list[dict] = []
            for line_box in result.line_boxes:
                face_side = _matching_face_side(str(line_box.get("normalized_text") or ""), expected_faces)
                if face_side is None:
                    continue
                transformed = _transform_line_box_to_original(line_box, rotation, image_array.shape[1], image_array.shape[0])
                observation = {
                    "fixture": image_path.name,
                    "expected_name": payload.get("expected_name"),
                    "expected_set_code": payload.get("expected_set_code"),
                    "rotation_degrees": rotation,
                    "matched_text": line_box.get("text"),
                    "face_side": face_side,
                    "confidence": line_box.get("confidence"),
                    "bbox": transformed["bbox"],
                    "points": transformed["points"],
                    "center_x": transformed["center_x"],
                    "center_y": transformed["center_y"],
                    "width": transformed["width"],
                    "height": transformed["height"],
                    "normalized_center_x": round(transformed["center_x"] / image_array.shape[1], 4),
                    "normalized_center_y": round(transformed["center_y"] / image_array.shape[0], 4),
                    "normalized_width": round(transformed["width"] / image_array.shape[1], 4),
                    "normalized_height": round(transformed["height"] / image_array.shape[0], 4),
                }
                matched_boxes.append(observation)
                observations.append(observation)
                by_rotation[rotation].append(observation)
                by_set_rotation[(payload.get("expected_set_code") or "?").lower()][rotation] += 1

            fixture_rotation_hits.append(
                {
                    "rotation_degrees": rotation,
                    "matched_box_count": len(matched_boxes),
                    "matched_texts": [entry["matched_text"] for entry in matched_boxes],
                    "ocr_lines": result.lines,
                }
            )

        best_rotation = max(
            fixture_rotation_hits,
            key=lambda item: (item["matched_box_count"], len(item["ocr_lines"]), sum(len(line) for line in item["ocr_lines"])),
        )
        fixture_summaries.append(
            {
                "fixture": image_path.name,
                "expected_name": payload.get("expected_name"),
                "expected_set_code": payload.get("expected_set_code"),
                "best_rotation_degrees": best_rotation["rotation_degrees"],
                "matched_box_count": best_rotation["matched_box_count"],
                "rotation_hits": fixture_rotation_hits,
            }
        )
        if index % 25 == 0 or index == total:
            print(f"[hotspots] {index}/{total}: {image_path.name}")

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    best_rotation_counts = Counter(
        str(item["best_rotation_degrees"])
        for item in fixture_summaries
        if item["matched_box_count"] > 0
    )
    summary = {
        "fixtures_dir": str(fixtures_dir),
        "fixture_count": len(fixture_summaries),
        "no_match_fixture_count": sum(1 for item in fixture_summaries if item["matched_box_count"] == 0),
        "matched_box_count": len(observations),
        "best_rotation_counts": dict(best_rotation_counts),
        "rotation_summary": {
            str(rotation): _summarize_observations(by_rotation.get(rotation, []))
            for rotation in ROTATIONS
        },
        "set_rotation_counts": {
            set_code: {str(rotation): count for rotation, count in sorted(counter.items())}
            for set_code, counter in sorted(by_set_rotation.items())
        },
        "fixtures": fixture_summaries,
    }
    output_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "fixture",
                "expected_name",
                "expected_set_code",
                "rotation_degrees",
                "matched_text",
                "face_side",
                "confidence",
                "center_x",
                "center_y",
                "width",
                "height",
                "normalized_center_x",
                "normalized_center_y",
                "normalized_width",
                "normalized_height",
                "bbox",
                "points",
            ],
        )
        writer.writeheader()
        for observation in observations:
            row = observation.copy()
            row["bbox"] = json.dumps(row["bbox"], separators=(",", ":"))
            row["points"] = json.dumps(row["points"], separators=(",", ":"))
            writer.writerow(row)

    print(f"Wrote hotspot summary to {output_json}")
    print(f"Wrote matched box CSV to {output_csv}")
    return 0


def _matching_face_side(normalized_text: str, expected_faces: dict[str, str]) -> str | None:
    if not normalized_text:
        return None
    for side, expected_text in expected_faces.items():
        if not expected_text:
            continue
        if normalized_text == expected_text:
            return side
        if normalized_text in expected_text or expected_text in normalized_text:
            return side
    return None


def _transform_line_box_to_original(
    line_box: dict,
    rotation_degrees: int,
    original_width: int,
    original_height: int,
) -> dict:
    points = line_box.get("points") or _bbox_to_points(line_box.get("bbox"))
    transformed_points = [_inverse_rotate_point(point[0], point[1], rotation_degrees, original_width, original_height) for point in points]
    bbox = _points_bbox(transformed_points)
    return {
        "points": [[round(point[0], 2), round(point[1], 2)] for point in transformed_points],
        "bbox": [round(component, 2) for component in bbox],
        "center_x": bbox[0] + (bbox[2] / 2.0),
        "center_y": bbox[1] + (bbox[3] / 2.0),
        "width": bbox[2],
        "height": bbox[3],
    }


def _bbox_to_points(bbox) -> list[list[float]]:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return []
    x, y, w, h = [float(component) for component in bbox]
    return [
        [x, y],
        [x + w, y],
        [x + w, y + h],
        [x, y + h],
    ]


def _inverse_rotate_point(
    x_rot: float,
    y_rot: float,
    rotation_degrees: int,
    original_width: int,
    original_height: int,
) -> list[float]:
    if rotation_degrees == 90:
        return [y_rot, max(0.0, (original_height - 1) - x_rot)]
    if rotation_degrees == 270:
        return [max(0.0, (original_width - 1) - y_rot), x_rot]
    if rotation_degrees == 180:
        return [max(0.0, (original_width - 1) - x_rot), max(0.0, (original_height - 1) - y_rot)]
    return [x_rot, y_rot]


def _points_bbox(points: list[list[float]]) -> list[float]:
    if not points:
        return [0.0, 0.0, 0.0, 0.0]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    min_x = min(xs)
    min_y = min(ys)
    return [min_x, min_y, max(xs) - min_x, max(ys) - min_y]


def _summarize_observations(observations: list[dict]) -> dict:
    if not observations:
        return {
            "matched_box_count": 0,
            "normalized_center_x": {},
            "normalized_center_y": {},
            "normalized_width": {},
            "normalized_height": {},
        }
    return {
        "matched_box_count": len(observations),
        "normalized_center_x": _metric_summary([item["normalized_center_x"] for item in observations]),
        "normalized_center_y": _metric_summary([item["normalized_center_y"] for item in observations]),
        "normalized_width": _metric_summary([item["normalized_width"] for item in observations]),
        "normalized_height": _metric_summary([item["normalized_height"] for item in observations]),
    }


def _metric_summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 4),
        "p10": round(_percentile(ordered, 0.10), 4),
        "mean": round(sum(ordered) / len(ordered), 4),
        "median": round(_percentile(ordered, 0.50), 4),
        "p90": round(_percentile(ordered, 0.90), 4),
        "max": round(ordered[-1], 4),
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    index = max(0.0, min((len(values) - 1) * fraction, len(values) - 1))
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return values[lower]
    weight = index - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


if __name__ == "__main__":
    raise SystemExit(main())
