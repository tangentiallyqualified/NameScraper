"""
Preview canvas — renders the file rename preview list with cards,
season headers, checkbox interaction, completeness display, and search.

All functions take the app instance to access preview_canvas and state.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from ..constants import MediaType
from ..engine import SeasonCompleteness
from ..styles import COLORS


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _is_actionable(item) -> bool:
    """True if the item can be selected for rename (OK or UNMATCHED)."""
    return item.status == "OK" or "UNMATCHED" in item.status


# ─── Preview rendering ───────────────────────────────────────────────────────

def display_preview(app) -> None:
    """
    Render the preview list using canvas primitives.

    Cards are sorted: OK first, then REVIEW, then SKIP/CONFLICT.
    Each card shows original filename, new name, status, and badges.
    """
    c = COLORS
    cv = app.preview_canvas

    # Preserve selections across redraws
    saved_checks = {k: v.get() for k, v in app.check_vars.items()}

    cv.delete("all")
    cv.yview_moveto(0)
    app._card_positions = []
    app._season_header_positions = []
    app._display_order = []

    if not app.preview_items:
        cv.create_text(
            20, 50, text="No files to preview",
            fill=c["text_muted"], font=("Helvetica", 13), anchor="w")
        cv.create_text(
            20, 78, text="Select a media folder to begin",
            fill=c["text_muted"], font=("Helvetica", 10), anchor="w")
        cv.configure(scrollregion=(0, 0, 100, 120))
        app.check_vars.clear()
        app._selected_index = None
        return

    # Sort order
    is_tv_mode = app.media_type == MediaType.TV
    if is_tv_mode:
        def _sort_key(idx):
            item = app.preview_items[idx]
            sn = item.season if item.season is not None else 9999
            if item.status == "OK":
                status_pri = 0
            elif "UNMATCHED" in item.status:
                status_pri = 1
            elif "REVIEW" in item.status:
                status_pri = 1
            else:
                status_pri = 2
            ep = item.episodes[0] if item.episodes else 9999
            return (sn, status_pri, ep, idx)
    else:
        def _sort_key(idx):
            s = app.preview_items[idx].status
            if s == "OK":
                return (0, idx)
            elif "REVIEW" in s:
                return (1, idx)
            return (2, idx)

    app._display_order = sorted(range(len(app.preview_items)), key=_sort_key)

    # Create BooleanVars
    app.check_vars.clear()
    for i, item in enumerate(app.preview_items):
        key = str(i)
        default = item.status == "OK" or "UNMATCHED" in item.status
        var = tk.BooleanVar(value=saved_checks.get(key, default))
        var.trace_add("write", lambda *_: _on_check_changed(app))
        app.check_vars[key] = var

    # Font metrics
    font_orig = app._font_orig
    font_new = app._font_new
    font_badge = app._font_badge

    line1_h = font_orig.metrics("linespace")
    line2_h = font_new.metrics("linespace")
    badge_text_h = font_badge.metrics("linespace")

    canvas_w = max(600, cv.winfo_width())
    s = app.dpi_scale
    margin_x = int(4 * s)
    margin_y = int(2 * s)
    pad_x = int(14 * s)
    pad_y = int(10 * s)
    bar_w = int(4 * s)
    check_w = int(28 * s)
    badge_h = badge_text_h + int(8 * s)
    badge_px = int(6 * s)
    gap = int(6 * s)

    font_orig_t = ("Helvetica", 11)
    font_new_t = ("Helvetica", 10)
    font_badge_t = ("Helvetica", 8, "bold")
    font_check_t = ("Helvetica", 14)
    font_header_t = ("Helvetica", 10, "bold")
    font_header_sub_t = ("Helvetica", 9)

    # Batch movie mode: pre-fetch poster thumbnails for preview cards
    is_batch_movie = (
        app.media_type == MediaType.MOVIE
        and len(app.preview_items) > 1
    )
    thumb_h = int(54 * s)
    thumb_w = int(36 * s)
    thumb_margin = int(8 * s)
    preview_thumb_refs: list = []
    preview_thumb_images: dict[int, object] = {}

    if is_batch_movie:
        from PIL import ImageTk
        from .helpers import create_placeholder_poster
        placeholder_img = create_placeholder_poster(thumb_w, thumb_h)
        placeholder_photo = ImageTk.PhotoImage(placeholder_img)
        preview_thumb_refs.append(placeholder_photo)

        tmdb = app._ensure_tmdb()
        for idx, item in enumerate(app.preview_items):
            movie_data = (app.movie_scanner.movie_info.get(item.original)
                          if app.movie_scanner else None)
            if movie_data and movie_data.get("poster_path") and tmdb:
                img = tmdb.fetch_image(movie_data["poster_path"],
                                       target_width=thumb_w)
                if img:
                    img = img.resize((thumb_w, thumb_h))
                    photo = ImageTk.PhotoImage(img)
                    preview_thumb_refs.append(photo)
                    preview_thumb_images[idx] = photo
                    continue
            # No poster — use placeholder
            preview_thumb_images[idx] = placeholder_photo

    app._preview_thumb_refs = preview_thumb_refs

    y = margin_y
    last_season_drawn: int | None = None

    for display_idx, item_idx in enumerate(app._display_order):
        item = app.preview_items[item_idx]

        # Season header bar (TV mode only)
        if is_tv_mode and item.season is not None and item.season != last_season_drawn:
            last_season_drawn = item.season
            y = _draw_season_header(
                app, cv, y, item.season, canvas_w, margin_x, margin_y, s,
                font_header_t, font_header_sub_t,
            )

        # Skip cards for collapsed seasons
        if is_tv_mode and item.season is not None and item.season in app._collapsed_seasons:
            continue

        is_multi = len(item.episodes) > 1
        is_special = item.season == 0
        is_movie = item.media_type == MediaType.MOVIE
        is_other = item.media_type == MediaType.OTHER
        has_review = "REVIEW" in item.status
        has_unmatched = "UNMATCHED" in item.status
        has_badges = is_multi or is_special or is_movie or is_other or has_review or has_unmatched
        tag = f"item_{item_idx}"

        # Text and colors
        if "SKIP" in item.status:
            name_fg, arrow_fg = c["text_muted"], c["text_muted"]
            arrow_text = item.status
        elif has_review:
            name_fg, arrow_fg = c["text"], c["info"]
            arrow_text = item.status
        elif "CONFLICT" in item.status:
            name_fg, arrow_fg = c["error"], c["error"]
            arrow_text = item.status
        elif has_unmatched:
            name_fg, arrow_fg = c["text"], c["accent"]
            arrow_text = f"→  [Unmatched/{item.original.parent.name}]  {item.new_name}"
        elif item.is_move():
            name_fg, arrow_fg = c["text"], c["move"]
            arrow_text = f"→  [{item.target_dir.name}]  {item.new_name}"
        else:
            name_fg, arrow_fg = c["text"], c["success"]
            arrow_text = f"→  {item.new_name}" if item.new_name else ""

        orig_text = item.original.name
        if item.is_move():
            orig_text = f"[{item.original.parent.name}]  {orig_text}"

        # Card border color
        if has_review:
            border_color = c["badge_review_bd"]
        elif is_special:
            border_color = c["badge_special_bd"]
        elif is_multi:
            border_color = c["badge_multi_bd"]
        else:
            border_color = c["border"]

        y_start = y
        x_left = margin_x
        x_right = canvas_w - margin_x

        # Card colors
        is_selected = (app._selected_index == item_idx)
        card_bg = c["bg_card_selected"] if is_selected else c["bg_card"]
        card_outline = c["accent"] if is_selected else border_color

        # Accent bar color
        bar_color = None
        if has_review:
            bar_color = c["badge_review_bd"]
        elif is_special:
            bar_color = c["badge_special_bd"]
        elif is_multi:
            bar_color = c["badge_multi_bd"]
        elif is_movie:
            bar_color = c["badge_movie_bd"]
        elif is_other:
            bar_color = c["badge_other_bd"]

        check_x = x_left + bar_w + pad_x
        has_thumb = item_idx in preview_thumb_images
        thumb_space = (thumb_w + thumb_margin) if has_thumb else 0
        text_x = check_x + check_w + thumb_space
        text_y = y + pad_y
        max_text_w = x_right - text_x - pad_x

        # Badge pills
        if has_badges:
            bx = text_x
            badges_to_draw = []
            if has_review:
                badges_to_draw.append((" NEEDS REVIEW ", c["badge_review_bg"],
                                        c["badge_review_fg"], c["badge_review_bd"]))
            if has_unmatched:
                badges_to_draw.append((" UNMATCHED ", c["badge_review_bg"],
                                        c["badge_review_fg"], c["badge_review_bd"]))
            if is_movie:
                badges_to_draw.append((" MOVIE ", c["badge_movie_bg"],
                                        c["badge_movie_fg"], c["badge_movie_bd"]))
            if is_other:
                badges_to_draw.append((" OTHER ", c["badge_other_bg"],
                                        c["badge_other_fg"], c["badge_other_bd"]))
            if is_multi:
                badges_to_draw.append((f" {len(item.episodes)}-PART ",
                                        c["badge_multi_bg"], c["badge_multi_fg"],
                                        c["badge_multi_bd"]))
            if is_special:
                badges_to_draw.append((" SPECIAL ", c["badge_special_bg"],
                                        c["badge_special_fg"], c["badge_special_bd"]))

            for label, bg, fg, bd in badges_to_draw:
                tw = font_badge.measure(label)
                pill_w = tw + badge_px * 2
                cv.create_rectangle(
                    bx, text_y, bx + pill_w, text_y + badge_h,
                    fill=bg, outline=bd, tags=(tag,))
                cv.create_text(
                    bx + badge_px, text_y + badge_h // 2, text=label,
                    fill=fg, font=font_badge_t, anchor="w", tags=(tag,))
                bx += pill_w + gap

            text_y += badge_h + gap

        # Line 1: original filename (with wrapping)
        id1 = cv.create_text(
            text_x, text_y, text=orig_text,
            fill=name_fg, font=font_orig_t, anchor="nw",
            width=max_text_w,
            tags=("text", tag))
        bbox1 = cv.bbox(id1)
        line1_actual_h = (bbox1[3] - bbox1[1]) if bbox1 else line1_h
        text_y += line1_actual_h

        # Line 2: arrow + new name (with wrapping)
        line2_actual_h = 0
        if arrow_text:
            text_y += gap
            id2 = cv.create_text(
                text_x + 4, text_y, text=arrow_text,
                fill=arrow_fg, font=font_new_t, anchor="nw",
                width=max_text_w,
                tags=("text", tag))
            bbox2 = cv.bbox(id2)
            line2_actual_h = (bbox2[3] - bbox2[1]) if bbox2 else line2_h

        # Compute actual card height
        content_bottom = text_y + line2_actual_h + pad_y
        row_h = max(int(44 * s), content_bottom - y)
        if has_thumb:
            row_h = max(row_h, thumb_h + pad_y * 2)

        # Card background behind text
        card_id = cv.create_rectangle(
            x_left, y, x_right, y + row_h,
            fill=card_bg, outline=card_outline,
            tags=("card", tag))
        cv.tag_lower(card_id)

        # Accent bar
        if bar_color:
            bar_id = cv.create_rectangle(
                x_left, y, x_left + bar_w, y + row_h,
                fill=bar_color, outline="", tags=(tag,))
            cv.tag_raise(bar_id, card_id)

        # Checkbox — dimmed for non-actionable items
        check_var = app.check_vars[str(item_idx)]
        check_cy = y + row_h // 2
        item_actionable = _is_actionable(item)
        if not item_actionable:
            check_char = "—"
            check_color = c["text_muted"]
        elif check_var.get():
            check_char = "☑"
            check_color = c["accent"]
        else:
            check_char = "☐"
            check_color = c["border_light"]
        cv.create_text(
            check_x, check_cy, text=check_char,
            fill=check_color, font=font_check_t, anchor="w",
            tags=(f"check_{display_idx}", "check", tag))

        # Poster thumbnail (batch movie mode)
        if has_thumb:
            thumb_x = check_x + check_w
            thumb_y = y + (row_h - thumb_h) // 2
            cv.create_image(
                thumb_x, thumb_y,
                image=preview_thumb_images[item_idx],
                anchor="nw", tags=(tag,))

        app._card_positions.append((y_start, y_start + row_h, item_idx))
        y += row_h + margin_y

    content_h = y + 10
    visible_h = cv.winfo_height()
    cv.configure(scrollregion=(0, 0, canvas_w, max(content_h, visible_h)))
    cv.bind("<Button-1>", lambda e: on_canvas_click(app, e))
    app._canvas_in_preview_mode = True

    # Status summary
    count_ok = sum(1 for it in app.preview_items if it.status == "OK")
    count_move = sum(1 for it in app.preview_items if it.is_move())
    count_multi = sum(1 for it in app.preview_items if len(it.episodes) > 1)
    count_special = sum(1 for it in app.preview_items if it.season == 0)
    count_review = sum(1 for it in app.preview_items if "REVIEW" in it.status)
    count_unmatched = sum(1 for it in app.preview_items if "UNMATCHED" in it.status)
    parts = [f"{count_ok} ready"]
    if count_review:
        parts.append(f"{count_review} needs review")
    if count_unmatched:
        parts.append(f"{count_unmatched} unmatched")
    if count_multi:
        parts.append(f"{count_multi} multi-ep")
    if count_special:
        parts.append(f"{count_special} specials")
    if count_move:
        parts.append(f"{count_move} moving")
    skip = sum(1 for it in app.preview_items
               if it.status != "OK" and "REVIEW" not in it.status
               and "UNMATCHED" not in it.status)
    if skip:
        parts.append(f"{skip} skipped")
    app.status_var.set("Preview:  " + "  ·  ".join(parts))
    update_tally(app)


# ─── Season header ───────────────────────────────────────────────────────────

def _draw_season_header(
    app, cv, y, season_num, canvas_w, margin_x, margin_y, s,
    font_header_t, font_header_sub_t,
) -> int:
    """Draw a season header bar. Returns new y position."""
    c = COLORS
    header_h = int(32 * s)
    pad_x = int(12 * s)
    progress_h = int(4 * s)
    progress_w = int(80 * s)
    x_left = margin_x
    x_right = canvas_w - margin_x
    is_collapsed = season_num in app._collapsed_seasons
    tag = f"season_hdr_{season_num}"

    arrow = "▸" if is_collapsed else "▾"
    if season_num == 0:
        label = f"{arrow}  Specials"
    else:
        label = f"{arrow}  Season {season_num}"

    # Season checkbox state — checked if all actionable items in this season are checked
    season_items = [
        (i, it) for i, it in enumerate(app.preview_items)
        if it.season == season_num and _is_actionable(it)
    ]
    all_checked = all(
        app.check_vars.get(str(i)) is not None and app.check_vars[str(i)].get()
        for i, _ in season_items
    ) if season_items else False

    # Completeness data
    sc = None
    if app._completeness:
        if season_num == 0:
            sc = app._completeness.specials
        else:
            sc = app._completeness.seasons.get(season_num)

    # Header background
    cv.create_rectangle(
        x_left, y, x_right, y + header_h,
        fill=c["bg_mid"], outline=c["border"],
        tags=("season_header", tag))

    # Season checkbox
    check_x = x_left + pad_x
    check_char = "☑" if all_checked else "☐"
    check_color = c["accent"] if all_checked else c["border_light"]
    cv.create_text(
        check_x, y + header_h // 2,
        text=check_char, fill=check_color,
        font=("Helvetica", 14), anchor="w",
        tags=("season_header", tag, f"season_check_{season_num}"))

    # Season label
    label_x = check_x + int(24 * s)
    cv.create_text(
        label_x, y + header_h // 2,
        text=label, fill=c["text"], font=font_header_t,
        anchor="w", tags=("season_header", tag))

    if sc and sc.expected > 0:
        if sc.is_complete:
            tally_text = f"{sc.matched}/{sc.expected} — Complete"
            tally_color = c["success"]
        else:
            tally_text = f"{sc.matched}/{sc.expected} ({sc.pct:.0f}%)"
            tally_color = c["accent"] if sc.pct >= 50 else c["error"]

        bar_x = x_right - pad_x - progress_w
        bar_y = y + (header_h - progress_h) // 2

        cv.create_rectangle(
            bar_x, bar_y, bar_x + progress_w, bar_y + progress_h,
            fill=c["bg_card"], outline="", tags=("season_header", tag))

        fill_w = int(progress_w * sc.pct / 100)
        if fill_w > 0:
            cv.create_rectangle(
                bar_x, bar_y, bar_x + fill_w, bar_y + progress_h,
                fill=tally_color, outline="", tags=("season_header", tag))

        cv.create_text(
            bar_x - int(8 * s), y + header_h // 2,
            text=tally_text, fill=tally_color, font=font_header_sub_t,
            anchor="e", tags=("season_header", tag))

    app._season_header_positions.append((y, y + header_h, season_num))
    return y + header_h + margin_y


# ─── Canvas interaction ──────────────────────────────────────────────────────

def on_canvas_click(app, event) -> None:
    """Handle clicks on the preview canvas — checkboxes, headers, cards."""
    try:
        _on_canvas_click_impl(app, event)
    except Exception:
        import traceback
        traceback.print_exc()


def _on_canvas_click_impl(app, event) -> None:
    cy = app.preview_canvas.canvasy(event.y)
    cx = app.preview_canvas.canvasx(event.x)
    check_zone = int(40 * app.dpi_scale)

    for y_start, y_end, season_num in app._season_header_positions:
        if y_start <= cy <= y_end:
            if cx < check_zone:
                toggle_season_check(app, season_num)
            else:
                if season_num in app._collapsed_seasons:
                    app._collapsed_seasons.discard(season_num)
                else:
                    app._collapsed_seasons.add(season_num)
                display_preview(app)
            return

    for y_start, y_end, item_idx in app._card_positions:
        if y_start <= cy <= y_end:
            if cx < check_zone:
                toggle_check(app, item_idx)
            else:
                select_card(app, item_idx)
            return


def toggle_season_check(app, season_num: int) -> None:
    """Toggle all actionable checkboxes in a season."""
    season_indices = [
        i for i, it in enumerate(app.preview_items)
        if it.season == season_num and _is_actionable(it)
    ]
    if not season_indices:
        return

    all_checked = all(
        app.check_vars.get(str(i)) is not None and app.check_vars[str(i)].get()
        for i in season_indices
    )
    new_val = not all_checked
    for i in season_indices:
        key = str(i)
        if key in app.check_vars:
            app.check_vars[key].set(new_val)

    if app._completeness_after_id:
        app.root.after_cancel(app._completeness_after_id)
        app._completeness_after_id = None
    if app.tv_scanner and app.preview_items:
        checked = get_checked_indices(app)
        app._completeness = app.tv_scanner.get_completeness(
            app.preview_items, checked_indices=checked)

    update_tally(app)
    display_preview(app)
    display_completeness(app)


def toggle_check(app, item_idx: int) -> None:
    """Toggle a single item's checkbox. Only actionable items can be toggled."""
    item = app.preview_items[item_idx]
    if not _is_actionable(item):
        return  # SKIP/REVIEW/CONFLICT items can't be checked

    key = str(item_idx)
    var = app.check_vars.get(key)
    if not var:
        return
    var.set(not var.get())

    c = COLORS
    cv = app.preview_canvas
    s = app.dpi_scale

    for display_idx, (y_start, y_end, idx) in enumerate(app._card_positions):
        if idx == item_idx:
            check_tag = f"check_{display_idx}"
            cv.delete(check_tag)
            check_char = "☑" if var.get() else "☐"
            check_color = c["accent"] if var.get() else c["border_light"]
            check_x = int(4 * s) + int(4 * s) + int(14 * s)
            check_cy = y_start + (y_end - y_start) // 2
            cv.create_text(
                check_x, check_cy, text=check_char,
                fill=check_color, font=("Helvetica", 14), anchor="w",
                tags=(check_tag, "check", f"item_{idx}"))
            break


