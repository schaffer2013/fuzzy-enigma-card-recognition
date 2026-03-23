from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import sqlite3
import tkinter as tk
from tkinter import ttk

from card_engine.api import recognize_card
from card_engine.art_match import ART_MATCH_CACHE_DIR
from card_engine.catalog.maintenance import catalog_refresh_needed, ensure_catalog_ready
from card_engine.catalog.scryfall_sync import fetch_random_card_image, prune_random_card_cache
from card_engine.roi import DEFAULT_ENABLED_ROI_GROUPS, roi_group_bboxes
from card_engine.utils.geometry import Quad, quad_from_bbox
from card_engine.utils.image_io import load_image

from .interaction import (
    PreviewTransform,
    bbox_corners,
    canvas_to_source_point,
    relative_roi_from_bboxes,
    source_to_canvas_point,
    update_bbox_corner_axis_aligned,
    update_quad_corner,
)
from .persistence import load_ui_overrides, save_ui_overrides
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


@dataclass(frozen=True)
class DragTarget:
    kind: str
    corner_index: int
    label: str | None = None


class OperationSplash:
    def __init__(self, root: tk.Tk, *, title: str, initial_message: str):
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.title(title)
        self.window.transient(root)
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(self.window, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)

        self.message_var = tk.StringVar(value=initial_message)
        ttk.Label(frame, text=title, font=("TkDefaultFont", 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.message_var, wraplength=360, justify="left").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(10, 10),
        )

        self.log_text = tk.Text(frame, height=8, width=52, state="disabled", wrap="word")
        self.log_text.grid(row=2, column=0, sticky="nsew")
        self.update(initial_message)

        self.window.update_idletasks()
        self.window.update()
        self._center_on_root()

    def update(self, message: str) -> None:
        self.message_var.set(message)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.window.update_idletasks()
        self.window.update()
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        self.window.destroy()
        self.root.update_idletasks()

    def _center_on_root(self) -> None:
        self.root.update_idletasks()
        root_x = self.root.winfo_rootx()
        root_y = self.root.winfo_rooty()
        root_w = max(self.root.winfo_width(), 800)
        root_h = max(self.root.winfo_height(), 600)
        window_w = self.window.winfo_width()
        window_h = self.window.winfo_height()
        x = root_x + max(0, (root_w - window_w) // 2)
        y = root_y + max(0, (root_h - window_h) // 2)
        self.window.geometry(f"+{x}+{y}")


class CardEngineDebugUI:
    def __init__(self, fixtures_dir: str | None = None):
        self.fixtures_dir = fixtures_dir or _default_fixtures_dir()
        self._overrides_path = _default_overrides_path()
        self.state = UIState()
        self.state.fixture_paths = discover_fixture_paths(self.fixtures_dir)
        manual_quads, manual_roi_overrides = load_ui_overrides(self._overrides_path)
        self.state.manual_quads = manual_quads
        self.state.manual_roi_overrides = manual_roi_overrides
        self.preview_image: tk.PhotoImage | None = None
        self.preview_transform: PreviewTransform | None = None
        self.active_drag_target: DragTarget | None = None
        self.root = tk.Tk()
        self.root.title("Card Engine Debug UI")
        self.root.minsize(1180, 720)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_layout()
        self._bind_shortcuts()
        self._prune_random_cache_if_needed()
        self._ensure_catalog()
        self._refresh()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=3)
        self.root.columnconfigure(2, weight=2)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 12, 12, 0))
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        for column in range(11):
            toolbar.columnconfigure(column, weight=1 if column == 10 else 0)

        ttk.Button(toolbar, text="Prev", command=self._select_previous_fixture).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="Next", command=self._select_next_fixture).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="Cycle ROI", command=self._cycle_roi).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(toolbar, text="Toggle BBox", command=self._toggle_bbox).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(toolbar, text="Refresh", command=self._refresh_fixture_list).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(toolbar, text="Random Card", command=self._fetch_random_card).grid(row=0, column=5, padx=(0, 8))
        ttk.Button(toolbar, text="Re-evaluate", command=self._re_evaluate).grid(row=0, column=6, padx=(0, 8))
        ttk.Button(toolbar, text="Reset BBox", command=self._reset_manual_bbox).grid(row=0, column=7, padx=(0, 8))
        ttk.Button(toolbar, text="Reset ROI", command=self._reset_manual_roi).grid(row=0, column=8, padx=(0, 8))

        self.fixture_count_var = tk.StringVar(value="0 fixtures")
        ttk.Label(toolbar, textvariable=self.fixture_count_var).grid(row=0, column=10, sticky="e")

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
        self.preview_canvas.bind("<Button-1>", self._on_preview_press)
        self.preview_canvas.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_preview_release)
        self.preview_canvas.bind("<Motion>", self._on_preview_motion)

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
        footer.columnconfigure(1, weight=0)

        self.footer_var = tk.StringVar(
            value="Use Left/Right to browse fixtures, drag green corners for bbox, drag orange corners for ROI, then click Re-evaluate."
        )
        ttk.Label(footer, textvariable=self.footer_var).grid(row=0, column=0, sticky="w")
        self.prehash_var = tk.StringVar(value="0/0 cards pre-hashed")
        ttk.Label(footer, textvariable=self.prehash_var).grid(row=0, column=1, sticky="e")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Left>", lambda _event: self._select_previous_fixture())
        self.root.bind("<Right>", lambda _event: self._select_next_fixture())
        self.root.bind("<Key-r>", lambda _event: self._cycle_roi())
        self.root.bind("<Key-b>", lambda _event: self._toggle_bbox())
        self.root.bind("<Escape>", lambda _event: self._reset_manual_bbox())

    def _refresh_fixture_list(self) -> None:
        self.state.fixture_paths = discover_fixture_paths(self.fixtures_dir)
        self.state.fixture_index = 0
        self.state.status_message = "Refreshed fixture list."
        self._refresh(run_recognition=True)

    def _select_previous_fixture(self) -> None:
        self.state.fixture_index = cycle_fixture_index(self.state.fixture_index, -1, len(self.state.fixture_paths))
        self.state.status_message = "Moved to previous fixture."
        self._refresh(run_recognition=True)

    def _select_next_fixture(self) -> None:
        self.state.fixture_index = cycle_fixture_index(self.state.fixture_index, 1, len(self.state.fixture_paths))
        self.state.status_message = "Moved to next fixture."
        self._refresh(run_recognition=True)

    def _cycle_roi(self) -> None:
        self.state.active_roi = cycle_active_roi(self.state.active_roi, self._available_roi_groups())
        self.state.status_message = f"Active ROI changed to {self.state.active_roi}. Recognition not rerun."
        self._refresh(run_recognition=False)

    def _toggle_bbox(self) -> None:
        self.state.show_bbox = not self.state.show_bbox
        self.state.status_message = (
            "Bounding box overlay enabled." if self.state.show_bbox else "Bounding box overlay hidden."
        )
        self._refresh(run_recognition=False)

    def _on_fixture_selected(self, _event) -> None:
        selection = self.fixture_list.curselection()
        if not selection:
            return

        self.state.fixture_index = selection[0]
        self.state.status_message = "Selected fixture from browser."
        self._refresh(run_recognition=True)

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
        self._refresh(run_recognition=True)
        self.state.status_message = f"Fetched random card image: {random_image_path.name}"
        set_readonly_text(self.status_text, format_status_summary(self.state))

    def _re_evaluate(self) -> None:
        fixture_path = selected_fixture(self.state)
        if fixture_path is None:
            return
        self.state.status_message = f"Re-evaluating {fixture_path.name}..."
        self._refresh(run_recognition=True)

    def _reset_manual_bbox(self) -> None:
        fixture_path = selected_fixture(self.state)
        if fixture_path is None:
            return
        if fixture_path in self.state.manual_quads:
            del self.state.manual_quads[fixture_path]
            self._save_overrides()
            self.state.status_message = f"Reset manual bbox override for {fixture_path.name}. Click Re-evaluate to apply."
            self._refresh(run_recognition=False)

    def _reset_manual_roi(self) -> None:
        if self.state.active_roi in self.state.manual_roi_overrides:
            del self.state.manual_roi_overrides[self.state.active_roi]
            self._save_overrides()
            self.state.status_message = f"Reset global ROI overrides for {self.state.active_roi}. Click Re-evaluate to apply."
            self._refresh(run_recognition=False)

    def _refresh(self, *, run_recognition: bool = True) -> None:
        if self.state.fixture_paths:
            self.state.fixture_index %= len(self.state.fixture_paths)
        else:
            self.state.fixture_index = 0

        self._load_selected_fixture_state(run_recognition=run_recognition)
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
        set_readonly_text(
            self.recognition_text,
            format_recognition_summary(
                self.state.recognition_result,
                error_message=self.state.recognition_error,
            ),
        )
        set_readonly_text(self.status_text, format_status_summary(self.state))
        self._refresh_prehash_summary()
        self._refresh_preview()

    def _load_selected_fixture_state(self, *, run_recognition: bool) -> None:
        fixture_path = selected_fixture(self.state)
        if fixture_path is None:
            self.state.current_image = None
            self.state.recognition_result = None
            self.state.recognition_error = None
            self.state.preview_message = "No fixture selected."
            return

        current_path = getattr(self.state.current_image, "path", None)
        if self.state.current_image is None or current_path != fixture_path:
            try:
                self.state.current_image = load_image(fixture_path)
            except Exception as exc:
                self.state.current_image = None
                self.state.recognition_result = None
                self.state.recognition_error = str(exc)
                self.state.preview_message = f"Could not read image metadata: {exc}"
                self.state.status_message = f"Failed to load image metadata for {fixture_path.name}."
                return

        if not run_recognition:
            self.state.preview_message = "Preview ready."
            return

        splash = OperationSplash(
            self.root,
            title="Recognizing Card",
            initial_message=f"Preparing recognition for {fixture_path.name}...",
        )
        try:
            self.state.recognition_result = recognize_card(
                self._build_recognition_input(),
                progress_callback=splash.update,
            )
            self.state.recognition_error = None
        except Exception as exc:
            self.state.recognition_result = None
            self.state.recognition_error = str(exc)
            self.state.status_message = f"Recognition failed for {fixture_path.name}: {exc}"
        else:
            self.state.status_message = f"Recognition refreshed for {fixture_path.name}."
        finally:
            splash.close()

        self.state.preview_message = "Preview ready."

    def _refresh_preview(self) -> None:
        self.preview_canvas.delete("all")
        self.preview_image = None
        self.preview_transform = None

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
        self.preview_transform = PreviewTransform(
            offset_x=image_x - (preview_image.width() / 2),
            offset_y=image_y - (preview_image.height() / 2),
            rendered_width=preview_image.width(),
            rendered_height=preview_image.height(),
            source_width=self.state.current_image.width,
            source_height=self.state.current_image.height,
        )

        if self.state.show_bbox and self.state.recognition_result and self.state.recognition_result.bbox and self.state.current_image:
            edit_quad = self._current_edit_quad()
            self._draw_bbox_overlay(
                quad=edit_quad or quad_from_bbox(self.state.recognition_result.bbox),
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
            self._draw_bbox_handles()
            self._draw_roi_handles()

    def _draw_bbox_overlay(
        self,
        *,
        quad: Quad,
        image_center: tuple[float, float],
        rendered_size: tuple[int, int],
        source_size: tuple[int, int],
    ) -> None:
        render_width, render_height = rendered_size
        source_width, source_height = source_size
        offset_x = image_center[0] - (render_width / 2)
        offset_y = image_center[1] - (render_height / 2)
        scale_x = render_width / max(source_width, 1)
        scale_y = render_height / max(source_height, 1)
        canvas_points: list[float] = []
        for x, y in quad:
            canvas_points.extend([offset_x + (x * scale_x), offset_y + (y * scale_y)])

        self.preview_canvas.create_polygon(*canvas_points, outline="#4ade80", width=2, fill="")

    def _draw_bbox_handles(self) -> None:
        quad = self._current_edit_quad()
        if quad is None or self.preview_transform is None:
            return

        for corner_index, point in enumerate(quad):
            canvas_x, canvas_y = source_to_canvas_point(self.preview_transform, point)
            is_active = self.active_drag_target == DragTarget(kind="bbox", corner_index=corner_index)
            radius = 5 if not is_active else 7
            self.preview_canvas.create_oval(
                canvas_x - radius,
                canvas_y - radius,
                canvas_x + radius,
                canvas_y + radius,
                fill="#38bdf8",
                outline="#082f49",
                width=1,
            )

    def _draw_active_roi_overlay(
        self,
        *,
        card_bbox: tuple[int, int, int, int],
        image_center: tuple[float, float],
        rendered_size: tuple[int, int],
        source_size: tuple[int, int],
    ) -> None:
        roi_entries = self._current_active_roi_entries()
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
            self.preview_canvas.create_rectangle(x1, y1, x2, y2, outline="#f59e0b", width=2)
            self.preview_canvas.create_text(x1 + 4, y1 + 4, text=label, fill="#f59e0b", anchor="nw")

    def _draw_roi_handles(self) -> None:
        if self.preview_transform is None:
            return

        for label, bbox in self._current_active_roi_entries():
            for corner_index, point in enumerate(bbox_corners(bbox)):
                canvas_x, canvas_y = source_to_canvas_point(self.preview_transform, point)
                is_active = self.active_drag_target == DragTarget(kind="roi", label=label, corner_index=corner_index)
                radius = 4 if not is_active else 6
                self.preview_canvas.create_oval(
                    canvas_x - radius,
                    canvas_y - radius,
                    canvas_x + radius,
                    canvas_y + radius,
                    fill="#f59e0b",
                    outline="#7c2d12",
                    width=1,
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

    def _on_preview_press(self, event) -> None:
        point = self._canvas_event_to_source_point(event.x, event.y)
        if point is None or self.state.current_image is None:
            return

        drag_target = self._nearest_drag_target(event.x, event.y)
        if drag_target is None:
            return
        self.active_drag_target = drag_target
        self._apply_drag_target_update(drag_target, point)

    def _on_preview_drag(self, event) -> None:
        point = self._canvas_event_to_source_point(event.x, event.y)
        if point is None or self.active_drag_target is None:
            return
        self._apply_drag_target_update(self.active_drag_target, point)

    def _on_preview_release(self, _event) -> None:
        self.active_drag_target = None

    def _on_preview_motion(self, event) -> None:
        point = self._canvas_event_to_source_point(event.x, event.y)
        if point is None:
            return
        x, y = point
        self.footer_var.set(
            f"Mouse: ({x}, {y}) in source image. Drag green corners for bbox or orange corners for ROI. Changes persist."
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

    def _canvas_event_to_source_point(self, x: int, y: int) -> tuple[int, int] | None:
        if self.preview_transform is None:
            return None
        return canvas_to_source_point(self.preview_transform, (x, y))

    def _current_edit_quad(self) -> Quad | None:
        fixture_path = selected_fixture(self.state)
        if fixture_path is None or self.state.recognition_result is None or self.state.recognition_result.bbox is None:
            return None
        if fixture_path in self.state.manual_quads:
            return self.state.manual_quads[fixture_path]
        return quad_from_bbox(self.state.recognition_result.bbox)

    def _current_active_roi_entries(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        if self.state.recognition_result is None or self.state.recognition_result.bbox is None:
            return []
        overrides = self.state.manual_roi_overrides.get(self.state.active_roi, {})
        return roi_group_bboxes(self.state.recognition_result.bbox, self.state.active_roi, overrides=overrides)

    def _apply_manual_corner_update(self, corner_index: int, point: tuple[int, int]) -> None:
        fixture_path = selected_fixture(self.state)
        quad = self._current_edit_quad()
        if fixture_path is None or quad is None or self.state.current_image is None:
            return

        updated_quad = update_quad_corner(
            quad,
            corner_index,
            point,
            frame_width=self.state.current_image.width,
            frame_height=self.state.current_image.height,
        )
        self.state.manual_quads[fixture_path] = updated_quad
        self._save_overrides()
        self.state.status_message = (
            f"Updated bbox corner {corner_index + 1} for {fixture_path.name}. Click Re-evaluate to apply."
        )
        self._refresh(run_recognition=False)

    def _apply_manual_roi_corner_update(self, label: str, corner_index: int, point: tuple[int, int]) -> None:
        if (
            self.state.current_image is None
            or self.state.recognition_result is None
            or self.state.recognition_result.bbox is None
        ):
            return

        roi_entries = dict(self._current_active_roi_entries())
        roi_bbox = roi_entries.get(label)
        if roi_bbox is None:
            return

        updated_bbox = update_bbox_corner_axis_aligned(
            roi_bbox,
            corner_index,
            point,
            frame_width=self.state.current_image.width,
            frame_height=self.state.current_image.height,
        )
        relative_roi = relative_roi_from_bboxes(self.state.recognition_result.bbox, updated_bbox)
        group_overrides = self.state.manual_roi_overrides.setdefault(self.state.active_roi, {})
        group_overrides[label] = relative_roi
        self._save_overrides()
        self.state.status_message = (
            f"Updated global ROI {label} corner {corner_index + 1} for {self.state.active_roi}. "
            "Click Re-evaluate to apply."
        )
        self._refresh(run_recognition=False)

    def _nearest_drag_target(self, canvas_x: int, canvas_y: int) -> DragTarget | None:
        if self.preview_transform is None:
            return None

        nearest_distance: float | None = None
        nearest_target: DragTarget | None = None

        for label, bbox in self._current_active_roi_entries():
            for corner_index, point in enumerate(bbox_corners(bbox)):
                px, py = source_to_canvas_point(self.preview_transform, point)
                distance = ((px - canvas_x) ** 2) + ((py - canvas_y) ** 2)
                if nearest_distance is None or distance < nearest_distance:
                    nearest_distance = distance
                    nearest_target = DragTarget(kind="roi", label=label, corner_index=corner_index)

        quad = self._current_edit_quad()
        if quad is not None:
            for corner_index, point in enumerate(quad):
                px, py = source_to_canvas_point(self.preview_transform, point)
                distance = ((px - canvas_x) ** 2) + ((py - canvas_y) ** 2)
                if nearest_distance is None or distance < nearest_distance:
                    nearest_distance = distance
                    nearest_target = DragTarget(kind="bbox", corner_index=corner_index)

        if nearest_distance is None or nearest_distance > (14 ** 2):
            return None
        return nearest_target

    def _apply_drag_target_update(self, target: DragTarget, point: tuple[int, int]) -> None:
        if target.kind == "bbox":
            self._apply_manual_corner_update(target.corner_index, point)
        elif target.kind == "roi" and target.label is not None:
            self._apply_manual_roi_corner_update(target.label, target.corner_index, point)

    def _build_recognition_input(self):
        fixture_path = selected_fixture(self.state)
        if fixture_path is None or self.state.current_image is None:
            return None

        manual_quad = self.state.manual_quads.get(fixture_path)
        manual_roi_overrides = self.state.manual_roi_overrides
        if manual_quad is None and not manual_roi_overrides:
            return fixture_path

        return EditableLoadedImage(
            path=self.state.current_image.path,
            image_format=self.state.current_image.image_format,
            width=self.state.current_image.width,
            height=self.state.current_image.height,
            layout_hint=self.state.current_image.layout_hint,
            content_hash=self.state.current_image.content_hash,
            image_array=self.state.current_image.image_array,
            card_quad=manual_quad,
            roi_overrides=manual_roi_overrides,
        )

    def _save_overrides(self) -> None:
        save_ui_overrides(
            self._overrides_path,
            manual_quads=self.state.manual_quads,
            manual_roi_overrides=self.state.manual_roi_overrides,
        )

    def _ensure_catalog(self) -> None:
        needs_refresh, age_days = catalog_refresh_needed(db_path=_default_catalog_path())
        if not needs_refresh:
            self.state.status_message = (
                f"Catalog ready ({age_days:.1f} days old)." if age_days is not None else "Catalog ready."
            )
            self._refresh_prehash_summary()
            return

        splash = OperationSplash(
            self.root,
            title="Updating Catalog",
            initial_message="Checking local card catalog...",
        )
        try:
            status = ensure_catalog_ready(
                db_path=_default_catalog_path(),
                source_json_path=_default_catalog_source_path(),
                max_age_days=7,
                progress_callback=splash.update,
            )
        except Exception as exc:
            self.state.status_message = f"Catalog refresh failed: {exc}"
            return
        finally:
            splash.close()

        if status.refreshed:
            self.state.status_message = (
                f"Catalog refreshed ({status.build_stats.card_count} cards)." if status.build_stats else "Catalog refreshed."
            )
        else:
            self.state.status_message = (
                f"Catalog reused ({status.age_days:.1f} days old)." if status.age_days is not None else "Catalog reused."
            )
        self._refresh_prehash_summary()

    def _prune_random_cache_if_needed(self) -> None:
        random_cache_dir = Path(_default_random_cache_dir()).resolve()
        active_fixtures_dir = Path(self.fixtures_dir).resolve()
        if active_fixtures_dir != random_cache_dir:
            return

        removed_cards = prune_random_card_cache(random_cache_dir)
        if removed_cards > 0:
            self.state.status_message = f"Pruned {removed_cards} old random card fixture(s) from cache."

    def _on_close(self) -> None:
        self._save_overrides()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

    def _refresh_prehash_summary(self) -> None:
        total_cards = _count_hashable_catalog_cards(_default_catalog_path())
        prehashed_cards = min(total_cards, _count_prehash_cache_entries())
        self.prehash_var.set(f"{prehashed_cards}/{total_cards} cards pre-hashed")


def _default_fixtures_dir() -> str:
    return str(Path("data") / "fixtures")


def _default_catalog_path() -> str:
    return str(Path("data") / "catalog" / "cards.sqlite3")


def _default_catalog_source_path() -> str:
    return str(Path("data") / "catalog" / "default-cards.json")


def _default_random_cache_dir() -> str:
    return str(Path("data") / "cache" / "random_cards")


def _default_overrides_path() -> str:
    return str(Path("data") / "cache" / "ui_overrides.json")


def _count_hashable_catalog_cards(catalog_path: str | Path) -> int:
    database = Path(catalog_path)
    if not database.exists():
        return 0
    try:
        with sqlite3.connect(database) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*)
                FROM cards
                WHERE image_uri IS NOT NULL
                  AND TRIM(image_uri) != ''
                """
            ).fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def _count_prehash_cache_entries() -> int:
    if not ART_MATCH_CACHE_DIR.exists():
        return 0
    return sum(1 for path in ART_MATCH_CACHE_DIR.glob("*.json") if path.name != "_cache_meta.json")


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
