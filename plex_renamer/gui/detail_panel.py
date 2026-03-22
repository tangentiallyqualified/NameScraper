"""
Detail panel — populates the right-side panel with metadata for the
selected preview item (TV episode or movie).

All functions take the app instance to access its widgets and state.
"""

from __future__ import annotations

from PIL import ImageTk

from ..constants import MediaType
from ..engine import PreviewItem
from ..tmdb import TMDBClient
from .helpers import scale_to_panel, scale_poster


# ─── Formatting helpers ──────────────────────────────────────────────────────

def format_rating(vote_avg: float, vote_count: int = 0) -> str:
    """Format a TMDB rating as a star display string."""
    if not vote_avg:
        return ""
    stars = vote_avg / 2
    full = int(stars)
    half = stars - full >= 0.3
    empty = 5 - full - (1 if half else 0)
    star_str = "★" * full + ("½" if half else "") + "☆" * empty
    count_str = f"  ({vote_count})" if vote_count else ""
    return f"{star_str}  {vote_avg:.1f}/10{count_str}"


def format_runtime(minutes: int | None) -> str:
    """Format runtime in minutes to a human readable string."""
    if not minutes:
        return ""
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h}h {m}m" if m else f"{h}h"
    return f"{minutes}m"


# ─── Panel operations ────────────────────────────────────────────────────────

def reset_detail(app) -> None:
    """Clear the detail panel to its empty state."""
    app.detail_header.configure(text="SELECT AN ITEM")
    app.detail_image.configure(image="")
    app._detail_img_ref = None
    app.detail_ep_title.configure(text="Click a file from the list\nto view its details")
    app.detail_meta_label.configure(text="")
    app.detail_overview.configure(text="")
    app.detail_crew_label.configure(text="")
    app.detail_orig_label.configure(text="")
    app.detail_new_label.configure(text="")
    app.detail_status_label.configure(text="")
    app.rematch_btn.pack_forget()


def display_poster(app, tmdb: TMDBClient, media_id: int, media_type: str) -> None:
    """Fetch and display the series/movie poster in the detail panel."""
    img = tmdb.fetch_poster(media_id, media_type, target_width=400)
    # Ensure poster row is visible
    if not app.poster_row.winfo_ismapped():
        app.poster_row.pack(fill="x", pady=(0, 6), before=app._separator_after_poster)
    if img:
        app.root.update_idletasks()
        img = scale_poster(img, app.detail_inner)
        photo = ImageTk.PhotoImage(img)
        app._poster_ref = photo
        app.poster_label.configure(image=photo)
    else:
        app.poster_label.configure(image="", text="(No poster)")


def populate_show_info(app, tmdb: TMDBClient, show_id: int) -> None:
    """Populate the show-level info beside the poster."""
    details = tmdb.get_tv_details(show_id)
    if not details:
        app.show_info_label.configure(text="")
        return

    lines = []

    vote_avg = details.get("vote_average", 0)
    if vote_avg:
        lines.append(format_rating(vote_avg, details.get("vote_count", 0)))

    genres = [g["name"] for g in details.get("genres", [])]
    if genres:
        lines.append(" · ".join(genres))

    status_parts = []
    status = details.get("status", "")
    if status:
        status_parts.append(status)
    networks = [n["name"] for n in details.get("networks", [])]
    if networks:
        status_parts.append(networks[0])
    if status_parts:
        lines.append(" · ".join(status_parts))

    n_seasons = details.get("number_of_seasons")
    n_episodes = details.get("number_of_episodes")
    if n_seasons and n_episodes:
        lines.append(f"{n_seasons} seasons, {n_episodes} eps")

    creators = [c["name"] for c in details.get("created_by", [])]
    if creators:
        lines.append(", ".join(creators))

    app.show_info_label.configure(text="\n".join(lines))


def show_detail(app, index: int) -> None:
    """Populate the detail panel with rich metadata for the selected item."""
    try:
        _show_detail_impl(app, index)
    except Exception as e:
        # Don't let detail panel errors crash the whole UI
        import traceback
        traceback.print_exc()
        app.detail_header.configure(text="FILE DETAILS")
        app.detail_ep_title.configure(text="Error loading details")
        app.detail_overview.configure(text=str(e))


