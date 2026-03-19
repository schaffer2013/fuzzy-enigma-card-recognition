from pathlib import Path

from card_engine.models import Candidate, RecognitionResult

from .state import UIState

SUPPORTED_FIXTURE_SUFFIXES = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}


def discover_fixture_paths(fixtures_dir: str | Path | None) -> list[Path]:
    if fixtures_dir is None:
        return []

    root = Path(fixtures_dir)
    if not root.exists():
        return []

    paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_FIXTURE_SUFFIXES
    ]
    return sorted(paths, key=lambda path: str(path.relative_to(root)).lower())


def selected_fixture(state: UIState) -> Path | None:
    if not state.fixture_paths:
        return None

    if state.fixture_index >= len(state.fixture_paths):
        return state.fixture_paths[0]

    return state.fixture_paths[state.fixture_index]


def format_fixture_summary(state: UIState) -> str:
    fixture_path = selected_fixture(state)
    if fixture_path is None:
        return (
            "No fixture images found.\n\n"
            "Point the UI at a fixture folder to browse image files and inspect "
            "recognition metadata as the engine grows."
        )

    size_bytes = fixture_path.stat().st_size
    summary_lines = [
        f"Fixture: {fixture_path.name}",
        f"Path: {fixture_path}",
        f"Index: {state.fixture_index + 1} / {len(state.fixture_paths)}",
        f"Active ROI: {state.active_roi}",
        f"Show bbox: {'yes' if state.show_bbox else 'no'}",
        f"Size: {size_bytes} bytes",
    ]

    if state.current_image is not None:
        summary_lines.extend(
            [
                f"Format: {state.current_image.image_format}",
                f"Dimensions: {state.current_image.width} x {state.current_image.height}",
                (
                    "OCR metadata: "
                    + (", ".join(sorted(state.current_image.ocr_text_by_roi)) if state.current_image.ocr_text_by_roi else "none")
                ),
            ]
        )

    return "\n".join(summary_lines)


def format_status_summary(state: UIState) -> str:
    fixture_path = selected_fixture(state)
    fixture_label = fixture_path.name if fixture_path is not None else "none"
    return "\n".join(
        [
            "Card Engine Debug UI",
            "",
            f"Selected fixture: {fixture_label}",
            f"ROI preset: {state.active_roi}",
            f"Bounding box overlay: {'enabled' if state.show_bbox else 'hidden'}",
            "",
            state.status_message,
        ]
    )


def format_recognition_summary(result: RecognitionResult | None) -> str:
    if result is None:
        return "Recognition has not run yet."

    lines = [
        f"Best name: {result.best_name or 'None'}",
        f"Confidence: {result.confidence:.2f}",
        f"Active ROI: {result.active_roi or 'None'}",
        f"Tried ROIs: {', '.join(result.tried_rois) if result.tried_rois else 'None'}",
        f"BBox: {result.bbox}",
    ]

    if result.ocr_lines:
        lines.append(f"OCR: {' | '.join(result.ocr_lines)}")
    else:
        lines.append("OCR: No text detected.")

    roi_results = result.debug.get("ocr", {}).get("results_by_roi", {})
    if roi_results:
        lines.append("")
        lines.append("OCR by ROI:")
        for roi_name in result.tried_rois:
            roi_result = roi_results.get(roi_name, {})
            roi_lines = roi_result.get("lines", [])
            roi_confidence = roi_result.get("confidence", 0.0)
            roi_text = " | ".join(roi_lines) if roi_lines else "No text"
            backend = roi_result.get("debug", {}).get("backend", "unknown")
            lines.append(f"  - {roi_name}: {roi_text} (confidence={roi_confidence:.2f}; backend={backend})")

    lines.append("")
    lines.append("Candidates:")
    if result.top_k_candidates:
        lines.extend(format_candidate_line(candidate) for candidate in result.top_k_candidates[:5])
    else:
        lines.append("  - none")

    return "\n".join(lines)


def format_candidate_line(candidate: Candidate) -> str:
    details = [f"score={candidate.score:.2f}"]
    if candidate.set_code:
        details.append(f"set={candidate.set_code}")
    if candidate.collector_number:
        details.append(f"collector={candidate.collector_number}")
    if candidate.notes:
        details.append(f"notes={', '.join(candidate.notes)}")

    return f"  - {candidate.name} ({'; '.join(details)})"
