from __future__ import annotations

import queue
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import argparse
import ctypes
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageGrab, ImageTk

try:
    from formula_ocr_app.recognizer import (
        PaddleFormulaRecognizer,
        PaddleOCRNotReadyError,
    )
    from formula_ocr_app.formula_formats import (
        clean_recognized_latex,
        export_formula_docx,
        latex_to_asciimath,
        latex_to_mathml,
        latex_to_typst,
        latex_to_word_linear,
        mathml_to_word_mathml,
    )
    from formula_ocr_app.word_clipboard import (
        FORMAT_HTML,
        FORMAT_MATHML,
        FORMAT_MATHML_PRESENTATION,
        FORMAT_OFFICE_OPEN_XML,
        copy_mathml_for_word_to_clipboard,
        tk_clipboard_text,
        windows_clipboard_formats,
        windows_clipboard_text,
    )
except ImportError:  # Allows `python formula_ocr_app/app.py`.
    from recognizer import PaddleFormulaRecognizer, PaddleOCRNotReadyError
    from formula_formats import (
        clean_recognized_latex,
        export_formula_docx,
        latex_to_asciimath,
        latex_to_mathml,
        latex_to_typst,
        latex_to_word_linear,
        mathml_to_word_mathml,
    )
    from word_clipboard import (
        FORMAT_HTML,
        FORMAT_MATHML,
        FORMAT_MATHML_PRESENTATION,
        FORMAT_OFFICE_OPEN_XML,
        copy_mathml_for_word_to_clipboard,
        tk_clipboard_text,
        windows_clipboard_formats,
        windows_clipboard_text,
    )


APP_ROOT = Path(__file__).resolve().parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _runtime_base() -> Path:
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return APP_ROOT.parent


def _resource_base() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return APP_ROOT.parent


WORKSPACE_ROOT = _runtime_base()
CACHE_DIR = (
    WORKSPACE_ROOT / "cache" if _is_frozen() else APP_ROOT / ".cache"
)
LOG_DIR = WORKSPACE_ROOT / "logs"
LOG_FILE = LOG_DIR / "formula_ocr.log"
DEFAULT_PADDLEOCR_REPO = _resource_base() / "PaddleOCR-main"
ICON_FILE = _resource_base() / "icon.png"
ICON_ICO_FILE = _resource_base() / "icon.ico"
MODEL_CHOICES = (
    (
        "等级3 · 轻量快速 · PP-FormulaNet_plus-S · 约248MB",
        "PP-FormulaNet_plus-S",
    ),
    (
        "等级2 · 准确率高 · PP-FormulaNet_plus-M · 约592MB",
        "PP-FormulaNet_plus-M",
    ),
    (
        "等级1 · 准确率最高 · PP-FormulaNet_plus-L · 约698MB",
        "PP-FormulaNet_plus-L",
    ),
)
MODEL_LABELS = tuple(label for label, _model_name in MODEL_CHOICES)
MODEL_LABEL_TO_NAME = dict(MODEL_CHOICES)
MODEL_NAME_TO_LABEL = {model_name: label for label, model_name in MODEL_CHOICES}
APP_BG = "#eef3f8"
PANEL_BG = "#ffffff"
SURFACE_SUBTLE = "#f7f9fc"
TEXT_PRIMARY = "#172033"
TEXT_SECONDARY = "#657086"
ACCENT = "#d4237a"
ACCENT_DARK = "#b71f69"
ACCENT_SOFT = "#fde7f2"
BORDER = "#dce4ef"


@dataclass(frozen=True)
class RecognizerSettings:
    model_name: str


def _rounded_rect(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
    **kwargs,
) -> int:
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        *,
        text: str,
        command,
        width: int = 112,
        height: int = 38,
        radius: int = 12,
        bg: str = PANEL_BG,
        fg: str = TEXT_PRIMARY,
        active_bg: str = SURFACE_SUBTLE,
        border: str = BORDER,
        selected_bg: str | None = None,
        selected_fg: str = "#ffffff",
        font: tuple[str, int, str] | tuple[str, int] = ("Microsoft YaHei UI", 10),
    ) -> None:
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent.cget("bg") if isinstance(parent, tk.Widget) else APP_BG,
            highlightthickness=0,
            bd=0,
        )
        self.command = command
        self.radius = radius
        self.normal_bg = bg
        self.active_bg = active_bg
        self.border = border
        self.fg = fg
        self.selected_bg = selected_bg
        self.selected_fg = selected_fg
        self.text = text
        self.font = font
        self.is_selected = False
        self.is_disabled = False
        self._draw()
        self.bind("<Enter>", lambda _event: self._draw(hover=True))
        self.bind("<Leave>", lambda _event: self._draw())
        self.bind("<Button-1>", self._click)

    def set_selected(self, selected: bool) -> None:
        self.is_selected = selected
        self._draw()

    def set_disabled(self, disabled: bool) -> None:
        self.is_disabled = disabled
        self._draw()

    def _click(self, _event: tk.Event) -> None:
        if not self.is_disabled and self.command:
            self.command()

    def _draw(self, hover: bool = False) -> None:
        self.delete("all")
        width = max(2, int(self.winfo_reqwidth()))
        height = max(2, int(self.winfo_reqheight()))
        selected = self.is_selected and self.selected_bg is not None
        fill = self.selected_bg if selected else (self.active_bg if hover else self.normal_bg)
        outline = self.selected_bg if selected else self.border
        text_color = self.selected_fg if selected else self.fg
        if self.is_disabled:
            fill = "#e4eaf3"
            outline = "#d5deeb"
            text_color = "#9aa5b5"
        _rounded_rect(
            self,
            1,
            1,
            width - 1,
            height - 1,
            self.radius,
            fill=fill,
            outline=outline,
            width=1,
        )
        self.create_text(
            width // 2,
            height // 2,
            text=self.text,
            fill=text_color,
            font=self.font,
        )


