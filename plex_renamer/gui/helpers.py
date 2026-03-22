"""
Shared GUI utilities — platform init, scaling, dialog creation,
mousewheel binding, progress bar, and canvas button helpers.

All functions/methods here are GUI-only but not specific to any
particular panel or view.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from PIL import Image, ImageDraw

from ..styles import COLORS


# ─── Placeholder poster ─────────────────────────────────────────────────────

def create_placeholder_poster(width: int, height: int) -> Image.Image:
    """
    Create a simple placeholder poster image for items without a TMDB poster.

    Returns a PIL Image with a dark background, border, and film icon.
    """
    c = COLORS
    img = Image.new("RGB", (width, height), c["bg_card"])
    draw = ImageDraw.Draw(img)
    # Border
    draw.rectangle([0, 0, width - 1, height - 1], outline=c["border"])
    # Simple film strip icon in center
    cx, cy = width // 2, height // 2
    icon_w, icon_h = width // 3, height // 4
    draw.rectangle(
        [cx - icon_w, cy - icon_h, cx + icon_w, cy + icon_h],
        outline=c["text_muted"], width=1)
    # Film perforations
    perf_size = max(2, width // 12)
    for dy in range(-icon_h, icon_h + 1, max(4, icon_h // 2)):
        draw.rectangle(
            [cx - icon_w - perf_size, cy + dy - perf_size // 2,
             cx - icon_w, cy + dy + perf_size // 2],
            fill=c["text_muted"])
        draw.rectangle(
            [cx + icon_w, cy + dy - perf_size // 2,
             cx + icon_w + perf_size, cy + dy + perf_size // 2],
            fill=c["text_muted"])
    return img


# ─── Platform ────────────────────────────────────────────────────────────────

def init_platform() -> None:
    """Platform-specific initialization (DPI awareness on Windows)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


# ─── Scaling ─────────────────────────────────────────────────────────────────

def scale_to_panel(img: Image.Image, detail_inner: ttk.Frame) -> Image.Image:
    """Scale a PIL Image to fit the detail panel width."""
    try:
        panel_w = detail_inner.winfo_width() - 40
    except Exception:
        panel_w = 260
    panel_w = max(150, panel_w)
    if img.width > panel_w:
        scale = panel_w / img.width
        img = img.resize((panel_w, int(img.height * scale)), Image.LANCZOS)
    return img


def scale_poster(img: Image.Image, detail_inner: ttk.Frame) -> Image.Image:
    """Scale the series/movie poster to ~45% of panel width."""
    try:
        panel_w = detail_inner.winfo_width() - 40
    except Exception:
        panel_w = 260
    target_w = max(80, int(panel_w * 0.45))
    if img.width != target_w:
        scale = target_w / img.width
        img = img.resize((target_w, int(img.height * scale)), Image.LANCZOS)
    return img


# ─── Dialog creation ─────────────────────────────────────────────────────────