def select_card(app, item_idx: int) -> None:
    """Select a card and show its details."""
    c = COLORS
    cv = app.preview_canvas

    prev = app._selected_index
    if prev is not None and prev != item_idx and prev < len(app.preview_items):
        old_item = app.preview_items[prev]
        if "REVIEW" in old_item.status or "UNMATCHED" in old_item.status:
            old_border = c["badge_review_bd"]
        elif old_item.season == 0:
            old_border = c["badge_special_bd"]
        elif len(old_item.episodes) > 1:
            old_border = c["badge_multi_bd"]
        else:
            old_border = c["border"]
        for tag_id in cv.find_withtag(f"item_{prev}"):
            if cv.type(tag_id) == "rectangle" and "card" in cv.gettags(tag_id):
                cv.itemconfigure(tag_id, outline=old_border, fill=c["bg_card"])

    for tag_id in cv.find_withtag(f"item_{item_idx}"):
        if cv.type(tag_id) == "rectangle" and "card" in cv.gettags(tag_id):
            cv.itemconfigure(tag_id, outline=c["accent"], fill=c["bg_card_selected"])

    app._selected_index = item_idx

    from .detail_panel import show_detail
    show_detail(app, item_idx)


# ─── Completeness display ───────────────────────────────────────────────────

def display_completeness(app) -> None:
    """Populate the completeness summary next to the poster."""
    c = COLORS
    report = app._completeness

    if not report:
        app.completeness_summary_label.configure(text="")
        _clear_season_details(app)
        _update_rename_button_style(app)
        return

    if report.is_complete:
        summary = (f"✓ Complete — "
                   f"{report.total_matched}/{report.total_expected} episodes")
        fg = c["success"]
    else:
        summary = (f"{report.total_matched}/{report.total_expected} "
                   f"episodes ({report.pct:.0f}%)")
        if report.pct >= 75:
            fg = c["accent"]
        elif report.pct >= 40:
            fg = c["info"]
        else:
            fg = c["error"]

    app.completeness_summary_label.configure(text=summary, foreground=fg)

    _clear_season_details(app)
    app._expanded_seasons.clear()

    all_seasons = sorted(report.seasons.items())
    if report.specials and report.specials.expected > 0:
        all_seasons.append((0, report.specials))

    for sn, sc in all_seasons:
        _build_season_row(app, sn, sc)

    _update_rename_button_style(app)


