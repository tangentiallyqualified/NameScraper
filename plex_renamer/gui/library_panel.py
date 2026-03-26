"""
Library panel — renders the left-side media roster.

Each entry gets a card with poster thumbnail, title, match confidence,
file counts, and status indicators. Clicking a card populates the
middle preview panel with that entry's current preview data.

All functions take the app instance to access library_canvas and state.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

from ..constants import MediaType
from ..engine import AUTO_ACCEPT_THRESHOLD, ScanState, score_results
from ..parsing import clean_folder_name, extract_year
from ..styles import COLORS
from ..app.services import CommandGatingService


# ─── Layout metrics ──────────────────────────────────────────────────────────

@dataclass
class LibraryMetrics:
    """Pre-computed DPI-scaled layout values for library card rendering."""
    margin_x: int
    margin_y: int
    pad_x: int
    pad_y: int
    thumb_w: int
    thumb_h: int
    thumb_margin: int
    check_w: int
    bar_w: int
    font_title: tuple
    font_sub: tuple
    font_status: tuple
    font_check: tuple
    font_conf: tuple
    font_alt_title: tuple

    @classmethod
    def from_scale(cls, s: float) -> LibraryMetrics:
        return cls(
            margin_x=int(3 * s),
            margin_y=int(2 * s),
            pad_x=int(8 * s),
            pad_y=int(8 * s),
            thumb_w=int(36 * s),
            thumb_h=int(54 * s),
            thumb_margin=int(8 * s),
            check_w=int(22 * s),
            bar_w=int(3 * s),
            font_title=("Helvetica", 10, "bold"),
            font_sub=("Helvetica", 9),
            font_status=("Helvetica", 8),
            font_check=("Helvetica", 13),
            font_conf=("Helvetica", 8),
            font_alt_title=("Helvetica", 9),
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _is_plex_ready_state(state: ScanState) -> bool:
    """Return the app-layer Plex Ready classification for a roster entry."""
    return CommandGatingService.is_plex_ready_state(state)

def _status_color(state: ScanState) -> str:
    """Pick a status dot color based on state."""
    c = COLORS
    if state.queued:
        return c["success"]
    if _is_plex_ready_state(state):
        return c["success"]
    if state.duplicate_of:
        return c["text_muted"]
    if state.all_skipped:
        return c["text_muted"]
    if state.needs_review:
        return c["accent"]
    if state.scanned and state.completeness:
        if state.completeness.is_complete:
            return c["success"]
        if state.completeness.pct >= 75:
            return c["info"]
        return c["accent"]
    return c["text_muted"]


def _status_text(state: ScanState) -> str:
    """Build a short status string for a show card."""
    if state.queued:
        return "Queued"
    if _is_plex_ready_state(state):
        return "Plex Ready"
    if state.duplicate_of:
        return f"Duplicate of {state.duplicate_of}"
    if state.scanning:
        return "Scanning..."
    if state.all_skipped:
        return f"{state.file_count} files — all skipped"
    if not state.scanned:
        return "Not scanned"
    if state.completeness:
        rpt = state.completeness
        if rpt.is_complete:
            return f"{rpt.total_matched}/{rpt.total_expected} — complete"
        return f"{rpt.total_matched}/{rpt.total_expected} ({rpt.pct:.0f}%)"
    return f"{state.file_count} files"


def _confidence_text(state: ScanState) -> str:
    """Build confidence label."""
    pct = int(state.confidence * 100)
    if state.confidence >= AUTO_ACCEPT_THRESHOLD:
        return f"Match: {pct}%"
    return f"Needs review ({pct}%)"


def _library_thumb_key(state: ScanState, thumb_w: int, thumb_h: int) -> tuple:
    """Stable cache key for a library thumbnail."""
    return (
        state.show_id,
        state.media_info.get("poster_path"),
        str(state.folder),
        thumb_w,
        thumb_h,
    )


def _library_media_type(state: ScanState) -> str:
    """Infer the media type for a roster entry thumbnail."""
    media_type = state.media_info.get("_media_type")
    if media_type:
        return media_type
    if state.media_info.get("name"):
        return MediaType.TV
    return MediaType.MOVIE


def _set_show_selected_visual(app, index: int, selected: bool) -> None:
    """Update card highlight for a single show without redrawing the full roster."""
    cv = app.library_canvas
    c = COLORS
    tag = f"lib_item_{index}"
    fill = c["bg_card_selected"] if selected else c["bg_card"]
    outline = c["accent"] if selected else c["border"]
    for item_id in cv.find_withtag(tag):
        if cv.type(item_id) == "rectangle" and "lib_card" in cv.gettags(item_id):
            cv.itemconfigure(item_id, fill=fill, outline=outline)


def _update_show_check_visual(app, index: int) -> None:
    """Update the master checkbox glyph for one show card."""
    if index >= len(app.library_states):
        return
    state = app.library_states[index]
    cv = app.library_canvas
    c = COLORS
    tag = f"lib_item_{index}"
    check_char = "☑" if state.checked else "☐"
    check_color = c["accent"] if state.checked else c["border_light"]
    for item_id in cv.find_withtag(tag):
        if "lib_check" in cv.gettags(item_id):
            cv.itemconfigure(item_id, text=check_char, fill=check_color)


# ─── Main rendering ──────────────────────────────────────────────────────────

def display_library(app) -> None:
    """Render the current media roster from app.library_states onto library_canvas."""
    c = COLORS
    cv = app.library_canvas

    cv.delete("all")
    app._library_card_positions = []
    app._library_alt_positions = []

    if not app.library_states:
        empty_title = "No media selected"
        empty_hint = "Select a TV folder, movie folder, or movie file(s)"
        if app.media_type == MediaType.TV:
            empty_title = "No TV shows loaded"
            empty_hint = "Select a TV folder to build a roster"
        elif app.media_type == MediaType.MOVIE:
            empty_title = "No movies loaded"
            empty_hint = "Select a movie folder or movie file(s)"
        cv.create_text(
            20, 40, text=empty_title,
            fill=c["text_muted"], font=("Helvetica", 11), anchor="w")
        cv.create_text(
            20, 62, text=empty_hint,
            fill=c["text_muted"], font=("Helvetica", 9), anchor="w")
        cv.configure(scrollregion=(0, 0, 240, 100))
        return

    canvas_w = max(200, cv.winfo_width())
    m = LibraryMetrics.from_scale(app.dpi_scale)
    s = app.dpi_scale

    # Build display order by result group, preserving original order within
    # each group so the scanner's ordering still reads naturally.
    display_indices = list(range(len(app.library_states)))

    # Respect "hide already properly named" setting
    hide_named = getattr(app, 'settings_hide_named', None)
    if hide_named and hide_named.get():
        display_indices = [
            i for i in display_indices
            if not _is_plex_ready_state(app.library_states[i])
        ]

    display_indices.sort(key=lambda i: (_group_sort_key(app.library_states[i]), i))

    draw_group_headers = (
        len(display_indices) > 1
        and (
            app.batch_mode
            or getattr(app, "_active_library_mode", None) == MediaType.MOVIE
        )
    )

    # Track which quality group headings we've drawn
    _drawn_headers: set[str] = set()

    y = m.margin_y

    for index in display_indices:
        state = app.library_states[index]

        # Group header
        header = _group_header_for(state)
        if draw_group_headers and header and header not in _drawn_headers:
            _drawn_headers.add(header)
            header_h = int(22 * s)
            cv.create_text(
                m.margin_x + m.pad_x, y + header_h // 2,
                text=header.upper(), fill=c["text_muted"],
                font=("Helvetica", 8, "bold"), anchor="w")
            cv.create_line(
                m.margin_x + m.pad_x, y + header_h - 1,
                canvas_w - m.margin_x, y + header_h - 1,
                fill=c["border"], dash=(2, 2))
            y += header_h + int(2 * s)

        y = _draw_show_card(app, cv, y, state, index, canvas_w, m)

        # Draw alternate matches for low-confidence shows
        if state.needs_review and state.alternate_matches and not state.queued:
            y = _draw_alternate_matches(app, cv, y, state, index, canvas_w, m)

    content_h = y + 10
    visible_h = cv.winfo_height()
    cv.configure(scrollregion=(0, 0, canvas_w, max(content_h, visible_h)))
    cv.bind("<Button-1>", lambda e: on_library_click(app, e))

    update_library_totals(app)


def _group_header_for(state: ScanState) -> str | None:
    """Return a group header label for this state, or None."""
    if state.queued:
        return "queued"
    if _is_plex_ready_state(state):
        return "plex ready"
    if state.duplicate_of is not None:
        return "duplicates"
    if state.show_id is None:
        return "no match"
    if state.needs_review:
        return "needs review"
    return "matched"


def _group_sort_key(state: ScanState) -> int:
    """Sort groups in the order they should appear in the library roster."""
    header = _group_header_for(state)
    order = {
        "matched": 0,
        "plex ready": 1,
        "needs review": 2,
        "no match": 3,
        "duplicates": 4,
        "queued": 5,
    }
    return order.get(header or "matched", 99)


def _draw_show_card(
    app, cv, y, state, index, canvas_w, m: LibraryMetrics,
) -> int:
    """Draw a single show card. Returns new y position."""
    c = COLORS
    s = app.dpi_scale
    is_selected = (app._library_selected_index == index)
    is_duplicate = state.duplicate_of is not None
    is_plex_ready = _is_plex_ready_state(state)
    is_queued = state.queued
    is_inactive = is_duplicate or is_plex_ready or state.all_skipped or is_queued
    tag = f"lib_item_{index}"

    x_left = m.margin_x
    x_right = canvas_w - m.margin_x
    y_start = y

    # Card background colors
    card_bg = c["bg_card_selected"] if is_selected else c["bg_card"]
    card_outline = c["accent"] if is_selected else c["border"]

    # Accent bar color
    if is_queued:
        bar_color = c["success"]
    elif is_plex_ready:
        bar_color = c["success"]
    elif is_inactive:
        bar_color = c["text_muted"]
    elif state.needs_review:
        bar_color = c["accent"]
    else:
        bar_color = None

    # Text colors — dimmed for inactive (duplicates, skipped, queued)
    title_fg = c["text_muted"] if is_inactive else c["text"]
    sub_fg = c["text_muted"] if is_inactive else c["text_dim"]

    # Layout x positions
    check_x = x_left + m.bar_w + m.pad_x
    thumb_x = check_x + m.check_w
    text_x = thumb_x + m.thumb_w + m.thumb_margin
    max_text_w = x_right - text_x - m.pad_x

    # ── Text content ──────────────────────────────────────
    text_y = y + m.pad_y

    # Badge above title (PLEX READY, DUPLICATE, or QUEUED)
    badge_label = None
    badge_fg_color = c["text_muted"]
    badge_outline = c["text_muted"]
    if is_plex_ready:
        badge_label = " PLEX READY "
        badge_fg_color = c["success"]
        badge_outline = c["success"]
    elif is_duplicate:
        badge_label = " DUPLICATE "
    elif is_queued:
        badge_label = " QUEUED "
        badge_fg_color = c["success"]
        badge_outline = c["success"]

    if badge_label:
        badge_tw = cv.tk.call("font", "measure", "TkDefaultFont", badge_label)
        try:
            badge_tw = int(badge_tw)
        except (TypeError, ValueError):
            badge_tw = 70
        badge_h = int(14 * s)
        cv.create_rectangle(
            text_x, text_y, text_x + badge_tw + int(8 * s), text_y + badge_h,
            fill=c["bg_mid"], outline=badge_outline, tags=(tag,))
        cv.create_text(
            text_x + int(4 * s), text_y + badge_h // 2,
            text=badge_label, fill=badge_fg_color,
            font=("Helvetica", 7, "bold"), anchor="w", tags=("text", tag))
        text_y += badge_h + int(3 * s)

    # Title (ellipsized)
    title = state.display_name
    id_title = cv.create_text(
        text_x, text_y, text=title,
        fill=title_fg, font=m.font_title, anchor="nw",
        width=max_text_w, tags=("text", tag))
    bbox = cv.bbox(id_title)
    title_h = (bbox[3] - bbox[1]) if bbox else 14
    text_y += title_h + int(2 * s)

    # Subtitle: year · seasons · episodes
    sub_parts = []
    year = state.media_info.get("year", "")
    if year:
        sub_parts.append(str(year))
    n_seasons = state.media_info.get("number_of_seasons")
    if n_seasons:
        sub_parts.append(f"{n_seasons}S")
    n_eps = state.media_info.get("number_of_episodes")
    if n_eps:
        sub_parts.append(f"{n_eps} eps")
    subtitle = " · ".join(sub_parts) if sub_parts else state.folder.name
    cv.create_text(
        text_x, text_y, text=subtitle,
        fill=sub_fg, font=m.font_sub, anchor="nw",
        width=max_text_w, tags=("text", tag))
    text_y += int(14 * s)

    # Status line with dot
    status_fg = _status_color(state)
    status_txt = _status_text(state)
    dot_r = int(3 * s)
    cv.create_oval(
        text_x, text_y + int(4 * s),
        text_x + dot_r * 2, text_y + int(4 * s) + dot_r * 2,
        fill=status_fg, outline="", tags=(tag,))
    cv.create_text(
        text_x + dot_r * 2 + int(4 * s), text_y,
        text=status_txt, fill=status_fg, font=m.font_status,
        anchor="nw", tags=("text", tag))
    text_y += int(14 * s)

    # Confidence (only for low-confidence)
    if state.needs_review:
        conf_txt = _confidence_text(state)
        cv.create_text(
            text_x, text_y, text=conf_txt,
            fill=c["accent"], font=m.font_conf, anchor="nw",
            tags=("text", tag))
        text_y += int(12 * s)

    # Card height
    content_bottom = text_y + m.pad_y
    row_h = max(m.thumb_h + m.pad_y * 2, content_bottom - y)

    # Card background
    card_id = cv.create_rectangle(
        x_left, y, x_right, y + row_h,
        fill=card_bg, outline=card_outline,
        tags=("card", "lib_card", tag))
    cv.tag_lower(card_id)

    # Accent bar
    if bar_color:
        bar_id = cv.create_rectangle(
            x_left, y, x_left + m.bar_w, y + row_h,
            fill=bar_color, outline="", tags=(tag,))
        cv.tag_raise(bar_id, card_id)

    # Checkbox
    check_cy = y + row_h // 2
    if is_duplicate or is_plex_ready or state.all_skipped or is_queued:
        check_char = "—"
        check_color = c["text_muted"]
    elif state.checked:
        check_char = "☑"
        check_color = c["accent"]
    else:
        check_char = "☐"
        check_color = c["border_light"]
    cv.create_text(
        check_x, check_cy, text=check_char,
        fill=check_color, font=m.font_check, anchor="w",
        tags=("lib_check", tag))

    # Poster thumbnail
    photo = app._library_thumb_cache.get(
        _library_thumb_key(state, m.thumb_w, m.thumb_h),
        app._library_placeholder,
    )
    if photo:
        thumb_y = y + (row_h - m.thumb_h) // 2
        cv.create_image(
            thumb_x, thumb_y, image=photo, anchor="nw", tags=(tag,))

    app._library_card_positions.append((y_start, y_start + row_h, index))
    return y + row_h + m.margin_y


def _draw_alternate_matches(
    app, cv, y, state, index, canvas_w, m: LibraryMetrics,
) -> int:
    """Draw alternate TMDB matches below a low-confidence show card."""
    c = COLORS
    s = app.dpi_scale
    indent = int(20 * s)
    x_left = m.margin_x + indent
    x_right = canvas_w - m.margin_x
    alt_h = int(28 * s)

    for alt_idx, alt in enumerate(state.alternate_matches[:3]):
        alt_tag = f"lib_alt_{index}_{alt_idx}"
        alt_name = alt.get("name") or alt.get("title") or "?"
        alt_year = alt.get("year", "")
        alt_label = f"{alt_name}" + (f" ({alt_year})" if alt_year else "")

        # Tiny card for alternate
        card_id = cv.create_rectangle(
            x_left, y, x_right, y + alt_h,
            fill=c["bg_mid"], outline=c["border"],
            tags=("alt_card", alt_tag))

        cv.create_text(
            x_left + m.pad_x, y + alt_h // 2,
            text=f"↳ {alt_label}",
            fill=c["text_dim"], font=m.font_alt_title, anchor="w",
            width=x_right - x_left - m.pad_x * 2 - int(40 * s),
            tags=("text", alt_tag))

        # "Use" label on right
        cv.create_text(
            x_right - m.pad_x, y + alt_h // 2,
            text="Use →",
            fill=c["accent"], font=m.font_conf, anchor="e",
            tags=("text", alt_tag))

        app._library_alt_positions.append((y, y + alt_h, index, alt_idx))
        y += alt_h + int(1 * s)

    return y + int(2 * s)


# ─── Interaction ──────────────────────────────────────────────────────────────

def on_library_click(app, event) -> None:
    """Handle clicks on the library canvas — checkboxes, show selection, alternates."""
    try:
        _on_library_click_impl(app, event)
    except Exception:
        import traceback
        traceback.print_exc()


def _on_library_click_impl(app, event) -> None:
    cy = app.library_canvas.canvasy(event.y)
    cx = app.library_canvas.canvasx(event.x)
    s = app.dpi_scale
    check_zone = int(30 * s)

    # Check alternate match clicks first
    for y_start, y_end, show_idx, alt_idx in app._library_alt_positions:
        if y_start <= cy <= y_end:
            _apply_alternate_match(app, show_idx, alt_idx)
            return

    # Check show card clicks
    for y_start, y_end, show_idx in app._library_card_positions:
        if y_start <= cy <= y_end:
            if cx < check_zone + int(10 * s):
                toggle_show_check(app, show_idx)
            else:
                select_show(app, show_idx)
            return


def _apply_alternate_match(app, show_idx: int, alt_idx: int) -> None:
    """Apply an alternate TMDB match for a show."""
    if show_idx >= len(app.library_states):
        return
    state = app.library_states[show_idx]
    if alt_idx >= len(state.alternate_matches):
        return

    new_match = state.alternate_matches[alt_idx]
    if app.batch_orchestrator:
        app.batch_orchestrator.rematch_show(state, new_match)

    # Rebuild alternates from search results excluding the new best match
    raw_name = clean_folder_name(state.folder.name)
    year_hint = extract_year(state.folder.name)
    scored = score_results(state.search_results, raw_name, year_hint, title_key="name")
    state.alternate_matches = [
        r for r, s in scored[:4]
        if r.get("id") != state.media_info.get("id") and s > 0.3
    ]

    display_library(app)

    # If this was the selected show, reload its preview
    if app._library_selected_index == show_idx:
        _load_show_preview(app, state)


def select_show(app, index: int) -> None:
    """Select a show and populate the middle panel with its episode preview."""
    if index >= len(app.library_states):
        return

    # No need to save state — properties write directly to active_scan
    previous_index = app._library_selected_index
    app._library_selected_index = index
    state = app.library_states[index]
    app.active_scan = state

    # Update library panel highlighting without redrawing the full roster
    if app._library_card_positions:
        if previous_index is not None and previous_index != index:
            _set_show_selected_visual(app, previous_index, False)
        _set_show_selected_visual(app, index, True)
    else:
        display_library(app)

    # Scroll selected card into view
    _scroll_to_show(app, index)

    # Load this show's data into the preview/detail panels
    _load_show_preview(app, state)


def _scroll_to_show(app, index: int) -> None:
    """Scroll the library canvas to make the selected show visible."""
    for y_start, y_end, idx in app._library_card_positions:
        if idx == index:
            cv = app.library_canvas
            region_str = cv.cget("scrollregion")
            if not region_str:
                break
            region = region_str.split()
            if len(region) == 4:
                total_h = float(region[3])
                if total_h > 0:
                    visible_h = cv.winfo_height()
                    # Only scroll if card isn't fully visible
                    view_top = cv.canvasy(0)
                    view_bottom = view_top + visible_h
                    if y_start < view_top or y_end > view_bottom:
                        fraction = max(0, (y_start - 20)) / total_h
                        cv.yview_moveto(fraction)
            break


def _load_show_preview(app, state: ScanState) -> None:
    """Load a roster entry's data into the preview and detail panels."""
    from . import preview_canvas, detail_panel

    if app.media_type == MediaType.MOVIE:
        if app._active_content_mode != MediaType.MOVIE:
            return
        app._show_movie_library_state(state)
        update_library_totals(app)
        return

    # Batch TV callbacks can finish after the user has switched to Movies.
    # Preserve TV session state, but do not redraw the shared pane unless
    # the TV tab currently owns it.
    if app._active_content_mode != MediaType.TV:
        return

    # If background scan is in progress for this show, show placeholder
    if state.scanning:
        cv, _, _ = app._clear_canvas()
        c = COLORS
        s = app.dpi_scale
        cv.create_text(
            int(20 * s), int(44 * s), text=f"Scanning {state.display_name}...",
            fill=c["text_muted"], font=("Helvetica", 13), anchor="nw")
        cv.create_text(
            int(20 * s), int(78 * s),
            text="Episode data will appear when the scan completes",
            fill=c["text_muted"], font=("Helvetica", 10), anchor="nw")
        cv.configure(scrollregion=(0, 0, 600, 120))
        app.media_label_var.set(state.display_name)
        detail_panel.reset_detail(app)
        return

    # Phase 2 scan if needed (normally already done by auto-scan,
    # but handles edge cases like rematched shows)
    if not state.scanned and state.show_id is not None:
        if app.batch_orchestrator:
            app.status_var.set(f"Scanning {state.display_name}...")
            app.root.update_idletasks()
            try:
                app.batch_orchestrator.scan_show(state)
                if app.command_gating.is_plex_ready_state(state):
                    state.checked = False
            except Exception as e:
                import traceback
                traceback.print_exc()
                app.status_var.set(f"Scan failed for {state.display_name}: {e}")
                return
            display_library(app)
            if hasattr(app, "_request_persistence"):
                app._request_persistence("tv", "cache")
            app.status_var.set(f"Loaded: {state.display_name}")

    # active_scan is already set by select_show() — the app's property
    # accessors now delegate directly to state, so no bridging needed.
    app.media_info = state.media_info

    # Update header
    app.media_label_var.set(state.display_name)

    # Display poster + show info
    tmdb = app._ensure_tmdb()
    if tmdb and state.show_id:
        detail_panel.display_poster(app, tmdb, state.show_id, "tv")
        detail_panel.populate_show_info(app, tmdb, state.show_id)
    else:
        detail_panel.reset_detail(app)

    # Render episodes in the preview panel
    preview_canvas.display_preview(app)
    if state.completeness:
        preview_canvas.display_completeness(app)

    # Auto-select the first actionable episode to populate the detail panel
    if state.preview_items:
        for idx, item in enumerate(state.preview_items):
            if item.status == "OK" or "UNMATCHED" in item.status:
                # Use display_order to find the first visible card
                if app._display_order:
                    first_display = app._display_order[0]
                    preview_canvas.select_card(app, first_display)
                else:
                    preview_canvas.select_card(app, idx)
                break

    # Update totals (lightweight — does NOT redraw the full library panel,
    # which was already redrawn by select_show before calling us)
    update_library_totals(app)