def create_dialog(
    root: tk.Tk,
    title: str,
    dpi_scale: float,
    width: int = 500,
    height: int = 300,
) -> tk.Toplevel:
    """Create a centered modal dialog window."""
    c = COLORS
    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=c["bg_mid"])
    win.transient(root)
    win.grab_set()

    scaled_w = int(width * dpi_scale)
    scaled_h = int(height * dpi_scale)

    root.update_idletasks()
    rx = root.winfo_x()
    ry = root.winfo_y()
    rw = root.winfo_width()
    rh = root.winfo_height()
    x = max(0, rx + (rw - scaled_w) // 2)
    y = max(0, ry + (rh - scaled_h) // 2)

    win.geometry(f"{scaled_w}x{scaled_h}+{x}+{y}")
    win.minsize(scaled_w, scaled_h)
    return win


# ─── Mousewheel ──────────────────────────────────────────────────────────────

def bind_mousewheel(app, canvas: tk.Canvas) -> None:
    """
    Bind mousewheel scrolling for a canvas.

    Uses the app object to store _scroll_target so enter/leave on
    different canvases can swap which canvas receives scroll events.
    """
    app._scroll_target = canvas

    def _on_wheel(event):
        app._scroll_target.yview_scroll(int(-1 * (event.delta / 120)), "units")
    def _on_linux_up(event):
        app._scroll_target.yview_scroll(-3, "units")
    def _on_linux_down(event):
        app._scroll_target.yview_scroll(3, "units")

    canvas.bind_all("<MouseWheel>", _on_wheel)
    canvas.bind_all("<Button-4>", _on_linux_up)
    canvas.bind_all("<Button-5>", _on_linux_down)
    canvas.bind("<Enter>", lambda e: setattr(app, '_scroll_target', canvas))


def setup_detail_mousewheel(app, detail_canvas: tk.Canvas, preview_canvas: tk.Canvas) -> None:
    """Route mousewheel to detail canvas when mouse enters it."""
    detail_canvas.bind("<Enter>",
        lambda e: setattr(app, '_scroll_target', detail_canvas))
    detail_canvas.bind("<Leave>",
        lambda e: setattr(app, '_scroll_target', preview_canvas))


# ─── Progress ────────────────────────────────────────────────────────────────

def show_progress(progress_bar: ttk.Progressbar, progress_var: tk.DoubleVar, visible: bool) -> None:
    """Show or hide the progress bar in the status bar."""
    if visible:
        progress_bar.pack(side="right", padx=(8, 12), pady=4)
    else:
        progress_bar.pack_forget()
        progress_var.set(0)


# ─── Canvas button helpers ───────────────────────────────────────────────────

def draw_canvas_button(
    cv: tk.Canvas,
    x: int, y: int, w: int, h: int,
    text: str,
    fill: str, outline: str, text_color: str,
    tag: str,
) -> tuple[int, int, int, int]:
    """
    Draw a styled button on the canvas and return its hit region.

    Returns (x, y, x+w, y+h) for click hit-testing.
    """
    cv.create_rectangle(x, y, x + w, y + h, fill=fill, outline=outline, tags=(tag,))
    cv.create_text(
        x + w // 2, y + h // 2, text=text, fill=text_color,
        font=("Helvetica", 10, "bold"), anchor="center", tags=(tag,))
    return x, y, x + w, y + h


def draw_action_buttons(
    cv: tk.Canvas,
    y: int,
    canvas_w: int,
    dpi_scale: float,
    show_undo: bool = True,
    show_scan: bool = True,
) -> tuple[int, int, dict[str, tuple[int, int, int, int]]]:
    """
    Draw Undo and/or Scan Again buttons centered on the canvas.

    Returns (btn_y_top, btn_y_bottom, hit_regions).
    """
    c = COLORS
    s = dpi_scale
    btn_h = int(36 * s)
    btn_w = int(130 * s)
    btn_gap = int(12 * s)
    regions: dict[str, tuple[int, int, int, int]] = {}

    if show_undo and show_scan:
        undo_x = canvas_w // 2 - btn_w - btn_gap // 2
        scan_x = canvas_w // 2 + btn_gap // 2
    elif show_undo:
        undo_x = canvas_w // 2 - btn_w // 2
        scan_x = 0
    else:
        undo_x = 0
        scan_x = canvas_w // 2 - btn_w // 2

    if show_undo:
        regions["undo"] = draw_canvas_button(
            cv, undo_x, y, btn_w, btn_h,
            "Undo", c["error_dim"], c["error"], c["error"], "btn_undo")

    if show_scan:
        regions["scan"] = draw_canvas_button(
            cv, scan_x, y, btn_w, btn_h,
            "Scan Again", c["bg_card"], c["border_light"], c["text"], "btn_scan")

    return y, y + btn_h, regions


def make_button_click_handler(
    cv: tk.Canvas,
    btn_y_top: int,
    btn_y_bottom: int,
    regions: dict[str, tuple[int, int, int, int]],
    undo_callback: Callable,
    scan_callback: Callable,
    extra_handler: Callable | None = None,
) -> None:
    """
    Bind a click handler to the canvas that dispatches to Undo/Scan buttons.

    Args:
        extra_handler: Optional callback(cx, cy) for additional hit regions.
    """
    def _on_click(event):
        cx = cv.canvasx(event.x)
        cy_click = cv.canvasy(event.y)
        if btn_y_top <= cy_click <= btn_y_bottom:
            for name, (x1, y1, x2, y2) in regions.items():
                if x1 <= cx <= x2:
                    if name == "undo":
                        undo_callback()
                    elif name == "scan":
                        scan_callback()
                    return
        if extra_handler:
            extra_handler(cx, cy_click)

    cv.bind("<Button-1>", _on_click)