def clear_completeness(app) -> None:
    """Clear completeness data and widgets."""
    app._completeness = None
    app.completeness_summary_label.configure(text="")
    _clear_season_details(app)
    _update_rename_button_style(app)


def _build_season_row(app, sn: int, sc: SeasonCompleteness) -> None:
    """Build a single collapsible season row."""
    c = COLORS
    frame = ttk.Frame(app.completeness_detail_frame, style="Mid.TFrame")
    frame.pack(fill="x", anchor="w")

    if sn == 0:
        label_text = f"Specials: {sc.matched}/{sc.expected}"
    else:
        label_text = f"S{sn:02d}: {sc.matched}/{sc.expected}"

    if sc.is_complete:
        label_text += " ✓"
        header_fg = c["success"]
    else:
        label_text += f" ({sc.pct:.0f}%)"
        header_fg = c["accent"] if sc.pct >= 50 else c["error"]

    has_details = len(sc.missing) > 0 or (sn == 0 and len(sc.matched_episodes) > 0)
    if has_details:
        label_text = "▸ " + label_text

    header = tk.Label(
        frame, text=label_text, fg=header_fg,
        bg=c["bg_mid"], font=("Helvetica", 9),
        anchor="w", cursor="hand2" if has_details else "",
    )
    header.pack(fill="x", anchor="w")

    body = ttk.Frame(frame, style="Mid.TFrame")

    # Show matched specials in green (under the fold)
    if sn == 0 and sc.matched_episodes:
        for ep_num, title in sc.matched_episodes:
            tk.Label(
                body, text=f"    ✓ S00E{ep_num:02d} – {title}",
                fg=c["success"], bg=c["bg_mid"],
                font=("Helvetica", 8), anchor="w",
            ).pack(fill="x", anchor="w")

    # Show missing episodes in muted color
    if sc.missing:
        for ep_num, title in sc.missing:
            prefix = f"S00E{ep_num:02d}" if sn == 0 else f"E{ep_num:02d}"
            tk.Label(
                body, text=f"    {prefix} – {title}",
                fg=c["text_muted"], bg=c["bg_mid"],
                font=("Helvetica", 8), anchor="w",
            ).pack(fill="x", anchor="w")

    if has_details:
        def _toggle(event, _sn=sn):
            _toggle_season_detail(app, _sn)
        header.bind("<Button-1>", _toggle)

    app._season_detail_widgets[sn] = {
        "frame": frame, "header": header, "body": body,
        "has_missing": has_details,  # reused for toggle logic
    }