def _show_detail_impl(app, index: int) -> None:
    """Internal implementation of show_detail."""
    c = app.c
    if index < 0 or index >= len(app.preview_items):
        return
    item = app.preview_items[index]

    is_multi = len(item.episodes) > 1
    is_special = item.season == 0
    is_movie = item.media_type == MediaType.MOVIE

    # Section header
    if is_movie:
        app.detail_header.configure(text="MOVIE DETAILS")
    elif is_special:
        app.detail_header.configure(text="SPECIAL")
    elif is_multi:
        app.detail_header.configure(
            text=f"S{item.season:02d} · EPISODES "
                 + ", ".join(str(e) for e in item.episodes))
    elif item.season is not None and item.episodes:
        app.detail_header.configure(
            text=f"S{item.season:02d}E{item.episodes[0]:02d}")
    else:
        app.detail_header.configure(text="FILE DETAILS")

    # Load content-specific image
    _load_detail_image(app, item)

    # Populate based on media type
    if is_movie:
        _show_movie_detail(app, item)
    else:
        _show_tv_detail(app, item)

    # Rename info card
    app.detail_orig_label.configure(
        text=f"FROM:  {item.original.name}",
        foreground=c["text_dim"],
    )

    if item.new_name:
        new_text = f"TO:  {item.new_name}"
        if item.is_move():
            new_text += f"\nINTO:  {item.target_dir.name}/"
        app.detail_new_label.configure(text=new_text)
    else:
        app.detail_new_label.configure(text="")

    # Status with color coding
    status = item.status
    if status == "OK":
        app.detail_status_label.configure(
            text="✓ Ready to rename", foreground=c["success"])
    elif "UNMATCHED" in status:
        app.detail_status_label.configure(
            text="⚠ No matching TMDB special — will move to Unmatched",
            foreground=c["accent"])
    elif "REVIEW" in status:
        app.detail_status_label.configure(
            text=f"⚠ {status}", foreground=c["accent"])
    elif "CONFLICT" in status:
        app.detail_status_label.configure(
            text=f"✗ {status}", foreground=c["error"])
    elif "SKIP" in status:
        app.detail_status_label.configure(
            text=f"— {status}", foreground=c["text_muted"])
    else:
        app.detail_status_label.configure(
            text=status, foreground=c["text_dim"])

    # Re-match button visibility — placed right after rename card
    if is_movie:
        app.rematch_btn.pack_forget()
        app.rematch_btn.pack(anchor="w", pady=(4, 0), after=app.detail_rename_frame)
    else:
        app.rematch_btn.pack_forget()


# ─── Internal ────────────────────────────────────────────────────────────────

def _show_tv_detail(app, item: PreviewItem) -> None:
    """Populate detail panel with TV episode metadata."""
    c = app.c
    meta = None

    if app.tv_scanner and item.episodes:
        meta = app.tv_scanner.episode_meta.get(
            (item.season, item.episodes[0]))

    if not meta:
        if app.tv_scanner and item.episodes:
            title = app.tv_scanner.episode_titles.get(
                (item.season, item.episodes[0]), "")
            app.detail_ep_title.configure(text=title or "Unknown Episode")
        else:
            app.detail_ep_title.configure(text="")
        app.detail_meta_label.configure(text="")
        app.detail_overview.configure(text="")
        app.detail_crew_label.configure(text="")
        return

    # Episode title
    ep_title = meta.get("name", "")
    if item.episodes and len(item.episodes) == 1:
        display_title = ep_title
    elif item.episodes:
        titles = []
        for ep in item.episodes:
            m = app.tv_scanner.episode_meta.get((item.season, ep))
            if m:
                titles.append(m.get("name", f"Episode {ep}"))
        display_title = " / ".join(titles) if titles else ep_title
    else:
        display_title = ep_title
    app.detail_ep_title.configure(text=display_title)

    # Metadata row
    meta_parts = []
    rating = meta.get("vote_average", 0)
    if rating:
        meta_parts.append(format_rating(rating, meta.get("vote_count", 0)))
    runtime = format_runtime(meta.get("runtime"))
    if runtime:
        meta_parts.append(runtime)
    air_date = meta.get("air_date", "")
    if air_date:
        meta_parts.append(air_date)
    app.detail_meta_label.configure(text="   ·   ".join(meta_parts))

    # Overview
    overview = meta.get("overview", "")
    app.detail_overview.configure(
        text=overview if overview else "No synopsis available.")

    # Crew & guest stars
    crew_parts = []
    directors = meta.get("directors", [])
    if directors:
        crew_parts.append(f"Directed by  {', '.join(directors)}")
    writers = meta.get("writers", [])
    if writers:
        crew_parts.append(f"Written by  {', '.join(writers)}")
    guests = meta.get("guest_stars", [])
    if guests:
        guest_strs = []
        for g in guests[:4]:
            name = g.get("name", "")
            char = g.get("character", "")
            if name and char:
                guest_strs.append(f"{name} as {char}")
            elif name:
                guest_strs.append(name)
        if guest_strs:
            crew_parts.append(f"Guest stars  {', '.join(guest_strs)}")
    app.detail_crew_label.configure(text="\n".join(crew_parts))


