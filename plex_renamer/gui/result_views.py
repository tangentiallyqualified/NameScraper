"""
Result views — displayed on the preview canvas after rename operations
or when files are already properly named.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from ..constants import MediaType
from ..engine import CompletenessReport, PreviewItem, RenameResult
from ..styles import COLORS
from ..undo_log import load_log
from .helpers import draw_action_buttons, make_button_click_handler


def show_rename_result(app, result: RenameResult, renamed_items: list[PreviewItem]) -> None:
    """
    Replace the preview canvas with a success/result summary.

    Shows a completion badge, stats, the list of renames performed
    (old → new), any errors, and action buttons for scan-again / undo.
    """
    c = COLORS
    cv, canvas_w, s = app._clear_canvas()
    margin_x = int(16 * s)
    x_left = margin_x
    x_right = canvas_w - margin_x
    y = int(20 * s)
    self_root = app.folder  # for computing relative paths in result cards

    has_errors = len(result.errors) > 0

    # Completion badge
    if has_errors:
        badge_text = "⚠  Partially Complete"
        badge_fg = c["accent"]
    else:
        badge_text = "✓  Rename Complete"
        badge_fg = c["success"]

    cv.create_text(
        canvas_w // 2, y,
        text=badge_text, fill=badge_fg,
        font=("Helvetica", 18, "bold"), anchor="n")
    y += int(36 * s)

    # Stats line
    unmatched_count = sum(1 for it in renamed_items if "UNMATCHED" in it.status)
    renamed_count = result.renamed_count - unmatched_count
    stats_parts = [f"{renamed_count} files renamed"]
    if unmatched_count:
        stats_parts.append(f"{unmatched_count} unmatched")
    move_count = sum(1 for it in renamed_items if it.is_move())
    if move_count:
        stats_parts.append(f"{move_count} moved")
    dir_renames = result.log_entry.get("renamed_dirs", [])
    if dir_renames:
        stats_parts.append(f"{len(dir_renames)} folders renamed")
    removed_dirs = result.log_entry.get("removed_dirs", [])
    if removed_dirs:
        stats_parts.append(f"{len(removed_dirs)} empty folders removed")

    cv.create_text(
        canvas_w // 2, y,
        text="  ·  ".join(stats_parts), fill=c["text_dim"],
        font=("Helvetica", 11), anchor="n")
    y += int(28 * s)

    # Action buttons
    is_single_movie = (
        app.media_type == MediaType.MOVIE
        and app.movie_scanner
        and app.movie_scanner.explicit_files
        and len(app.movie_scanner.explicit_files) == 1
    )
    show_scan_again = not is_single_movie

    btn_y_top, btn_y_bot, regions = draw_action_buttons(
        cv, y, canvas_w, s, show_undo=True, show_scan=show_scan_again)
    y = btn_y_bot + int(20 * s)

    # Errors section
    if has_errors:
        cv.create_text(
            x_left, y, text="ERRORS",
            fill=c["error"], font=("Helvetica", 9, "bold"), anchor="nw")
        y += int(18 * s)
        for err in result.errors[:10]:
            cv.create_text(
                x_left + int(8 * s), y, text=f"  {err}",
                fill=c["error"], font=("Helvetica", 9), anchor="nw")
            y += int(16 * s)
        y += int(12 * s)

    # Folder operations (alphabetized)
    if dir_renames or removed_dirs:
        cv.create_text(
            x_left, y, text="FOLDER CHANGES",
            fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
        y += int(18 * s)
        for d in sorted(dir_renames, key=lambda d: Path(d["old"]).name.lower()):
            old_name = Path(d["old"]).name
            new_name = Path(d["new"]).name
            cv.create_text(
                x_left + int(8 * s), y,
                text=f"{old_name}  →  {new_name}",
                fill=c["move"], font=("Helvetica", 9), anchor="nw")
            y += int(16 * s)
        for d in sorted(removed_dirs, key=lambda d: Path(d).name.lower()):
            cv.create_text(
                x_left + int(8 * s), y,
                text=f"Removed: {Path(d).name}/",
                fill=c["text_muted"], font=("Helvetica", 9), anchor="nw")
            y += int(16 * s)
        y += int(12 * s)

    # Renamed files list (grouped by season, collapsible)
    cv.create_text(
        x_left, y, text="RENAMED FILES",
        fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
    y += int(22 * s)

    app._last_rename_result = result
    app._last_renamed_items = renamed_items

    by_season: dict[int | None, list[PreviewItem]] = defaultdict(list)
    for item in renamed_items:
        by_season[item.season].append(item)

    card_h = int(48 * s)
    pad = int(10 * s)
    bar_w = int(3 * s)
    result_season_positions: list[tuple[int, int, int | None]] = []
    result_card_positions: list[tuple[int, int, int]] = []  # (y_start, y_end, item_index)
    _result_selected_index: list[int | None] = [None]  # mutable for closure

    # Batch movie mode: pre-fetch poster thumbnails for result cards
    is_batch_movie = (
        app.media_type == MediaType.MOVIE
        and len(renamed_items) > 1
    )
    thumb_h = int(54 * s)  # thumbnail height — drives card min height
    thumb_w = int(36 * s)  # ~2:3 aspect ratio
    thumb_margin = int(8 * s)
    thumb_refs: list = []  # keep PhotoImage references alive
    thumb_images: dict[int, object] = {}  # item_index → PhotoImage

    if is_batch_movie:
        from PIL import ImageTk
        from .helpers import create_placeholder_poster
        placeholder_img = create_placeholder_poster(thumb_w, thumb_h)
        placeholder_photo = ImageTk.PhotoImage(placeholder_img)
        thumb_refs.append(placeholder_photo)

        tmdb = app._ensure_tmdb()
        for idx, item in enumerate(renamed_items):
            movie_data = (app.movie_scanner.movie_info.get(item.original)
                          if app.movie_scanner else None)
            if movie_data and movie_data.get("poster_path") and tmdb:
                img = tmdb.fetch_image(movie_data["poster_path"],
                                       target_width=thumb_w)
                if img:
                    img = img.resize((thumb_w, thumb_h))
                    photo = ImageTk.PhotoImage(img)
                    thumb_refs.append(photo)
                    thumb_images[idx] = photo
                    continue
            # No poster — use placeholder
            thumb_images[idx] = placeholder_photo
        card_h = max(card_h, thumb_h + pad * 2)

    # Store thumbnail refs on app to prevent garbage collection
    app._result_thumb_refs = thumb_refs

    # TV mode: pre-fetch season poster thumbnails for result headers
    is_tv_mode = app.media_type == MediaType.TV
    season_thumb_images: dict[int, object] = {}
    if is_tv_mode and app.tv_scanner:
        from PIL import ImageTk as _ImageTk
        tmdb = app._ensure_tmdb()
        if tmdb:
            season_poster_h = int(32 * s)  # match header height
            season_poster_w = int(22 * s)
            for season_key in by_season:
                if season_key is None:
                    continue
                img = tmdb.fetch_poster(
                    app.tv_scanner.show_info["id"], "tv",
                    season=season_key, target_width=season_poster_w)
                if img:
                    img = img.resize((season_poster_w, season_poster_h))
                    photo = _ImageTk.PhotoImage(img)
                    thumb_refs.append(photo)  # prevent GC
                    season_thumb_images[season_key] = photo

    # Pre-build index map for O(1) lookups (avoids O(n) .index() per item)
    _item_index_map: dict[int, int] = {id(item): i for i, item in enumerate(renamed_items)}

    for season_key in sorted(by_season.keys(), key=lambda k: k if k is not None else -1):
        items = by_season[season_key]
        is_collapsed = season_key in app._result_collapsed_seasons

        if season_key is not None and len(by_season) > 1:
            arrow = "\u25b8" if is_collapsed else "\u25be"
            if season_key == 0:
                hdr_text = f"{arrow}  Specials ({len(items)} files)"
            else:
                hdr_text = f"{arrow}  Season {season_key} ({len(items)} files)"

            has_season_thumb = season_key in season_thumb_images
            hdr_h = int(36 * s) if has_season_thumb else int(24 * s)
            hdr_y = y
            cv.create_rectangle(
                x_left, y, x_right, y + hdr_h,
                fill=c["bg_mid"], outline=c["border"])

            text_offset = int(8 * s)
            if has_season_thumb:
                season_poster_w = int(22 * s)
                cv.create_image(
                    x_left + int(8 * s), y + (hdr_h - int(32 * s)) // 2,
                    image=season_thumb_images[season_key],
                    anchor="nw")
                text_offset = int(8 * s) + season_poster_w + int(6 * s)

            cv.create_text(
                x_left + text_offset, y + hdr_h // 2,
                text=hdr_text, fill=c["text_dim"],
                font=("Helvetica", 9, "bold"), anchor="w")
            result_season_positions.append((hdr_y, hdr_y + hdr_h, season_key))
            y += hdr_h + int(4 * s)

        if is_collapsed:
            continue

        for item in items:
            tag = f"result_item_{len(result_card_positions)}"
            item_index = _item_index_map[id(item)]
            is_unmatched = "UNMATCHED" in item.status

            # Thumbnail shifts text to the right in batch movie mode
            has_thumb = item_index in thumb_images
            thumb_space = (thumb_w + thumb_margin) if has_thumb else 0
            text_x = x_left + bar_w + pad + int(22 * s) + thumb_space
            max_text_w = x_right - text_x - pad

            # Colors depend on matched vs unmatched
            bar_color = c["accent"] if is_unmatched else c["success"]
            check_color = c["accent"] if is_unmatched else c["success"]
            arrow_color = c["accent"] if is_unmatched else c["success"]
            check_char = "⚠" if is_unmatched else "\u2713"

            id1 = cv.create_text(
                text_x, y + pad,
                text=item.original.name, fill=c["text_muted"],
                font=("Helvetica", 9), anchor="nw",
                width=max_text_w, tags=(tag,))

            new_text = item.new_name or item.original.name
            if item.is_move() and item.target_dir:
                # Show the full relative path for unmatched
                if is_unmatched and item.target_dir:
                    try:
                        rel = item.target_dir.relative_to(self_root)
                        new_text = f"[{rel}]  {new_text}"
                    except ValueError:
                        new_text = f"[{item.target_dir.name}]  {new_text}"
                else:
                    new_text = f"[{item.target_dir.name}]  {new_text}"

            bbox1 = cv.bbox(id1)
            line1_bottom = (bbox1[3] if bbox1 else y + pad + int(14 * s))

            id2 = cv.create_text(
                text_x, line1_bottom + int(2 * s),
                text=f"\u2192  {new_text}", fill=arrow_color,
                font=("Helvetica", 10), anchor="nw",
                width=max_text_w, tags=(tag,))

            bbox2 = cv.bbox(id2)
            content_bottom = (bbox2[3] if bbox2 else line1_bottom + int(16 * s))
            actual_h = max(card_h, content_bottom - y + pad)

            bg_id = cv.create_rectangle(
                x_left, y, x_right, y + actual_h,
                fill=c["bg_card"], outline=c["border"],
                tags=("result_card", tag))
            cv.tag_lower(bg_id)

            bar_id = cv.create_rectangle(
                x_left, y, x_left + bar_w, y + actual_h,
                fill=bar_color, outline="", tags=(tag,))
            cv.tag_raise(bar_id, bg_id)

            cv.create_text(
                x_left + bar_w + pad, y + actual_h // 2,
                text=check_char, fill=check_color,
                font=("Helvetica", 12, "bold"), anchor="w", tags=(tag,))

            # Poster thumbnail (batch movie mode)
            if has_thumb:
                thumb_x = x_left + bar_w + pad + int(22 * s)
                thumb_y = y + (actual_h - thumb_h) // 2  # vertically centered
                cv.create_image(
                    thumb_x, thumb_y,
                    image=thumb_images[item_index],
                    anchor="nw", tags=(tag,))

            result_card_positions.append((y, y + actual_h, item_index))
            y += actual_h + int(2 * s)

        y += int(8 * s)

    y += int(10 * s)
    cv.configure(scrollregion=(0, 0, canvas_w, y))

    # Click handler
    def _on_extra_click(cx, cy_click):
        # Check season headers
        for sy_top, sy_bot, sk in result_season_positions:
            if sy_top <= cy_click <= sy_bot:
                if sk in app._result_collapsed_seasons:
                    app._result_collapsed_seasons.discard(sk)
                else:
                    app._result_collapsed_seasons.add(sk)
                show_rename_result(app, result, renamed_items)
                return

        # Check result cards — select and show detail
        for y_start, y_end, item_idx in result_card_positions:
            if y_start <= cy_click <= y_end:
                _select_result_card(cv, result_card_positions,
                                    _result_selected_index, item_idx,
                                    renamed_items, app)
                return

    make_button_click_handler(
        cv, btn_y_top, btn_y_bot, regions,
        undo_callback=app.undo, scan_callback=app.run_preview,
        extra_handler=_on_extra_click)

    # Status bar
    if has_errors:
        app.status_var.set(
            f"Renamed {result.renamed_count} files with "
            f"{len(result.errors)} error(s)")
    else:
        app.status_var.set(
            f"✓ Successfully renamed {result.renamed_count} files")

    # Detail panel — behavior depends on media type and count
    from .detail_panel import reset_detail

    is_movie = app.media_type == MediaType.MOVIE
    is_single_movie = (
        is_movie
        and app.movie_scanner
        and app.movie_scanner.explicit_files
        and len(app.movie_scanner.explicit_files) == 1
    )

    if is_single_movie:
        # Single movie: keep the detail panel as-is (already showing movie info)
        pass
    elif is_movie and result_card_positions:
        # Batch movie: auto-select the first result card to populate details
        first_card_idx = result_card_positions[0][2]
        _select_result_card(cv, result_card_positions,
                            _result_selected_index, first_card_idx,
                            renamed_items, app)
    else:
        # TV mode: reset and prompt for click
        reset_detail(app)
        app.detail_header.configure(text="RENAME COMPLETE")
        app.detail_ep_title.configure(text="Click a file to view details")
        app.detail_overview.configure(text="")


def show_already_renamed(app, report: CompletenessReport | None) -> None:
    """
    Show an 'already renamed' state for TV mode when all matched
    files already have their target names.
    """
    c = COLORS
    cv, canvas_w, s = app._clear_canvas()
    margin_x = int(16 * s)
    x_left = margin_x
    y = int(30 * s)

    episodes_complete = report and report.is_complete
    sp = report.specials if report else None
    specials_complete = sp and sp.expected > 0 and sp.is_complete
    specials_missing = sp and sp.expected > 0 and not sp.is_complete
    fully_complete = episodes_complete and (specials_complete or not sp or sp.expected == 0)

    # Badge
    if fully_complete:
        badge_text = "✓  Fully Complete"
        badge_fg = c["success"]
        sub_text = "All episodes and specials are present and correctly named."
    elif episodes_complete and specials_missing:
        badge_text = "✓  Episodes Complete"
        badge_fg = c["success"]
        sub_text = "All episodes are properly named. Some specials are missing."
    elif episodes_complete:
        badge_text = "✓  Already Properly Named"
        badge_fg = c["success"]
        sub_text = "All episodes are present and correctly named. No action needed."
    else:
        badge_text = "✓  Matched Files Already Named"
        badge_fg = c["accent"]
        sub_text = "All matched files already have their correct names."

    cv.create_text(
        canvas_w // 2, y, text=badge_text, fill=badge_fg,
        font=("Helvetica", 18, "bold"), anchor="n")
    y += int(34 * s)

    cv.create_text(
        canvas_w // 2, y, text=sub_text, fill=c["text_dim"],
        font=("Helvetica", 11), anchor="n")
    y += int(30 * s)

    # Completeness summary
    if report and report.total_expected > 0:
        if episodes_complete:
            summary = (f"{report.total_matched}/{report.total_expected} "
                       f"episodes — complete")
            summary_fg = c["success"]
        else:
            summary = (f"{report.total_matched}/{report.total_expected} "
                       f"episodes matched ({report.pct:.0f}%)")
            summary_fg = c["accent"]
        cv.create_text(
            canvas_w // 2, y, text=summary, fill=summary_fg,
            font=("Helvetica", 12, "bold"), anchor="n")
        y += int(30 * s)

    # Action buttons
    has_undo = bool(load_log())
    btn_y_top, btn_y_bot, regions = draw_action_buttons(
        cv, y, canvas_w, s, show_undo=has_undo, show_scan=True)
    y = btn_y_bot + int(20 * s)

    # Missing episodes
    if report and not episodes_complete and report.total_missing:
        cv.create_text(
            x_left, y, text="MISSING EPISODES",
            fill=c["error"], font=("Helvetica", 9, "bold"), anchor="nw")
        y += int(20 * s)
        for sn, ep_num, title in report.total_missing:
            cv.create_text(
                x_left + int(8 * s), y,
                text=f"S{sn:02d}E{ep_num:02d} – {title}",
                fill=c["text_dim"], font=("Helvetica", 10), anchor="nw")
            y += int(18 * s)
        y += int(12 * s)

    # Missing specials
    if specials_missing and sp.missing:
        cv.create_text(
            x_left, y, text="MISSING SPECIALS",
            fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
        y += int(20 * s)
        for ep_num, title in sp.missing:
            cv.create_text(
                x_left + int(8 * s), y,
                text=f"S00E{ep_num:02d} – {title}",
                fill=c["text_muted"], font=("Helvetica", 10), anchor="nw")
            y += int(18 * s)
        y += int(12 * s)

    if specials_complete:
        cv.create_text(
            x_left, y, text=f"Specials: {sp.matched}/{sp.expected} ✓",
            fill=c["success"], font=("Helvetica", 10), anchor="nw")
        y += int(24 * s)

    y += int(10 * s)
    cv.configure(scrollregion=(0, 0, canvas_w, y))

    make_button_click_handler(
        cv, btn_y_top, btn_y_bot, regions,
        undo_callback=app.undo, scan_callback=app.run_preview)

    if fully_complete:
        app.status_var.set("✓ Series fully complete — no action needed")
    elif episodes_complete and specials_missing:
        app.status_var.set(
            f"✓ Episodes complete — {len(sp.missing)} specials missing")
    elif episodes_complete:
        app.status_var.set("✓ Series is properly named — no action needed")
    else:
        app.status_var.set(
            f"Matched files already named — "
            f"{len(report.total_missing)} episodes missing"
            if report else "Matched files already named")


def show_already_renamed_movies(app, ok_items: list[PreviewItem]) -> None:
    """
    Show an 'already renamed' state for movie mode when all matched
    files already have their target names.
    """
    c = COLORS
    cv, canvas_w, s = app._clear_canvas()
    margin_x = int(16 * s)
    x_left = margin_x
    y = int(30 * s)

    count = len(ok_items)
    badge_text = "✓  Already Properly Named"
    badge_fg = c["success"]
    if count == 1:
        sub_text = "This movie is already correctly named. No action needed."
    else:
        sub_text = f"All {count} movies are already correctly named. No action needed."

    cv.create_text(
        canvas_w // 2, y, text=badge_text, fill=badge_fg,
        font=("Helvetica", 18, "bold"), anchor="n")
    y += int(34 * s)

    cv.create_text(
        canvas_w // 2, y, text=sub_text, fill=c["text_dim"],
        font=("Helvetica", 11), anchor="n")
    y += int(30 * s)

    # Undo button
    has_undo = bool(load_log())
    if has_undo:
        btn_y_top, btn_y_bot, regions = draw_action_buttons(
            cv, y, canvas_w, s, show_undo=True, show_scan=False)
        y = btn_y_bot + int(20 * s)
    else:
        btn_y_top = btn_y_bot = y
        regions = {}

    # List properly named files
    cv.create_text(
        x_left, y, text="PROPERLY NAMED FILES",
        fill=c["text_dim"], font=("Helvetica", 9, "bold"), anchor="nw")
    y += int(20 * s)

    for item in ok_items:
        cv.create_text(
            x_left + int(8 * s), y,
            text=f"✓  {item.original.name}",
            fill=c["success"], font=("Helvetica", 10), anchor="nw")
        y += int(18 * s)

    y += int(10 * s)
    cv.configure(scrollregion=(0, 0, canvas_w, y))

    make_button_click_handler(
        cv, btn_y_top, btn_y_bot, regions,
        undo_callback=app.undo, scan_callback=app.run_preview)

    app.status_var.set("✓ Movies already properly named — no action needed")

    # Populate detail panel with the first movie's info
    if ok_items:
        from .detail_panel import show_detail
        saved_items = app.preview_items
        app.preview_items = ok_items
        show_detail(app, 0)
        app.preview_items = saved_items


# ─── Shared helper ───────────────────────────────────────────────────────────

def _select_result_card(
    cv,
    card_positions: list[tuple[int, int, int]],
    selected_index: list[int | None],
    item_idx: int,
    renamed_items: list[PreviewItem],
    app,
) -> None:
    """
    Highlight a result card and populate the detail panel with its metadata.

    Uses the same visual selection pattern as the preview canvas — resets
    the previous card's outline, highlights the new one with accent color.
    """
    c = COLORS

    def _find_tag(target_idx: int) -> str | None:
        for i, (_, _, pos_idx) in enumerate(card_positions):
            if pos_idx == target_idx:
                return f"result_item_{i}"
        return None

    # Reset previous selection
    prev = selected_index[0]
    if prev is not None and prev != item_idx:
        tag = _find_tag(prev)
        if tag:
            for cid in cv.find_withtag(tag):
                if cv.type(cid) == "rectangle" and "result_card" in cv.gettags(cid):
                    cv.itemconfigure(cid, outline=c["border"], fill=c["bg_card"])

    # Highlight new selection
    tag = _find_tag(item_idx)
    if tag:
        for cid in cv.find_withtag(tag):
            if cv.type(cid) == "rectangle" and "result_card" in cv.gettags(cid):
                cv.itemconfigure(cid, outline=c["accent"], fill=c["bg_card_selected"])

    selected_index[0] = item_idx

    # Populate detail panel — temporarily set preview_items to renamed_items
    # so the detail panel can look up the item by index
    saved_items = app.preview_items
    app.preview_items = renamed_items
    from .detail_panel import show_detail
    show_detail(app, item_idx)
    app.preview_items = saved_items