def _toggle_season_detail(app, sn: int) -> None:
    """Expand or collapse a season's missing episode list."""
    widgets = app._season_detail_widgets.get(sn)
    if not widgets or not widgets["has_missing"]:
        return

    header = widgets["header"]
    body = widgets["body"]
    text = header.cget("text")

    if sn in app._expanded_seasons:
        app._expanded_seasons.discard(sn)
        body.pack_forget()
        header.configure(text=text.replace("▾ ", "▸ ", 1))
    else:
        app._expanded_seasons.add(sn)
        body.pack(fill="x", anchor="w")
        header.configure(text=text.replace("▸ ", "▾ ", 1))


def _clear_season_details(app) -> None:
    """Remove all season detail widgets."""
    for sn, widgets in app._season_detail_widgets.items():
        widgets["frame"].destroy()
    app._season_detail_widgets.clear()


def _update_rename_button_style(app) -> None:
    """Set rename button to green 'Complete' style when series is fully matched."""
    report = app._completeness
    if report and report.is_complete:
        app.btn_rename.configure(style="Complete.TButton", text="✓ Rename Files")
    else:
        app.btn_rename.configure(style="Accent.TButton", text="Rename Files")


# ─── Search / selection ──────────────────────────────────────────────────────

def update_search(app) -> None:
    """Filter preview cards by search query."""
    query = app.search_var.get().lower()
    if not app._card_positions:
        return
    for y_start, y_end, item_idx in app._card_positions:
        item = app.preview_items[item_idx]
        text = (item.original.name + " " + (item.new_name or "")).lower()
        tag = f"item_{item_idx}"
        state = "normal" if (not query or query in text) else "hidden"
        for cid in app.preview_canvas.find_withtag(tag):
            app.preview_canvas.itemconfigure(cid, state=state)