class RoundedPanel(tk.Canvas):
    def __init__(self, parent: tk.Widget, *, radius: int = 18, padding: int = 16) -> None:
        super().__init__(
            parent,
            bg=APP_BG,
            highlightthickness=0,
            bd=0,
        )
        self.radius = radius
        self.padding = padding
        self.content = tk.Frame(self, bg=PANEL_BG)
        self.window_id = self.create_window(
            padding,
            padding,
            anchor="nw",
            window=self.content,
        )
        self.bind("<Configure>", self._resize)

    def _resize(self, event: tk.Event) -> None:
        self.delete("panel")
        width = max(2, int(event.width))
        height = max(2, int(event.height))
        _rounded_rect(
            self,
            2,
            2,
            width - 2,
            height - 2,
            self.radius,
            fill=PANEL_BG,
            outline=BORDER,
            width=1,
            tags="panel",
        )
        self.tag_lower("panel")
        inner_width = max(1, width - self.padding * 2)
        inner_height = max(1, height - self.padding * 2)
        self.coords(self.window_id, self.padding, self.padding)
        self.itemconfigure(self.window_id, width=inner_width, height=inner_height)


class SlimScrollbar(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        *,
        command,
        width: int = 12,
        bg: str = PANEL_BG,
        track: str = "#edf2f8",
        thumb: str = "#aeb7c4",
        active_thumb: str = "#8793a3",
    ) -> None:
        super().__init__(
            parent,
            width=width,
            bg=bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.command = command
        self.track = track
        self.thumb = thumb
        self.active_thumb = active_thumb
        self.first = 0.0
        self.last = 1.0
        self.drag_start_y = 0
        self.drag_start_first = 0.0
        self.dragging = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda _event: self._draw(hover=True))
        self.bind("<Leave>", lambda _event: self._draw())

    def set(self, first: float | str, last: float | str) -> None:
        try:
            first_float = float(first)
            last_float = float(last)
        except (TypeError, ValueError):
            return
        self.first = min(max(first_float, 0.0), 1.0)
        self.last = min(max(last_float, self.first), 1.0)
        self._draw()

    def _thumb_bounds(self) -> tuple[int, int]:
        height = max(1, self.winfo_height())
        visible = max(0.0, min(1.0, self.last - self.first))
        if visible >= 0.999:
            return 2, max(3, height - 2)
        thumb_height = min(height - 4, max(34, int(height * visible)))
        movable = max(1, height - 4 - thumb_height)
        max_first = max(0.001, 1.0 - visible)
        top = 2 + int((self.first / max_first) * movable)
        return top, top + thumb_height

    def _draw(self, hover: bool = False) -> None:
        self.delete("all")
        width = max(8, self.winfo_width())
        height = max(8, self.winfo_height())
        bar_width = 5
        x1 = (width - bar_width) // 2
        x2 = x1 + bar_width
        _rounded_rect(
            self,
            x1,
            2,
            x2,
            height - 2,
            3,
            fill=self.track,
            outline=self.track,
            width=0,
        )
        top, bottom = self._thumb_bounds()
        fill = self.active_thumb if hover or self.dragging else self.thumb
        _rounded_rect(
            self,
            x1,
            top,
            x2,
            bottom,
            3,
            fill=fill,
            outline=fill,
            width=0,
        )

    def _on_press(self, event: tk.Event) -> None:
        top, bottom = self._thumb_bounds()
        if top <= event.y <= bottom:
            self.dragging = True
            self.drag_start_y = int(event.y)
            self.drag_start_first = self.first
        else:
            self._move_thumb_to(int(event.y))
            self.dragging = True
            self.drag_start_y = int(event.y)
            self.drag_start_first = self.first
        self._draw(hover=True)

    def _on_drag(self, event: tk.Event) -> None:
        if not self.dragging:
            return
        height = max(1, self.winfo_height())
        visible = max(0.0, min(1.0, self.last - self.first))
        top, bottom = self._thumb_bounds()
        movable = max(1, height - 4 - (bottom - top))
        max_first = max(0.0, 1.0 - visible)
        delta = (int(event.y) - self.drag_start_y) / movable * max_first
        self._moveto(self.drag_start_first + delta)

    def _on_release(self, _event: tk.Event) -> None:
        self.dragging = False
        self._draw()

    def _move_thumb_to(self, y: int) -> None:
        height = max(1, self.winfo_height())
        top, bottom = self._thumb_bounds()
        thumb_height = bottom - top
        movable = max(1, height - 4 - thumb_height)
        visible = max(0.0, min(1.0, self.last - self.first))
        max_first = max(0.0, 1.0 - visible)
        fraction = ((y - 2 - thumb_height / 2) / movable) * max_first
        self._moveto(fraction)

    def _moveto(self, fraction: float) -> None:
        visible = max(0.0, min(1.0, self.last - self.first))
        max_first = max(0.0, 1.0 - visible)
        fraction = min(max(fraction, 0.0), max_first)
        self.command("moveto", fraction)


class FormulaOCRApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("公式识别助手")
        self.geometry("1160x740")
        self.minsize(960, 620)
        self.configure(bg=APP_BG)

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.current_image: Image.Image | None = None
        self.current_image_path: Path | None = None
        self.preview_photo: ImageTk.PhotoImage | None = None
        self.window_icon: tk.PhotoImage | None = None
        self.recognizer: PaddleFormulaRecognizer | None = None
        self.recognizer_settings: RecognizerSettings | None = None
        self.worker_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.mathml_preview_queue: queue.Queue[tuple[int, str, str]] = queue.Queue()
        self.is_busy = False
        self.mathml_update_after_id: str | None = None
        self.worker_poll_after_id: str | None = None
        self.mathml_preview_poll_after_id: str | None = None
        self.mathml_render_token = 0
        self.mathml_preview_photo: ImageTk.PhotoImage | None = None
        self.busy_started_at: float | None = None
        self.busy_status_after_id: str | None = None
        self.is_destroying = False

        self._configure_styles()
        self._set_window_icon()
        self._build_ui()
        self._bind_shortcuts()
        self._schedule_worker_poll()
        self._schedule_mathml_preview_poll()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("App.TFrame", background=APP_BG)
        style.configure("Panel.TFrame", background=PANEL_BG)
        style.configure("Toolbar.TFrame", background=PANEL_BG)
        style.configure(
            "Title.TLabel",
            background=APP_BG,
            foreground=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=APP_BG,
            foreground=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "PanelTitle.TLabel",
            background=PANEL_BG,
            foreground=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=PANEL_BG,
            foreground=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(12, 7))
        style.configure(
            "Accent.TButton",
            foreground="#ffffff",
            background=ACCENT,
            bordercolor=ACCENT,
            focusthickness=0,
            padding=(18, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("disabled", "#9fb7eb")],
            foreground=[("disabled", "#f4f7ff")],
        )
        style.configure(
            "Status.Horizontal.TProgressbar",
            troughcolor="#dfe7f2",
            background=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            bordercolor=APP_BG,
            thickness=6,
        )

    def _set_window_icon(self) -> None:
        try:
            if ICON_ICO_FILE.exists():
                self.iconbitmap(default=str(ICON_ICO_FILE))
            if ICON_FILE.exists():
                self.window_icon = tk.PhotoImage(file=str(ICON_FILE))
                self.iconphoto(True, self.window_icon)
        except tk.TclError:
            write_log(f"Unable to load window icon: {ICON_ICO_FILE} / {ICON_FILE}")

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=APP_BG)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        header.configure(padx=22, pady=18)

        title_group = tk.Frame(header, bg=APP_BG)
        title_group.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_group,
            text="公式识别助手",
            bg=APP_BG,
            fg=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 20, "bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            title_group,
            text="图片公式转 LaTeX，识别后自动复制",
            bg=APP_BG,
            fg=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        model_bar = tk.Frame(header, bg=APP_BG)
        model_bar.grid(row=0, column=1, sticky="e")
        self.model_var = tk.StringVar(value=MODEL_LABELS[0])
        self.model_buttons: list[tuple[str, RoundedButton]] = []
        model_button_data = (
            ("等级3 快速", "PP-FormulaNet_plus-S"),
            ("等级2 高准", "PP-FormulaNet_plus-M"),
            ("等级1 最高", "PP-FormulaNet_plus-L"),
        )
        for index, (button_text, model_name) in enumerate(model_button_data):
            button = RoundedButton(
                model_bar,
                text=button_text,
                command=lambda name=model_name: self._select_model(name),
                width=100,
                height=38,
                radius=13,
                bg="#ffffff",
                active_bg=ACCENT_SOFT,
                selected_bg=ACCENT,
                border=BORDER,
                font=("Microsoft YaHei UI", 10, "bold"),
            )
            button.pack(side=tk.LEFT, padx=(0 if index == 0 else 6, 0))
            self.model_buttons.append((model_name, button))
        self._sync_model_buttons()
        self.recognize_button = RoundedButton(
            model_bar,
            text="识别",
            command=self.recognize_image,
            width=92,
            height=38,
            radius=13,
            bg=ACCENT,
            active_bg=ACCENT_DARK,
            fg="#ffffff",
            border=ACCENT,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.recognize_button.pack(side=tk.LEFT, padx=(10, 0))

        content = tk.Frame(self, bg=APP_BG)
        content.grid(row=1, column=0, sticky="nsew", padx=22, pady=(0, 14))
        content.columnconfigure(0, weight=3)
        content.columnconfigure(1, weight=2)
        content.rowconfigure(0, weight=1)

        left_panel = RoundedPanel(content, radius=22, padding=18)
        right_panel = RoundedPanel(content, radius=22, padding=18)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        left = left_panel.content
        right = right_panel.content

        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        image_header = tk.Frame(left, bg=PANEL_BG)
        image_header.grid(row=0, column=0, sticky="ew")
        image_header.columnconfigure(0, weight=1)
        tk.Label(
            image_header,
            text="图片",
            bg=PANEL_BG,
            fg=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            image_header,
            text="打开、粘贴或截图",
            bg=PANEL_BG,
            fg=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        image_toolbar = tk.Frame(left, bg=PANEL_BG)
        image_toolbar.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        RoundedButton(
            image_toolbar,
            text="打开图片",
            command=self.open_image,
            width=112,
        ).pack(
            side=tk.LEFT
        )
        RoundedButton(
            image_toolbar,
            text="粘贴图片",
            command=self.paste_image,
            width=112,
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        RoundedButton(
            image_toolbar,
            text="截图",
            command=self.capture_screen,
            width=84,
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        preview_frame = tk.Frame(
            left,
            bg=SURFACE_SUBTLE,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        preview_frame.grid(row=2, column=0, sticky="nsew")
        preview_frame.rowconfigure(0, weight=1)
        preview_frame.columnconfigure(0, weight=1)
        self.preview_label = tk.Label(
            preview_frame,
            text="暂无图片",
            anchor=tk.CENTER,
            bg=SURFACE_SUBTLE,
            fg=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 12),
        )
        self.preview_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        output_header = tk.Frame(right, bg=PANEL_BG)
        output_header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        output_header.columnconfigure(0, weight=1)
        tk.Label(
            output_header,
            text="识别结果",
            bg=PANEL_BG,
            fg=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        output_actions = tk.Frame(output_header, bg=PANEL_BG)
        output_actions.grid(row=0, column=1, sticky="e")
        RoundedButton(
            output_actions,
            text="复制LaTeX",
            command=self.copy_latex,
            width=104,
            height=34,
            radius=12,
        ).pack(
            side=tk.LEFT
        )
        RoundedButton(
            output_actions,
            text="复制MathML",
            command=self.copy_mathml,
            width=104,
            height=34,
            radius=12,
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.format_menu = tk.Menu(
            self,
            tearoff=0,
            bg="#ffffff",
            fg=TEXT_PRIMARY,
            activebackground=ACCENT_SOFT,
            activeforeground=TEXT_PRIMARY,
            relief=tk.FLAT,
            borderwidth=1,
            font=("Microsoft YaHei UI", 10),
        )
        self.format_menu.add_command(
            label="复制MathML(Word)",
            command=lambda: self.copy_format("mathml"),
        )
        self.format_menu.add_command(
            label="复制AsciiMath",
            command=lambda: self.copy_format("asciimath"),
        )
        self.format_menu.add_command(
            label="复制Typst",
            command=lambda: self.copy_format("typst"),
        )
        self.format_menu.add_separator()
        self.format_menu.add_command(
            label="导出Docx(Word/WPS)",
            command=self.export_docx,
        )
        self.format_button = RoundedButton(
            output_actions,
            text="更多格式 ▾",
            command=self.show_format_menu,
            width=112,
            height=34,
            radius=12,
            bg=ACCENT_SOFT,
            active_bg="#fbd3e8",
            fg=ACCENT_DARK,
            border="#f6bfd9",
        )
        self.format_button.pack(side=tk.LEFT, padx=(8, 0))
        RoundedButton(
            output_actions,
            text="清空",
            command=self.clear_output,
            width=72,
            height=34,
            radius=12,
        ).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        results_frame = tk.Frame(right, bg=PANEL_BG)
        results_frame.grid(row=1, column=0, sticky="nsew")
        results_frame.rowconfigure(0, weight=1, uniform="result_sections")
        results_frame.rowconfigure(1, weight=1, uniform="result_sections")
        results_frame.columnconfigure(0, weight=1)

        latex_section = tk.Frame(results_frame, bg=PANEL_BG)
        latex_section.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        latex_section.rowconfigure(1, weight=1)
        latex_section.columnconfigure(0, weight=1)
        latex_header = tk.Frame(latex_section, bg=PANEL_BG)
        latex_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        latex_header.columnconfigure(0, weight=1)
        tk.Label(
            latex_header,
            text="LaTeX 结果",
            bg=PANEL_BG,
            fg=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            latex_header,
            text="可编辑",
            bg=PANEL_BG,
            fg=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=1, sticky="e")

        latex_frame = tk.Frame(
            latex_section,
            bg=PANEL_BG,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        latex_frame.grid(row=1, column=0, sticky="nsew")
        latex_frame.rowconfigure(0, weight=1)
        latex_frame.columnconfigure(0, weight=1)

        self.output_text = tk.Text(
            latex_frame,
            wrap=tk.WORD,
            font=("Consolas", 12),
            undo=True,
            height=1,
            bg="#fbfdff",
            fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief=tk.FLAT,
            borderwidth=0,
            padx=12,
            pady=12,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        self.latex_scrollbar = SlimScrollbar(
            latex_frame, command=self.output_text.yview
        )
        self.latex_scrollbar.grid(row=0, column=1, sticky="ns", padx=(2, 4), pady=8)
        self.output_text.configure(yscrollcommand=self.latex_scrollbar.set)

        mathml_section = tk.Frame(results_frame, bg=PANEL_BG)
        mathml_section.grid(row=1, column=0, sticky="nsew")
        mathml_section.rowconfigure(1, weight=1)
        mathml_section.columnconfigure(0, weight=1)
        mathml_header = tk.Frame(mathml_section, bg=PANEL_BG)
        mathml_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        mathml_header.columnconfigure(0, weight=1)
        tk.Label(
            mathml_header,
            text="MathML 公式展示",
            bg=PANEL_BG,
            fg=TEXT_PRIMARY,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w")
        RoundedButton(
            mathml_header,
            text="刷新预览",
            command=self.refresh_mathml_preview,
            width=92,
            height=30,
            radius=11,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        mathml_frame = tk.Frame(
            mathml_section,
            bg="#fbfdff",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        mathml_frame.grid(row=1, column=0, sticky="nsew")
        mathml_frame.rowconfigure(0, weight=1)
        mathml_frame.columnconfigure(0, weight=1)

        self.mathml_preview_label = tk.Label(
            mathml_frame,
            text="暂无公式预览",
            anchor=tk.CENTER,
            justify=tk.CENTER,
            bg="#fbfdff",
            fg=TEXT_SECONDARY,
            font=("Cambria Math", 16),
        )
        self.mathml_preview_label.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        self.output_text.bind("<<Modified>>", self._on_latex_modified)
        self.output_text.edit_modified(False)

        status_frame = tk.Frame(self, bg=APP_BG)
        status_frame.grid(row=2, column=0, sticky="ew", padx=22, pady=(0, 14))
        status_frame.columnconfigure(0, weight=1)

        self.status_var = tk.StringVar(value="就绪")
        status_label = tk.Label(
            status_frame,
            textvariable=self.status_var,
            anchor=tk.W,
            bg=APP_BG,
            fg=TEXT_SECONDARY,
            font=("Microsoft YaHei UI", 9),
        )
        status_label.grid(row=0, column=0, sticky="ew")
        self.busy_progress = ttk.Progressbar(
            status_frame,
            mode="indeterminate",
            length=180,
            style="Status.Horizontal.TProgressbar",
        )
        self.busy_progress.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.busy_progress.grid_remove()

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-o>", lambda _event: self.open_image())
        self.bind("<Control-v>", lambda _event: self.paste_image())
        self.bind("<Control-Return>", lambda _event: self.recognize_image())
        self.bind("<Control-c>", self._copy_shortcut)

    def _copy_shortcut(self, event: tk.Event) -> str | None:
        if self.focus_get() is self.output_text:
            return None
        self.copy_latex()
        return "break"

    def _select_model(self, model_name: str) -> None:
        label = MODEL_NAME_TO_LABEL[model_name]
        if self.model_var.get() == label:
            return
        self.model_var.set(label)
        self._on_model_changed()

    def _on_model_changed(self, _event: tk.Event | None = None) -> None:
        self._reset_recognizer()
        self._sync_model_buttons()
        self.status_var.set(f"已选择 {self.model_var.get()}")

    def _sync_model_buttons(self) -> None:
        current_model = MODEL_LABEL_TO_NAME.get(
            self.model_var.get().strip(), "PP-FormulaNet_plus-S"
        )
        for model_name, button in self.model_buttons:
            button.set_selected(model_name == current_model)

    def open_image(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择公式图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff"),
                ("所有文件", "*.*"),
            ],
        )
        if not file_path:
            return
        try:
            image = Image.open(file_path)
            self._set_image(image)
            self.status_var.set(f"已加载图片：{file_path}")
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def paste_image(self) -> None:
        try:
            data = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showerror("粘贴失败", str(exc))
            return

        if isinstance(data, Image.Image):
            self._set_image(data)
            self.status_var.set("已从剪贴板加载图片")
            return

        if isinstance(data, list) and data:
            try:
                image = Image.open(data[0])
                self._set_image(image)
                self.status_var.set(f"已从剪贴板文件加载图片：{data[0]}")
                return
            except Exception as exc:
                messagebox.showerror("粘贴失败", str(exc))
                return

        messagebox.showinfo("没有图片", "剪贴板里没有可用的图片。")

    def capture_screen(self) -> None:
        self.withdraw()
        self.after(180, self._start_capture_overlay)

    def _start_capture_overlay(self) -> None:
        selector = ScreenshotSelector(self, self._on_screen_captured)
        selector.start()

    def _on_screen_captured(self, image: Image.Image | None) -> None:
        self.deiconify()
        self.lift()
        if image is None:
            self.status_var.set("截图已取消")
            return
        self._set_image(image)
        self.status_var.set("已截取图片")

    def recognize_image(self) -> None:
        if self.is_busy:
            return
        if self.current_image_path is None:
            messagebox.showinfo("没有图片", "请先打开、粘贴或截图一张公式图片。")
            return

        settings = self._current_settings()
        self._set_busy(True)
        thread = threading.Thread(
            target=self._recognize_worker,
            args=(self.current_image_path, settings),
            daemon=True,
        )
        thread.start()

    def copy_latex(self) -> None:
        latex = self._current_latex()
        if not latex:
            self.status_var.set("没有可复制的 LaTeX")
            return
        self._copy_text(latex)
        self.status_var.set("LaTeX 已复制到剪贴板")

    def copy_mathml(self) -> None:
        self.copy_format("mathml")

    def show_format_menu(self) -> None:
        x = self.format_button.winfo_rootx()
        y = self.format_button.winfo_rooty() + self.format_button.winfo_height() + 4
        try:
            self.format_menu.tk_popup(x, y)
        finally:
            self.format_menu.grab_release()

    def copy_format(self, fmt: str) -> None:
        latex = self._current_latex()
        if not latex:
            self.status_var.set("没有可转换的 LaTeX")
            return
        try:
            if fmt == "mathml":
                mathml = latex_to_mathml(latex)
                value = mathml_to_word_mathml(mathml)
                label = "MathML(Word)"
                rich_copied = self._copy_mathml_for_word(mathml, plain_text=value)
                if rich_copied:
                    self.status_var.set(f"{label} 已复制到剪贴板")
                else:
                    self.status_var.set(f"{label} 富格式复制失败，已复制纯文本")
                return
            elif fmt == "asciimath":
                value = latex_to_asciimath(latex)
                label = "AsciiMath"
            elif fmt == "typst":
                value = latex_to_typst(latex)
                label = "Typst"
            else:
                raise ValueError(f"Unknown format: {fmt}")
        except Exception as exc:
            messagebox.showerror("转换失败", str(exc))
            self.status_var.set("转换失败")
            return
        self._copy_text(value)
        self.status_var.set(f"{label} 已复制到剪贴板")

    def export_docx(self) -> None:
        latex = self._current_latex()
        if not latex:
            self.status_var.set("没有可导出的 LaTeX")
            return
        file_path = filedialog.asksaveasfilename(
            title="导出 Docx",
            defaultextension=".docx",
            initialfile="formula_result.docx",
            filetypes=[("Word 文档", "*.docx"), ("所有文件", "*.*")],
        )
        if not file_path:
            return
        try:
            mathml = latex_to_mathml(latex)
            asciimath = latex_to_asciimath(latex)
            typst = latex_to_typst(latex)
            word_linear = latex_to_word_linear(latex)
            export_formula_docx(
                file_path,
                latex=latex,
                mathml=mathml,
                asciimath=asciimath,
                typst=typst,
                word_linear=word_linear,
                image_path=self.current_image_path,
            )
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))
            self.status_var.set("导出失败")
            return
        self.status_var.set(f"Docx 已导出：{file_path}")

    def _current_latex(self) -> str:
        return self.output_text.get("1.0", tk.END).strip()

    def _copy_text(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def _copy_formula_result(self, latex: str) -> bool:
        try:
            mathml = latex_to_mathml(latex)
        except Exception as exc:
            write_log(f"Failed to prepare Word MathML clipboard: {exc}")
            self._copy_text(latex)
            return False
        return self._copy_mathml_for_word(mathml, plain_text=latex)

    def _copy_mathml_for_word(self, mathml: str, *, plain_text: str) -> bool:
        if copy_mathml_for_word_to_clipboard(
            mathml,
            plain_text=plain_text,
            clipboard_widget=self,
            owner_hwnd=self.winfo_id(),
        ):
            self.update_idletasks()
            return True
        self._copy_text(plain_text)
        return False

    def refresh_mathml_preview(self) -> None:
        if self.mathml_update_after_id is not None:
            self.after_cancel(self.mathml_update_after_id)
            self.mathml_update_after_id = None
        self._update_mathml_preview()
        self.status_var.set("MathML 预览已刷新")

    def _on_latex_modified(self, _event: tk.Event) -> None:
        if not self.output_text.edit_modified():
            return
        self.output_text.edit_modified(False)
        self._schedule_mathml_preview_update()

    def _schedule_mathml_preview_update(self) -> None:
        if self.mathml_update_after_id is not None:
            self.after_cancel(self.mathml_update_after_id)
        self.mathml_update_after_id = self.after(450, self._update_mathml_preview)

    def _update_mathml_preview(self) -> None:
        self.mathml_update_after_id = None
        latex = self._current_latex()
        if not latex:
            self._set_mathml_preview_text("暂无公式预览")
            return
        try:
            mathml = latex_to_mathml(latex)
        except Exception as exc:
            write_log(f"Failed to convert LaTeX to MathML: {exc}")
            self._set_mathml_preview_text("MathML 转换失败")
            return
        self.mathml_render_token += 1
        token = self.mathml_render_token
        self._set_mathml_preview_text("正在渲染 MathML...")
        thread = threading.Thread(
            target=self._render_mathml_preview_worker,
            args=(token, latex, mathml),
            daemon=True,
        )
        thread.start()

    def _set_mathml_preview_text(self, text: str) -> None:
        self.mathml_preview_photo = None
        self.mathml_preview_label.configure(image="", text=text, fg=TEXT_SECONDARY)

    def clear_output(self) -> None:
        if self.mathml_update_after_id is not None:
            self.after_cancel(self.mathml_update_after_id)
            self.mathml_update_after_id = None
        self.output_text.delete("1.0", tk.END)
        self.mathml_render_token += 1
        self._set_mathml_preview_text("暂无公式预览")
        self.status_var.set("结果已清空")

    def _recognize_worker(
        self, image_path: Path, settings: RecognizerSettings
    ) -> None:
        start = time.time()
        try:
            recognizer = self._get_recognizer(settings)
            formula = recognizer.predict(image_path)
            elapsed = time.time() - start
            self.worker_queue.put(("success", f"{formula}\n@@TIME@@{elapsed:.2f}"))
        except PaddleOCRNotReadyError as exc:
            details = "".join(traceback.format_exception(exc)).strip()
            self.worker_queue.put(("error", f"{exc}\n\n{details}"))
        except Exception as exc:
            details = "".join(traceback.format_exception(exc)).strip()
            self.worker_queue.put(("error", f"{exc}\n\n{details}"))

    def _schedule_worker_poll(self) -> None:
        if self.is_destroying:
            return
        self.worker_poll_after_id = self.after(100, self._poll_worker_queue)

    def _poll_worker_queue(self) -> None:
        self.worker_poll_after_id = None
        if self.is_destroying:
            return
        try:
            kind, payload = self.worker_queue.get_nowait()
        except queue.Empty:
            self._schedule_worker_poll()
            return

        self._set_busy(False)
        if kind == "success":
            formula, _, marker = payload.partition("\n@@TIME@@")
            formula = clean_recognized_latex(formula)
            self.output_text.delete("1.0", tk.END)
            self.output_text.insert("1.0", formula)
            self._update_mathml_preview()
            rich_copied = self._copy_formula_result(formula)
            if marker:
                if rich_copied:
                    self.status_var.set(f"识别完成，用时 {marker} 秒；Word 格式已复制")
                else:
                    self.status_var.set(
                        f"识别完成，用时 {marker} 秒；已复制 LaTeX 纯文本"
                    )
            else:
                if rich_copied:
                    self.status_var.set("识别完成；Word 格式已复制")
                else:
                    self.status_var.set("识别完成；已复制 LaTeX 纯文本")
        else:
            messagebox.showerror("识别失败", payload)
            self.status_var.set("识别失败")

        self._schedule_worker_poll()

    def _schedule_mathml_preview_poll(self) -> None:
        if self.is_destroying:
            return
        self.mathml_preview_poll_after_id = self.after(
            120,
            self._poll_mathml_preview_queue,
        )

    def _poll_mathml_preview_queue(self) -> None:
        self.mathml_preview_poll_after_id = None
        if self.is_destroying:
            return
        try:
            while True:
                token, kind, payload = self.mathml_preview_queue.get_nowait()
                if token != self.mathml_render_token:
                    continue
                if kind == "image":
                    self._set_mathml_preview_image(Path(payload))
                elif kind == "text":
                    self._set_mathml_preview_text(payload)
                else:
                    self._set_mathml_preview_text("MathML 预览不可用")
                    write_log(f"MathML preview render failed: {payload}")
        except queue.Empty:
            pass
        self._schedule_mathml_preview_poll()

    def _render_mathml_preview_worker(
        self,
        token: int,
        latex: str,
        mathml: str,
    ) -> None:
        try:
            image_path = self._render_mathml_to_png(token, mathml)
        except Exception as exc:
            fallback = latex_to_word_linear(latex) or latex
            self.mathml_preview_queue.put((token, "text", fallback))
            write_log(f"MathML browser render fallback: {exc}")
            return
        self.mathml_preview_queue.put((token, "image", str(image_path)))

    def _render_mathml_to_png(self, token: int, mathml: str) -> Path:
        browser = self._find_browser_executable()
        if browser is None:
            raise RuntimeError("Edge/Chrome was not found for MathML preview.")

        render_dir = CACHE_DIR / "mathml_preview"
        render_dir.mkdir(parents=True, exist_ok=True)
        html_path = render_dir / f"preview_{token}.html"
        png_path = render_dir / f"preview_{token}.png"
        profile_dir = render_dir / f"profile_{token}"
        try:
            png_path.unlink()
        except FileNotFoundError:
            pass
        html_path.write_text(self._mathml_preview_html(mathml), encoding="utf-8")

        args = [
            str(browser),
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--disable-extensions",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--default-background-color=fffbfdff",
            "--window-size=2200,620",
            f"--screenshot={png_path}",
            html_path.as_uri(),
        ]
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
            startupinfo.wShowWindow = 0
        process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
        )
        try:
            self._wait_for_rendered_png(png_path, timeout=10.0)
            returncode = process.poll()
            if returncode not in (None, 0) and not png_path.exists():
                raise RuntimeError(f"Browser screenshot failed: {returncode}")
        finally:
            self._stop_preview_browser(process)
            shutil.rmtree(profile_dir, ignore_errors=True)

        self._trim_mathml_preview_image(png_path)
        return png_path

    def _wait_for_rendered_png(self, image_path: Path, *, timeout: float = 3.0) -> None:
        deadline = time.time() + timeout
        last_size = -1
        stable_count = 0
        while time.time() < deadline:
            if image_path.exists():
                size = image_path.stat().st_size
                if size > 0 and size == last_size:
                    try:
                        with Image.open(image_path) as image:
                            image.load()
                        stable_count += 1
                        if stable_count >= 2:
                            return
                    except Exception:
                        stable_count = 0
                else:
                    stable_count = 0
                last_size = size
            time.sleep(0.08)
        raise RuntimeError("Browser screenshot file was not ready.")

    def _stop_preview_browser(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _mathml_preview_html(self, mathml: str) -> str:
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
html, body {{
  margin: 0;
  width: 2200px;
  height: 620px;
  background: #fbfdff;
  overflow: hidden;
}}
body {{
  display: flex;
  align-items: center;
  justify-content: center;
  color: #172033;
  font-family: "Cambria Math", "Times New Roman", serif;
}}
.formula {{
  box-sizing: border-box;
  width: 2100px;
  min-height: 500px;
  padding: 44px 56px;
  display: flex;
  align-items: center;
  justify-content: center;
}}
math {{
  font-size: 42px;
  line-height: 1.45;
}}
mtd {{
  padding: 3px 8px;
}}
</style>
</head>
<body><div class="formula">{mathml}</div></body>
</html>
"""

    def _trim_mathml_preview_image(self, image_path: Path) -> None:
        with Image.open(image_path) as image:
            image = image.convert("RGB")
            background = Image.new("RGB", image.size, "#fbfdff")
            diff = ImageChops.difference(image, background)
            bbox = diff.getbbox()
            if bbox is None:
                image.save(image_path)
                return
            left, top, right, bottom = bbox
            margin = 28
            left = max(0, left - margin)
            top = max(0, top - margin)
            right = min(image.width, right + margin)
            bottom = min(image.height, bottom + margin)
            cropped = image.crop((left, top, right, bottom))
            cropped.save(image_path)

    def _set_mathml_preview_image(self, image_path: Path) -> None:
        try:
            with Image.open(image_path) as image:
                image = image.convert("RGBA")
                self.update_idletasks()
                max_width = max(220, self.mathml_preview_label.winfo_width() - 24)
                max_height = max(160, self.mathml_preview_label.winfo_height() - 24)
                image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
                self.mathml_preview_photo = ImageTk.PhotoImage(image)
        except Exception as exc:
            self._set_mathml_preview_text("MathML 预览加载失败")
            write_log(f"Failed to load MathML preview image: {exc}")
            return
        self.mathml_preview_label.configure(
            image=self.mathml_preview_photo,
            text="",
            bg="#fbfdff",
        )

    def _find_browser_executable(self) -> Path | None:
        candidates = [
            os.environ.get("FORMULA_OCR_BROWSER", ""),
            str(Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            str(Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            str(Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        ]
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                return path
        return None

    def _set_busy(self, busy: bool) -> None:
        self.is_busy = busy
        self.recognize_button.set_disabled(busy)
        if busy:
            self._start_busy_feedback()
        else:
            self._stop_busy_feedback()

    def _start_busy_feedback(self) -> None:
        self.busy_started_at = time.time()
        self.busy_progress.grid()
        self.busy_progress.start(12)
        self._update_busy_status()

    def _stop_busy_feedback(self) -> None:
        if self.busy_status_after_id is not None:
            try:
                self.after_cancel(self.busy_status_after_id)
            except tk.TclError:
                pass
            self.busy_status_after_id = None
        self.busy_started_at = None
        self.busy_progress.stop()
        self.busy_progress.grid_remove()

    def _update_busy_status(self) -> None:
        if not self.is_busy:
            return
        started_at = self.busy_started_at or time.time()
        elapsed = time.time() - started_at
        self.status_var.set(f"正在加载模型/识别公式... {elapsed:.1f}s")
        self.busy_status_after_id = self.after(300, self._update_busy_status)

    def _get_recognizer(
        self, settings: RecognizerSettings
    ) -> PaddleFormulaRecognizer:
        if self.recognizer is not None and self.recognizer_settings == settings:
            return self.recognizer
        self._reset_recognizer()
        self.recognizer_settings = settings
        self.recognizer = PaddleFormulaRecognizer(
            paddleocr_repo=DEFAULT_PADDLEOCR_REPO,
            model_name=settings.model_name,
            device="cpu",
        )
        return self.recognizer

    def _reset_recognizer(self) -> None:
        if self.recognizer is not None:
            self.recognizer.close()
        self.recognizer = None
        self.recognizer_settings = None

    def _current_settings(self) -> RecognizerSettings:
        model_label = self.model_var.get().strip()
        return RecognizerSettings(
            model_name=MODEL_LABEL_TO_NAME.get(model_label, model_label),
        )

    def _set_image(self, image: Image.Image) -> None:
        image = image.convert("RGB")
        self.current_image = image
        self.current_image_path = CACHE_DIR / "current_formula.png"
        image.save(self.current_image_path)
        self._update_preview()

    def _update_preview(self) -> None:
        if self.current_image is None:
            return
        self.update_idletasks()
        max_width = max(200, self.preview_label.winfo_width() - 24)
        max_height = max(160, self.preview_label.winfo_height() - 24)
        preview = self.current_image.copy()
        preview.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.preview_photo, text="", bg=SURFACE_SUBTLE)

    def destroy(self) -> None:
        self.is_destroying = True
        if self.mathml_update_after_id is not None:
            try:
                self.after_cancel(self.mathml_update_after_id)
            except tk.TclError:
                pass
            self.mathml_update_after_id = None
        if self.worker_poll_after_id is not None:
            try:
                self.after_cancel(self.worker_poll_after_id)
            except tk.TclError:
                pass
            self.worker_poll_after_id = None
        if self.mathml_preview_poll_after_id is not None:
            try:
                self.after_cancel(self.mathml_preview_poll_after_id)
            except tk.TclError:
                pass
            self.mathml_preview_poll_after_id = None
        if self.busy_status_after_id is not None:
            try:
                self.after_cancel(self.busy_status_after_id)
            except tk.TclError:
                pass
            self.busy_status_after_id = None
        self._reset_recognizer()
        super().destroy()


class ScreenshotSelector:
    def __init__(self, parent: tk.Tk, callback) -> None:
        self.parent = parent
        self.callback = callback
        self.start_x = 0
        self.start_y = 0
        self.rect_id: int | None = None
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.22)

        width = self.window.winfo_screenwidth()
        height = self.window.winfo_screenheight()
        self.window.geometry(f"{width}x{height}+0+0")

        self.canvas = tk.Canvas(
            self.window,
            cursor="crosshair",
            bg="black",
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.window.bind("<Escape>", self._cancel)

    def start(self) -> None:
        self.window.deiconify()
        self.window.focus_force()

    def _on_press(self, event: tk.Event) -> None:
        self.start_x = int(event.x_root)
        self.start_y = int(event.y_root)
        self.rect_id = self.canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#2f8cff",
            width=3,
        )

    def _on_drag(self, event: tk.Event) -> None:
        if self.rect_id is None:
            return
        x0 = self.start_x - self.window.winfo_rootx()
        y0 = self.start_y - self.window.winfo_rooty()
        self.canvas.coords(self.rect_id, x0, y0, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        x1, y1 = self.start_x, self.start_y
        x2, y2 = int(event.x_root), int(event.y_root)
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        self.window.destroy()

        if right - left < 5 or bottom - top < 5:
            self.callback(None)
            return

        try:
            image = ImageGrab.grab(bbox=(left, top, right, bottom))
        except TypeError:
            image = ImageGrab.grab((left, top, right, bottom))
        self.callback(image)

    def _cancel(self, _event: tk.Event | None = None) -> None:
        self.window.destroy()
        self.callback(None)


def main() -> None:
    install_exception_logger()
    if "--word-mathml-self-test" in sys.argv:
        run_word_mathml_self_test()
        return
    if "--clipboard-self-test" in sys.argv:
        run_clipboard_self_test()
        return
    if "--preview-self-test" in sys.argv:
        run_preview_self_test()
        return
    if "--self-test" in sys.argv:
        run_self_test()
        return

    set_windows_app_id()
    app = FormulaOCRApp()
    app.mainloop()


def set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FormulaOCR.Offline.LaTeX.1"
        )
    except Exception:
        pass


def install_exception_logger() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _hook(exc_type, exc_value, exc_traceback) -> None:
        details = "".join(
            traceback.format_exception(exc_type, exc_value, exc_traceback)
        )
        write_log("Unhandled exception\n" + details)
        if any(
            flag in sys.argv
            for flag in (
                "--self-test",
                "--preview-self-test",
                "--clipboard-self-test",
                "--word-mathml-self-test",
            )
        ):
            print(details, file=sys.stderr)
            return
        try:
            messagebox.showerror("程序错误", f"程序启动失败，详情见日志：\n{LOG_FILE}")
        except Exception:
            pass

    sys.excepthook = _hook


def write_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(f"[{timestamp}] {message.rstrip()}\n")


def run_self_test() -> None:
    from PIL import ImageDraw, ImageFont

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--self-test-image", default="")
    parser.add_argument("--self-test-device", default="cpu")
    parser.add_argument("--self-test-model", default="PP-FormulaNet_plus-S")
    args, _unknown = parser.parse_known_args(sys.argv[1:])

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if args.self_test_image:
        test_image = Path(args.self_test_image).expanduser().resolve()
    else:
        test_image = CACHE_DIR / "self_test_formula.png"
        image = Image.new("RGB", (520, 120), "white")
        draw = ImageDraw.Draw(image)
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/times.ttf", 64)
        except Exception:
            font = ImageFont.load_default()
        draw.text((28, 22), "x^2 + y^2 = z^2", fill="black", font=font)
        image.save(test_image)

    recognizer = PaddleFormulaRecognizer(
        paddleocr_repo=DEFAULT_PADDLEOCR_REPO,
        model_name=args.self_test_model,
        device=args.self_test_device,
    )
    try:
        formula = recognizer.predict(test_image)
        write_log(f"Self-test OK: {formula}")
        print(formula)
    except Exception:
        details = traceback.format_exc()
        write_log("Self-test failed\n" + details)
        print(details, file=sys.stderr)
        raise
    finally:
        recognizer.close()


def run_preview_self_test() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--preview-self-test", action="store_true")
    parser.add_argument(
        "--preview-formula",
        default=(
            r"e_{i j}^{(s)}=[f_{i}\parallel f_{j}\parallel"
            r"(x_{j}-x_{i})]\in\mathbb{R}^{2C_{i n}+3}"
        ),
    )
    args, _unknown = parser.parse_known_args(sys.argv[1:])

    app = FormulaOCRApp()
    app.withdraw()
    try:
        mathml = latex_to_mathml(args.preview_formula)
        token = int(time.time() * 1000) % 1_000_000
        image_path = app._render_mathml_to_png(token, mathml)
        write_log(f"Preview self-test OK: {image_path}")
        print(image_path)
    except Exception:
        details = traceback.format_exc()
        write_log("Preview self-test failed\n" + details)
        print(details, file=sys.stderr)
        raise
    finally:
        app.destroy()


def run_clipboard_self_test() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--clipboard-self-test", action="store_true")
    parser.add_argument(
        "--clipboard-formula",
        default=(
            r"\sum_{i=1}^{n}\sum_{j=1}^{n}\sum_{k=1}^{n}"
            r" f(x_i,y_j,z_k)+\overline{x}"
        ),
    )
    parser.add_argument("--require-native-clipboard", action="store_true")
    args, _unknown = parser.parse_known_args(sys.argv[1:])

    if sys.platform != "win32":
        print("clipboard-self-test: skipped on non-Windows")
        return

    root = tk.Tk()
    root.withdraw()
    root.update()
    try:
        mathml = latex_to_mathml(args.clipboard_formula)
        copied = copy_mathml_for_word_to_clipboard(
            mathml,
            plain_text=args.clipboard_formula,
            clipboard_widget=root,
            owner_hwnd=root.winfo_id(),
        )
        if not copied:
            raise RuntimeError("failed to write Word HTML MathML clipboard format")
        root.update()
        native_formats: list[str] = []
        native_error = ""
        try:
            native_formats = windows_clipboard_formats()
        except Exception as exc:
            native_error = str(exc)
        native_required = {FORMAT_HTML}
        if native_required.issubset(native_formats):
            html = windows_clipboard_text(FORMAT_HTML)
            formats = native_formats
            clipboard_path = "win32"
        else:
            if args.require_native_clipboard:
                raise RuntimeError(
                    "native clipboard formats unavailable: "
                    + (native_error or "|".join(native_formats))
                )
            html = tk_clipboard_text(root, FORMAT_HTML)
            formats = [FORMAT_HTML, "CF_UNICODETEXT"]
            clipboard_path = "tk-fallback"
        plain_text = root.clipboard_get()
        legacy_formats = {
            FORMAT_OFFICE_OPEN_XML,
            FORMAT_MATHML,
            FORMAT_MATHML_PRESENTATION,
        }
        checks = {
            "html_has_cf_html_header": html.startswith("Version:1.0"),
            "html_has_mathml": "<math" in html and "</math>" in html,
            "html_has_mathml_namespace": (
                'xmlns="http://www.w3.org/1998/Math/MathML"' in html
            ),
            "html_has_overline": _contains_word_overline_mathml(html),
            "html_has_display_limited_large_operator": (
                _contains_display_limited_large_operator(html)
            ),
            "legacy_word_formats_absent": legacy_formats.isdisjoint(formats),
            "unicode_text_matches": plain_text == args.clipboard_formula,
        }
        print(f"clipboard_path:{clipboard_path}")
        print("formats:" + "|".join(formats))
        for name, passed in checks.items():
            print(f"{name}:{passed}")
        if native_formats:
            print("win32_formats:" + "|".join(native_formats))
        elif native_error:
            print(f"win32_formats_unavailable:{native_error}")
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError("clipboard self-test failed: " + ", ".join(failed))
    finally:
        root.destroy()


def run_word_mathml_self_test() -> None:
    try:
        from formula_ocr_app.word_clipboard_tests import (
            CASES,
            run_word_mathml_regression,
        )
    except ImportError:
        from word_clipboard_tests import CASES, run_word_mathml_regression

    failures = run_word_mathml_regression()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        raise SystemExit(1)
    print(f"word-mathml-regression-ok:{len(CASES)}")


def _contains_word_overline_mathml(text: str) -> bool:
    return '<mover accent="true">' in text and "<mi>―</mi>" in text


def _contains_display_limited_large_operator(text: str) -> bool:
    return "<munderover>" in text and 'largeop="true"' in text


if __name__ == "__main__":
    main()
