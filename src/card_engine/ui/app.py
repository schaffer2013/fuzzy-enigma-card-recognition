from __future__ import annotations

import argparse
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from card_engine.api import recognize_card
from card_engine.catalog.scryfall_sync import fetch_random_card_image
from card_engine.roi import DEFAULT_ENABLED_ROI_GROUPS, roi_group_bboxes
from card_engine.utils.image_io import load_image

from .state import UIState, cycle_active_roi, cycle_fixture_index
from .views import (
    discover_fixture_paths,
    format_fixture_summary,
    format_recognition_summary,
    format_status_summary,
    selected_fixture,
)
from .widgets import make_panel, make_readonly_text, set_readonly_text

DEFAULT_ROIS = list(DEFAULT_ENABLED_ROI_GROUPS)


class CardEngineDebugUI:
    def __init__(self, fixtures_dir: str | None = None):
        self.fixtures_dir = fixtures_dir or _default_fixtures_dir()
        self.state = UIState()
        self.state.fixture_paths = discover_fixture_paths(self.fixtures_dir)
        self.preview_image: tk.PhotoImage | None = None
        self.root = tk.Tk()
        self.root.title("Card Engine Debug UI")
        self.root.minsize(1180, 720)

        self._build_layout()
        self._bind_shortcuts()
        self._refresh()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=3)
        self.root.columnconfigure(2, weight=2)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 12, 12, 0))
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        for column in range(8):
            toolbar.columnconfigure(column, weight=1 if column == 7 else 0)

        ttk.Button(toolbar, text="Prev", command=self._select_previous_fixture).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="Next", command=self._select_next_fixture).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="Cycle ROI", command=self._cycle_roi).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="Toggle BBox", command=self._toggle_bbox).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="Refresh", command=self._refresh_fixture_list).grid(row=0, column=4)
        ttk.Button(toolbar, text="Random Card", command=self._fetch_random_card).grid(row=0, column=5, padx=(0, 8))

        self.fixture_count_var = tk.StringVar(value="0 fixtures")
        ttk.Label(toolbar, textvariable=self.fixture_count_var).grid(row=0, column=7, sticky="e")

        fixture_panel = make_panel(self.root, "Fixtures")
        fixture_panel.grid(row=1, column=0, sticky="nsew", padx=(12, 6), pady=12)

        self.fixture_list = tk.Listbox(fixture_panel, exportselection=False)
        self.fixture_list.grid(row=0, column=0, sticky="nsew")
        self.fixture_list.bind("<<ListboxSelect>>", self._on_fixture_selected)

        preview_panel = make_panel(self.root, "Preview")
        preview_panel.grid(row=1, column=1, sticky="nsew", padx=6, pady=12)
        self.preview_canvas = tk.Canvas(preview_panel, background="#1f2328", highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._refresh_preview())

        sidebar = ttk.Frame(self.root)
        sidebar.grid(row=1, column=2, sticky="nsew", padx=(6, 12), pady=12)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)
        sidebar.rowconfigure(2, weight=1)

        detail_panel = make_panel(sidebar, "Fixture Details")
        detail_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        self.fixture_text = make_readonly_text(detail_panel, height=10, width=44)
        self.fixture_text.grid(row=0, column=0, sticky="nsew")

        recognition_panel = make_panel(sidebar, "Recognition")
        recognition_panel.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.recognition_text = make_readonly_text(recognition_panel, height=12, width=44)
        self.recognition_text.grid(row=0, column=0, sticky="nsew")

        status_panel = make_panel(sidebar, "Status")
        status_panel.grid(row=2, column=0, sticky="nsew")
        self.status_text = make_readonly_text(status_panel, height=8, width=44)
        self.status_text.grid(row=0, column=0, sticky="nsew")

        footer = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        footer.grid(row=2, column=0, columnspan=3, sticky="ew")
        footer.columnconfigure(0, weight=1)

        self.footer_var = tk.StringVar(
            value="Use Left/Right to browse fixtures, R to cycle ROI, B to toggle bbox, or Random Card to fetch one."
        )
        ttk.Label(footer, textvariable=self.footer_var).grid(row=0, column=0, sticky="w")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Left>", lambda _event: self._select_previous_fixture())
        self.root.bind("<Right>", lambda _event: self._select_next_fixture())
        self.root.bind("<Key-r>", lambda _event: self._cycle_roi())
        self.root.bind("<Key-b>", lambda _event: self._toggle_bbox())

    def _refresh_fixture_list(self) -> None:
        self.state.fixture_paths = discover_fixture_paths(self.fixtures_dir)
        self.state.fixture_index = 0
        self.state.status_message = "Refreshed fixture list."
        self._refresh()

    def _select_previous_fixture(self) -> None:
        self.state.fixture_index = cycle_fixture_index(self.state.fixture_index, -1, len(self.state.fixture_paths))
        self.state.status_message = "Moved to previous fixture."
        self._refresh()

    def _select_next_fixture(self) -> None:
        self.state.fixture_index = cycle_fixture_index(self.state.fixture_index, 1, len(self.state.fixture_paths))
        self.state.status_message = "Moved to next fixture."
        self._refresh()

    def _cycle_roi(self) -> None:
        self.state.active_roi = cycle_active_roi(self.state.active_roi, self._available_roi_groups())
        self.state.status_message = f"Active ROI changed to {self.state.active_roi}."
        self._refresh()

    def _toggle_bbox(self) -> None:
        self.state.show_bbox = not self.state.show_bbox
        self.state.status_message = (
            "Bounding box overlay enabled." if self.state.show_bbox else "Bounding box overlay hidden."
        )
        self._refresh()

    def _on_fixture_selected(self, _event) -> None:
        selection = self.fixture_list.curselection()
        if not selection:
            return

        self.state.fixture_index = selection[0]
        self.state.status_message = "Selected fixture from browser."
        self._refresh()

    def _fetch_random_card(self) -> None:
        self.state.status_message = "Fetching a random card image from Scrython..."
        set_readonly_text(self.status_text, format_status_summary(self.state))
        self.root.update_idletasks()

        try:
            random_image_path = fetch_random_card_image(_default_random_cache_dir())
        except Exception as exc:
            self.state.status_message = f"Random card fetch failed: {exc}"
            set_readonly_text(self.status_text, format_status_summary(self.state))
            return

        existing = [path for path in self.state.fixture_paths if path != random_image_path]
        self.state.fixture_paths = [random_image_path] + existing
        self.state.fixture_index = 0
        self._refresh()
        self.state.status_message = f"Fetched random card image: {random_image_path.name}"
        set_readonly_text(self.status_text, format_status_summary(self.state))

    def _refresh(self) -> None:
        if self.state.fixture_paths:
            self.state.fixture_index %= len(self.state.fixture_paths)
        else:
            self.state.fixture_index = 0

        self._load_selected_fixture_state()
        self._sync_active_roi()
        self.fixture_count_var.set(f"{len(self.state.fixture_paths)} fixture(s)")
        self.fixture_list.delete(0, tk.END)
        for fixture_path in self.state.fixture_paths:
            self.fixture_list.insert(tk.END, fixture_path.name)

        if self.state.fixture_paths:
            self.fixture_list.selection_clear(0, tk.END)
            self.fixture_list.selection_set(self.state.fixture_index)
            self.fixture_list.activate(self.state.fixture_index)

        set_readonly_text(self.fixture_text, format_fixture_summary(self.state))
        set_readonly_text(self.recognition_text, format_recognition_summary(self.state.recognition_result))
        set_readonly_text(self.status_text, format_status_summary(self.state))
        self._refresh_preview()

    def _load_selected_fixture_state(self) -> None:
        fixture_path = selected_fixture(self.state)
        if fixture_path is None:
            self.state.current_image = None
            self.state.recognition_result = None
            self.state.preview_message = "No fixture selected."
            return

        try:
            self.state.current_image = load_image(fixture_path)
        except Exception as exc:
            self.state.current_image = None
            self.state.recognition_result = None
            self.state.preview_message = f"Could not read image metadata: {exc}"
            self.state.status_message = f"Failed to load image metadata for {fixture_path.name}."
            return

        try:
            self.state.recognition_result = recognize_card(fixture_path)
        except Exception as exc:
            self.state.recognition_result = None
            self.state.status_message = f"Recognition failed for {fixture_path.name}: {exc}"
        else:
            self.state.status_message = f"Recognition refreshed for {fixture_path.name}."

        self.state.preview_message = "Preview ready."

    def _refresh_preview(self) -> None:
        self.preview_canvas.delete("all")
        self.preview_image = None

        fixture_path = selected_fixture(self.state)
        if fixture_path is None:
            self._draw_preview_message("No fixture selected.")
            return

        try:
            preview_image = tk.PhotoImage(file=str(fixture_path))
        except tk.TclError:
            if self.state.current_image is not None:
                self._draw_preview_message(
                    "Preview unavailable for this format.\n\n"
                    f"Loaded metadata: {self.state.current_image.width} x {self.state.current_image.height} "
                    f"({self.state.current_image.image_format})"
                )
            else:
                self._draw_preview_message(self.state.preview_message)
            return

        canvas_width = max(self.preview_canvas.winfo_width(), 240)
        canvas_height = max(self.preview_canvas.winfo_height(), 240)
        scale_ratio = max(preview_image.width() / canvas_width, preview_image.height() / canvas_height, 1.0)
        downsample = max(1, math.ceil(scale_ratio))
        if downsample > 1:
            preview_image = preview_image.subsample(downsample, downsample)

        self.preview_image = preview_image
        image_x = canvas_width / 2
        image_y = canvas_height / 2
        self.preview_canvas.create_image(image_x, image_y, image=preview_image)

        if self.state.show_bbox and self.state.recognition_result and self.state.recognition_result.bbox and self.state.current_image:
            self._draw_bbox_overlay(
                bbox=self.state.recognition_result.bbox,
                image_center=(image_x, image_y),
                rendered_size=(preview_image.width(), preview_image.height()),
                source_size=(self.state.current_image.width, self.state.current_image.height),
            )
            self._draw_active_roi_overlay(
                card_bbox=self.state.recognition_result.bbox,
                image_center=(image_x, image_y),
                rendered_size=(preview_image.width(), preview_image.height()),
                source_size=(self.state.current_image.width, self.state.current_image.height),
            )

    def _draw_bbox_overlay(
        self,
        *,
        bbox: tuple[int, int, int, int],
        image_center: tuple[float, float],
        rendered_size: tuple[int, int],
        source_size: tuple[int, int],
    ) -> None:
        left, top, width, height = bbox
        render_width, render_height = rendered_size
        source_width, source_height = source_size
        offset_x = image_center[0] - (render_width / 2)
        offset_y = image_center[1] - (render_height / 2)
        scale_x = render_width / max(source_width, 1)
        scale_y = render_height / max(source_height, 1)

        self.preview_canvas.create_rectangle(
            offset_x + (left * scale_x),
            offset_y + (top * scale_y),
            offset_x + ((left + width) * scale_x),
            offset_y + ((top + height) * scale_y),
            outline="#4ade80",
            width=2,
        )

    def _draw_active_roi_overlay(
        self,
        *,
        card_bbox: tuple[int, int, int, int],
        image_center: tuple[float, float],
        rendered_size: tuple[int, int],
        source_size: tuple[int, int],
    ) -> None:
        roi_entries = roi_group_bboxes(card_bbox, self.state.active_roi)
        if not roi_entries:
            return

        render_width, render_height = rendered_size
        source_width, source_height = source_size
        offset_x = image_center[0] - (render_width / 2)
        offset_y = image_center[1] - (render_height / 2)
        scale_x = render_width / max(source_width, 1)
        scale_y = render_height / max(source_height, 1)

        for label, (left, top, width, height) in roi_entries:
            x1 = offset_x + (left * scale_x)
            y1 = offset_y + (top * scale_y)
            x2 = offset_x + ((left + width) * scale_x)
            y2 = offset_y + ((top + height) * scale_y)
            self.preview_canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                outline="#f59e0b",
                width=2,
            )
            self.preview_canvas.create_text(
                x1 + 4,
                y1 + 4,
                text=label,
                fill="#f59e0b",
                anchor="nw",
            )

    def _draw_preview_message(self, message: str) -> None:
        canvas_width = max(self.preview_canvas.winfo_width(), 240)
        canvas_height = max(self.preview_canvas.winfo_height(), 240)
        self.preview_canvas.create_text(
            canvas_width / 2,
            canvas_height / 2,
            text=message,
            fill="#d0d7de",
            width=canvas_width - 40,
            justify="center",
        )

    def _available_roi_groups(self) -> list[str]:
        if self.state.recognition_result and self.state.recognition_result.tried_rois:
            return self.state.recognition_result.tried_rois
        return DEFAULT_ROIS

    def _sync_active_roi(self) -> None:
        available_rois = self._available_roi_groups()
        if not available_rois:
            return
        if self.state.active_roi not in available_rois:
            self.state.active_roi = available_rois[0]

    def run(self) -> None:
        self.root.mainloop()


def _default_fixtures_dir() -> str:
    return str(Path("data") / "fixtures")


def _default_random_cache_dir() -> str:
    return str(Path("data") / "cache" / "random_cards")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Card Engine debug UI.")
    parser.add_argument(
        "--fixtures-dir",
        default=_default_fixtures_dir(),
        help="Directory containing fixture images to browse.",
    )
    return parser


def run_ui(fixtures_dir: str | None = None) -> None:
    app = CardEngineDebugUI(fixtures_dir=fixtures_dir)
    app.run()


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    run_ui(fixtures_dir=args.fixtures_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