def select_all(app) -> None:
    """Toggle all actionable checkboxes."""
    selectable = [
        str(i) for i, item in enumerate(app.preview_items)
        if _is_actionable(item)
    ]
    if not selectable:
        return
    all_checked = all(
        app.check_vars[k].get() for k in selectable if k in app.check_vars
    )
    new_val = not all_checked
    for k in selectable:
        if k in app.check_vars:
            app.check_vars[k].set(new_val)
    update_tally(app)


def update_tally(app) -> None:
    """Update the selected/total tally display."""
    total = sum(1 for it in app.preview_items if _is_actionable(it))
    selected = sum(
        1 for i, item in enumerate(app.preview_items)
        if _is_actionable(item)
        and app.check_vars.get(str(i)) is not None
        and app.check_vars[str(i)].get()
    )
    app.tally_var.set(f"{selected} / {total}")


def get_checked_indices(app) -> set[int]:
    """Return the set of item indices whose checkboxes are checked."""
    return {
        i for i in range(len(app.preview_items))
        if app.check_vars.get(str(i)) is not None
        and app.check_vars[str(i)].get()
    }


def _on_check_changed(app) -> None:
    """Called when any checkbox changes."""
    if not app.preview_items or not app.check_vars:
        return  # Guard against stale callbacks during rebuild
    update_tally(app)
    if app._completeness_after_id:
        app.root.after_cancel(app._completeness_after_id)
    app._completeness_after_id = app.root.after(50, lambda: _refresh_completeness(app))


def _refresh_completeness(app) -> None:
    """Recalculate and redisplay completeness."""
    app._completeness_after_id = None
    if app.tv_scanner and app.preview_items:
        checked = get_checked_indices(app)
        app._completeness = app.tv_scanner.get_completeness(
            app.preview_items, checked_indices=checked)
        display_completeness(app)