def _show_movie_detail(app, item: PreviewItem) -> None:
    """Populate detail panel with movie metadata."""
    c = app.c
    tmdb = app._ensure_tmdb()

    movie_data = (app.movie_scanner.movie_info.get(item.original)
                  if app.movie_scanner else None)

    if not movie_data or not tmdb:
        app.detail_ep_title.configure(text=item.new_name or "")
        app.detail_meta_label.configure(text="")
        app.detail_overview.configure(text="")
        app.detail_crew_label.configure(text="")
        return

    details = tmdb.get_movie_details(movie_data["id"])
    if not details:
        app.detail_ep_title.configure(
            text=f"{movie_data.get('title', '')} ({movie_data.get('year', '')})")
        app.detail_meta_label.configure(text="")
        app.detail_overview.configure(text=movie_data.get("overview", ""))
        app.detail_crew_label.configure(text="")
        return

    # Title + tagline
    title = details.get("title", "")
    year = (details.get("release_date") or "")[:4]
    tagline = details.get("tagline", "")
    title_text = f"{title}" + (f" ({year})" if year else "")
    if tagline:
        title_text += f"\n\"{tagline}\""
    app.detail_ep_title.configure(text=title_text)

    # Metadata row
    meta_parts = []
    vote_avg = details.get("vote_average", 0)
    if vote_avg:
        meta_parts.append(format_rating(vote_avg, details.get("vote_count", 0)))
    runtime = format_runtime(details.get("runtime"))
    if runtime:
        meta_parts.append(runtime)
    release_date = details.get("release_date", "")
    if release_date:
        meta_parts.append(release_date)
    app.detail_meta_label.configure(text="   ·   ".join(meta_parts))

    # Overview
    overview = details.get("overview", "")
    app.detail_overview.configure(
        text=overview if overview else "No synopsis available.")

    # Genres + production info
    info_parts = []
    genres = [g["name"] for g in details.get("genres", [])]
    if genres:
        info_parts.append(" · ".join(genres))
    companies = [co["name"] for co in details.get("production_companies", [])[:3]]
    if companies:
        info_parts.append(", ".join(companies))
    app.detail_crew_label.configure(text="\n".join(info_parts))


def _load_detail_image(app, item: PreviewItem) -> None:
    """Load the appropriate image for the detail panel."""
    tmdb = app._ensure_tmdb()
    if not tmdb or not app.media_info:
        app.detail_image.configure(image="")
        app._detail_img_ref = None
        return

    img = None
    is_movie = item.media_type == MediaType.MOVIE

    if is_movie and app.movie_scanner:
        movie_data = app.movie_scanner.movie_info.get(item.original)
        if movie_data and movie_data.get("poster_path"):
            img = tmdb.fetch_image(movie_data["poster_path"], target_width=400)
    elif app.tv_scanner and item.episodes:
        poster_path = app.tv_scanner.episode_posters.get(
            (item.season, item.episodes[0]))
        if poster_path:
            img = tmdb.fetch_image(poster_path, target_width=400)

    if img:
        app.root.update_idletasks()
        img = scale_to_panel(img, app.detail_inner)
        photo = ImageTk.PhotoImage(img)
        app._detail_img_ref = photo
        app.detail_image.configure(image=photo)
    else:
        app.detail_image.configure(image="")
        app._detail_img_ref = None
