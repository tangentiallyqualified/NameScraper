"""
Theme and style configuration for the Plex Renamer GUI.

Extracted from the monolithic GUI class to keep styling concerns
separate from application logic.  Provides a consistent color
palette and ttk style setup.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageDraw, ImageTk


# ─── Color palette ────────────────────────────────────────────────────────────

COLORS = {
    "bg_dark":          "#0d0d0d",
    "bg_mid":           "#151515",
    "bg_card":          "#1c1c1c",
    "bg_card_hover":    "#242424",
    "bg_card_selected": "#1f1a0e",
    "bg_input":         "#252525",
    "border":           "#2a2a2a",
    "border_light":     "#3a3a3a",
    "text":             "#e0e0e0",
    "text_dim":         "#777777",
    "text_muted":       "#4a4a4a",
    "accent":           "#e5a00d",
    "accent_hover":     "#f0b429",
    "accent_dim":       "#7a5a10",
    "success":          "#3ea463",
    "success_dim":      "#1a3328",
    "error":            "#d44040",
    "error_dim":        "#2d1414",
    "info":             "#4a9eda",
    "info_dim":         "#142030",
    "move":             "#6c8ebf",
    "move_dim":         "#162030",
    "badge_multi_bg":   "#2d1f4e",
    "badge_multi_fg":   "#b48efa",
    "badge_multi_bd":   "#4a3370",
    "badge_special_bg": "#1a3a2a",
    "badge_special_fg": "#5ec4a0",
    "badge_special_bd": "#2a5e45",
    "badge_movie_bg":   "#1a2a3a",
    "badge_movie_fg":   "#6aaddf",
    "badge_movie_bd":   "#2a4a6a",
    "badge_review_bg":  "#2a2210",
    "badge_review_fg":  "#d4a843",
    "badge_review_bd":  "#4a3a10",
    "badge_other_bg":   "#1e1e1e",
    "badge_other_fg":   "#888888",
    "badge_other_bd":   "#3a3a3a",
}


def get_dpi_scale(root: tk.Tk) -> float:
    """Get the DPI scaling factor from tkinter."""
    try:
        scale = root.tk.call("tk", "scaling")
        return max(1.0, scale)
    except Exception:
        return 1.0


def create_checkbox_images(size: int = 18) -> dict[str, ImageTk.PhotoImage]:
    """Create custom checkbox images (checked/unchecked) as PhotoImages."""
    c = COLORS

    img_off = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_off = ImageDraw.Draw(img_off)
    draw_off.rounded_rectangle(
        [1, 1, size - 2, size - 2],
        radius=3, outline=c["border_light"], width=2,
    )

    img_on = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_on = ImageDraw.Draw(img_on)
    draw_on.rounded_rectangle(
        [1, 1, size - 2, size - 2],
        radius=3, fill=c["accent"],
    )
    dark = c["bg_dark"]
    cx, cy = size * 0.28, size * 0.52
    mx, my = size * 0.45, size * 0.70
    ex, ey = size * 0.75, size * 0.32
    draw_on.line(
        [(cx, cy), (mx, my), (ex, ey)],
        fill=dark, width=max(2, size // 8),
    )

    return {
        "unchecked": ImageTk.PhotoImage(img_off),
        "checked": ImageTk.PhotoImage(img_on),
    }


def setup_styles(root: tk.Tk, dpi_scale: float) -> dict[str, ImageTk.PhotoImage]:
    """
    Configure all ttk styles and return the checkbox images dict.

    Must be called after the Tk root window is created.
    """
    c = COLORS
    root.configure(bg=c["bg_dark"])
    root.option_add("*Font", "Helvetica 11")

    style = ttk.Style()
    style.theme_use("clam")

    # Base
    style.configure(
        ".",
        background=c["bg_dark"], foreground=c["text"],
        fieldbackground=c["bg_input"], bordercolor=c["border"],
        insertcolor=c["text"], selectbackground=c["accent_dim"],
        selectforeground=c["text"],
    )

    # Frames
    style.configure("TFrame", background=c["bg_dark"])
    style.configure("Card.TFrame", background=c["bg_card"])
    style.configure("Mid.TFrame", background=c["bg_mid"])

    # Labels
    style.configure("TLabel", background=c["bg_dark"], foreground=c["text"],
                     font=("Helvetica", 11))
    style.configure("Title.TLabel", font=("Helvetica", 18, "bold"),
                     foreground=c["accent"])
    style.configure("Subtitle.TLabel", font=("Helvetica", 11),
                     foreground=c["text_dim"])
    style.configure("Card.TLabel", background=c["bg_card"], foreground=c["text"])
    style.configure("CardDim.TLabel", background=c["bg_card"],
                     foreground=c["text_dim"], font=("Helvetica", 10))
    style.configure("Detail.TLabel", background=c["bg_mid"], foreground=c["text"])
    style.configure("DetailDim.TLabel", background=c["bg_mid"],
                     foreground=c["text_dim"], font=("Helvetica", 10))
    style.configure("DetailTitle.TLabel", background=c["bg_mid"],
                     foreground=c["text"], font=("Helvetica", 12, "bold"))
    style.configure("DetailEpTitle.TLabel", background=c["bg_mid"],
                     foreground=c["accent"], font=("Helvetica", 11, "bold"))
    style.configure("DetailFieldName.TLabel", background=c["bg_mid"],
                     foreground=c["text_dim"], font=("Helvetica", 9))
    style.configure("DetailFieldValue.TLabel", background=c["bg_mid"],
                     foreground=c["text"], font=("Helvetica", 10))
    style.configure("DetailOverview.TLabel", background=c["bg_mid"],
                     foreground=c["text_dim"], font=("Helvetica", 10))
    style.configure("DetailRating.TLabel", background=c["bg_mid"],
                     foreground=c["accent"], font=("Helvetica", 11, "bold"))
    style.configure("DetailMeta.TLabel", background=c["bg_card"],
                     foreground=c["text_dim"], font=("Helvetica", 9))
    style.configure("DetailCard.TFrame", background=c["bg_card"])
    style.configure("Status.TLabel", background=c["bg_mid"],
                     foreground=c["text_dim"], font=("Helvetica", 10),
                     padding=(12, 6))

    # Buttons
    style.configure("Accent.TButton", font=("Helvetica", 11, "bold"),
                     background=c["accent"], foreground=c["bg_dark"],
                     padding=(16, 8), borderwidth=0)
    style.map("Accent.TButton",
               background=[("active", c["accent_hover"]),
                           ("disabled", c["border"])])

    style.configure("Complete.TButton", font=("Helvetica", 11, "bold"),
                     background=c["success"], foreground=c["bg_dark"],
                     padding=(16, 8), borderwidth=0)
    style.map("Complete.TButton",
               background=[("active", "#4bbf73"),
                           ("disabled", c["border"])])

    style.configure("TButton", font=("Helvetica", 11),
                     background=c["bg_card"], foreground=c["text"],
                     padding=(14, 8), borderwidth=1)
    style.map("TButton",
               background=[("active", c["border_light"]),
                           ("disabled", c["bg_mid"])])

    style.configure("Small.TButton", font=("Helvetica", 10), padding=(10, 5))

    style.configure("Danger.TButton", font=("Helvetica", 10),
                     background=c["error_dim"], foreground=c["error"],
                     padding=(10, 5), borderwidth=1)
    style.map("Danger.TButton",
               background=[("active", c["error"])])

    # Entry / Combobox
    style.configure("TEntry", padding=(8, 6), font=("Helvetica", 11))
    style.configure("TCombobox", padding=(8, 6),
                     fieldbackground=c["bg_input"], background=c["bg_card"],
                     foreground=c["text"], arrowcolor=c["text_dim"])
    style.map("TCombobox",
               fieldbackground=[("readonly", c["bg_input"]),
                                 ("readonly focus", c["bg_input"])],
               foreground=[("readonly", c["text"])],
               selectbackground=[("readonly", c["accent_dim"])],
               selectforeground=[("readonly", c["text"])])

    root.option_add("*TCombobox*Listbox.background", c["bg_input"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["bg_dark"])
    root.option_add("*TCombobox*Listbox.font", "Helvetica 11")
    root.option_add("*TCombobox*Listbox.borderWidth", "0")
    root.option_add("*TCombobox*Listbox.highlightThickness", "0")

    # Checkbutton with custom images
    check_size = max(20, int(18 * dpi_scale))
    check_imgs = create_checkbox_images(size=check_size)
    style.element_create(
        "custom_check", "image", check_imgs["unchecked"],
        ("selected", check_imgs["checked"]), sticky="w",
    )
    style.layout("Card.TCheckbutton", [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("custom_check", {"side": "left", "sticky": ""}),
            ("Checkbutton.label", {"side": "left", "sticky": "nswe"}),
        ]}),
    ])
    style.configure("Card.TCheckbutton", background=c["bg_card"],
                     foreground=c["text"])
    style.map("Card.TCheckbutton",
               background=[("active", c["bg_card_hover"])])

    # Scrollbar
    sb_width = max(10, int(8 * dpi_scale))
    style.configure("TScrollbar", background=c["bg_mid"],
                     troughcolor=c["bg_dark"], borderwidth=0,
                     arrowcolor=c["text_dim"], width=sb_width, arrowsize=sb_width)
    style.map("TScrollbar",
               background=[("active", c["border_light"])])

    style.configure("TSeparator", background=c["border"])

    # Progressbar
    style.configure("Accent.Horizontal.TProgressbar",
                     background=c["accent"], troughcolor=c["bg_card"],
                     borderwidth=0, thickness=4)

    return check_imgs
