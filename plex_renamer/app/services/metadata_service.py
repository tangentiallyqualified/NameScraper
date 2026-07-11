"""Metadata/artwork export planning (spec: local-metadata-artwork).

Qt-free. Plans are baked into jobs at queue-submission time from the
already-hot TMDB caches (mirroring automux_service mux plans); the
executor's decorate phase consumes the serialized plan without any
metadata API access.
"""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from ..._mkv_locate import find_mkvpropedit
from ..._nfo_render import (
    render_episode_nfo,
    render_movie_nfo,
    render_tvshow_nfo,
)
from ..._tmdb_metadata_builder import select_logo_path
from ...constants import MediaType

log = logging.getLogger(__name__)


def metadata_active(svc) -> bool:
    """Metadata export runs only when the master switch is on."""
    return svc is not None and bool(svc.metadata_enabled)


def _posix(relative: str) -> PurePosixPath:
    return PurePosixPath(str(relative).replace("\\", "/"))


def _selected_video_ops(job) -> list:
    return [
        op for op in job.rename_ops
        if op.selected and op.file_type == "video" and op.new_name
        and (op.status == "OK" or op.status.startswith("REVIEW"))
    ]


def _show_root(job, video_ops) -> PurePosixPath:
    if job.show_folder_rename:
        return PurePosixPath(job.show_folder_rename)
    first = _posix(video_ops[0].target_dir_relative)
    return PurePosixPath(first.parts[0]) if first.parts else PurePosixPath(".")


def _art(plan: dict, tmdb_path, target: PurePosixPath, kind: str,
         slot: str, plex_extra: bool = False) -> None:
    plan["artwork"].append({
        "tmdb_path": tmdb_path or None,
        "target_relative": str(target),
        "kind": kind,
        "slot": slot,
        "plex_extra": plex_extra,
    })


def _nfo(plan: dict, content: str, target: PurePosixPath, slot: str) -> None:
    plan["nfo_files"].append({
        "target_relative": str(target),
        "content": content,
        "slot": slot,
    })


def build_metadata_plan(job, tmdb_client, svc) -> dict | None:
    """Serializable MetadataPlan for one job, or None when inapplicable.

    Artwork entries may carry tmdb_path=None (enabled slot, no TMDB
    asset) so the prefer-local pass can still fulfill them; call
    finalize_plan() afterwards to drop leftover placeholders.
    """
    if not metadata_active(svc) or tmdb_client is None or not job.tmdb_id:
        return None
    video_ops = _selected_video_ops(job)
    if not video_ops:
        return None

    propedit = find_mkvpropedit(getattr(svc, "mkvmerge_path", "") or "")
    plan: dict = {
        "nfo_files": [],
        "artwork": [],
        "embed_title": bool(svc.metadata_embed_title),
        "prefer_local": bool(svc.metadata_prefer_local),
        "plex_naming": bool(svc.metadata_plex_naming),
        "mkvpropedit_path": str(propedit) if propedit else "",
    }

    if job.media_type == MediaType.TV:
        _populate_tv(plan, job, video_ops, tmdb_client, svc)
    else:
        _populate_movie(plan, job, video_ops, tmdb_client, svc)
    return plan


def _populate_common_art(plan, details, root, svc, client, poster_hint) -> None:
    if svc.metadata_write_poster:
        poster = poster_hint or details.get("poster_path")
        _art(plan, poster, root / "poster.jpg", "poster", "poster")
    if svc.metadata_write_fanart:
        _art(plan, details.get("backdrop_path"), root / "fanart.jpg",
             "fanart", "fanart")
    if svc.metadata_write_clearlogo:
        logo = select_logo_path(details, getattr(client, "language", "en-US"))
        _art(plan, logo, root / "clearlogo.png", "clearlogo", "clearlogo")


def _populate_tv(plan, job, video_ops, client, svc) -> None:
    details = client.get_tv_details(job.tmdb_id) or {}
    root = _show_root(job, video_ops)

    if svc.metadata_write_nfo and details:
        _nfo(plan, render_tvshow_nfo(details), root / "tvshow.nfo", "nfo:show")

    _populate_common_art(plan, details, root, svc, client, job.poster_path)

    seasons = sorted({op.season for op in video_ops if op.season is not None})
    payloads = {sn: client.get_season(job.tmdb_id, sn) or {} for sn in seasons}

    if svc.metadata_write_season_posters:
        for sn in seasons:
            season_poster = payloads[sn].get("season_poster_path")
            slot = f"season_poster:{sn}"
            name = ("season-specials-poster.jpg" if sn == 0
                    else f"season{sn:02d}-poster.jpg")
            _art(plan, season_poster, root / name, "season_poster", slot)
            if plan["plex_naming"]:
                season_dir = _season_dir(video_ops, sn)
                if season_dir is not None:
                    _art(plan, season_poster,
                         season_dir / f"Season{sn:02d}.jpg",
                         "season_poster", slot, plex_extra=True)

    for op in video_ops:
        if op.season is None or not op.episodes:
            continue
        episodes_meta = payloads.get(op.season, {}).get("episodes") or {}
        stem = _posix(op.new_name).stem
        target_dir = _posix(op.target_dir_relative)

        if svc.metadata_write_episode_nfo:
            blocks = [
                {"season": op.season, "episode": ep,
                 "meta": episodes_meta.get(ep) or {}}
                for ep in op.episodes
            ]
            if any(block["meta"] for block in blocks):
                _nfo(plan, render_episode_nfo(blocks),
                     target_dir / f"{stem}.nfo",
                     f"nfo:episode:{op.original_relative}")

        if svc.metadata_write_episode_thumbs:
            still = (episodes_meta.get(op.episodes[0]) or {}).get("still_path")
            slot = f"episode_thumb:{op.original_relative}"
            _art(plan, still, target_dir / f"{stem}-thumb.jpg",
                 "episode_thumb", slot)
            if plan["plex_naming"]:
                _art(plan, still, target_dir / f"{stem}.jpg",
                     "episode_thumb", slot, plex_extra=True)


def _season_dir(video_ops, season: int) -> PurePosixPath | None:
    for op in video_ops:
        if op.season == season:
            return _posix(op.target_dir_relative)
    return None


def _populate_movie(plan, job, video_ops, client, svc) -> None:
    details = client.get_movie_details(job.tmdb_id) or {}
    op = video_ops[0]
    root = _posix(op.target_dir_relative)
    stem = _posix(op.new_name).stem

    if svc.metadata_write_nfo and details:
        _nfo(plan, render_movie_nfo(details), root / f"{stem}.nfo", "nfo:show")

    _populate_common_art(plan, details, root, svc, client, job.poster_path)


def finalize_plan(plan: dict | None) -> dict | None:
    """Drop unfulfilled artwork placeholders; None when nothing remains."""
    if not plan:
        return None
    plan["artwork"] = [a for a in plan["artwork"] if a.get("tmdb_path")]
    if not plan["nfo_files"] and not plan["artwork"] and not plan["embed_title"]:
        return None
    return plan