def toggle_show_check(app, index: int) -> None:
    """Toggle a show's master checkbox. Plex-ready and inactive shows cannot be checked."""
    if index >= len(app.library_states):
        return

    state = app.library_states[index]

    # Duplicates, Plex-ready, all-skipped, and queued shows can't be toggled
    if state.duplicate_of is not None:
        return
    if _is_plex_ready_state(state):
        return
    if state.all_skipped:
        return
    if state.queued:
        return

    state.checked = not state.checked

    # If this show's episodes are currently displayed, toggle all episode checkboxes
    if app.active_scan is state and state.check_vars:
        from . import preview_canvas

        key_values: dict[str, bool] = {}
        for key, var in state.check_vars.items():
            try:
                item_index = int(key)
                item = state.preview_items[item_index]
                if item.status == "OK" or "UNMATCHED" in item.status:
                    key_values[key] = state.checked
            except (ValueError, IndexError):
                pass
        preview_canvas._apply_bulk_check_values(
            app, key_values, redraw_preview=True)
    elif state.check_vars:
        for key, var in state.check_vars.items():
            try:
                item_index = int(key)
                item = state.preview_items[item_index]
            except (ValueError, IndexError):
                continue
            if item.status == "OK" or "UNMATCHED" in item.status:
                var.set(state.checked)

    if app._library_card_positions:
        _update_show_check_visual(app, index)
    else:
        display_library(app)
    update_library_totals(app)


def update_library_totals(app) -> None:
    """Update the totals bar at the bottom of the library panel."""
    if not hasattr(app, 'library_totals_var') or not app.library_states:
        return

    checked_shows = sum(1 for s in app.library_states if s.checked and not s.queued)
    total_shows = len(app.library_states)
    total_files = sum(s.file_count for s in app.library_states if s.checked and not s.queued)
    needs_review = sum(1 for s in app.library_states if s.needs_review and not s.queued)
    plex_ready = sum(1 for s in app.library_states if _is_plex_ready_state(s))
    queued_shows = sum(1 for s in app.library_states if s.queued)

    parts = [f"{checked_shows}/{total_shows} shows"]
    if total_files:
        parts.append(f"{total_files} files")
    if needs_review:
        parts.append(f"{needs_review} needs review")
    if plex_ready:
        parts.append(f"{plex_ready} Plex Ready")
    if queued_shows:
        parts.append(f"{queued_shows} queued")

    app.library_totals_var.set("  ·  ".join(parts))


# ─── Poster thumbnail loading ────────────────────────────────────────────────

def load_library_thumbnails(app) -> None:
    """
    Fetch poster thumbnails for all roster entries.

    Caches them by stable media identity so reordering or rematching
    doesn't force index-based thumbnail churn.
    """
    tmdb = app._ensure_tmdb()
    if not tmdb:
        return

    from PIL import ImageTk
    from .helpers import create_placeholder_poster
    from .queue_panel import _poster_dims, seed_poster_cache

    s = app.dpi_scale
    thumb_w = int(36 * s)
    thumb_h = int(54 * s)
    queue_w, _ = _poster_dims(app)

    signature = tuple(
        _library_thumb_key(state, thumb_w, thumb_h)
        for state in app.library_states
    )
    if signature == app._library_thumb_signature:
        return

    placeholder_img = create_placeholder_poster(thumb_w, thumb_h)
    placeholder_photo = ImageTk.PhotoImage(placeholder_img)
    app._library_placeholder = placeholder_photo  # prevent GC

    cache: dict[tuple, object] = dict(app._library_thumb_cache)

    for state in app.library_states:
        key = _library_thumb_key(state, thumb_w, thumb_h)
        if key in cache:
            continue
        poster_path = state.media_info.get("poster_path")
        if poster_path:
            img = tmdb.fetch_image(
                poster_path, target_width=max(thumb_w, queue_w))
            if img:
                seed_poster_cache(app, _library_media_type(state), state.show_id, img)
                img = img.resize((thumb_w, thumb_h))
                photo = ImageTk.PhotoImage(img)
                cache[key] = photo
                continue
        cache[key] = placeholder_photo

    app._library_thumb_cache = {
        key: cache[key] for key in signature if key in cache
    }
    app._library_thumb_signature = signature
