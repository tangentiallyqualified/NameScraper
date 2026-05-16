"""Artwork helpers for MediaDetailPanel poster and still presentation."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QWidget

from ._image_utils import (
    ShimmerOverlay,
    build_placeholder_pixmap,
    scale_pixmap_for_device,
)


def normalize_artwork_mode(mode: str) -> str:
    return "still" if mode == "still" else "poster"


def detail_artwork_device_pixel_ratio(poster: QLabel) -> float:
    try:
        return max(1.0, float(poster.devicePixelRatioF()))
    except Exception:
        return 1.0


def set_detail_artwork_mode(
    poster: QLabel,
    facts_card: QWidget | None,
    mode: str,
    *,
    portrait_size: QSize,
    landscape_size: QSize,
) -> str:
    normalized = normalize_artwork_mode(mode)
    size = landscape_size if normalized == "still" else portrait_size
    poster.setFixedSize(size)
    if facts_card is not None:
        facts_card.setFixedHeight(poster.height())
    return normalized


def render_detail_artwork(
    poster: QLabel,
    pixmap,
    mode: str,
    *,
    portrait_size: QSize,
    landscape_size: QSize,
) -> None:
    if pixmap is None or pixmap.isNull():
        return
    target = poster.contentsRect().size()
    if not target.isValid():
        target = landscape_size if mode == "still" else portrait_size
    scaled = scale_pixmap_for_device(
        pixmap,
        target,
        device_pixel_ratio=detail_artwork_device_pixel_ratio(poster),
    )
    poster.setPixmap(scaled)


def stop_detail_shimmer(shimmer: ShimmerOverlay | None) -> None:
    if shimmer is not None:
        shimmer.stop()


def show_detail_artwork_placeholder(
    poster: QLabel,
    shimmer: ShimmerOverlay | None,
    mode: str,
    *,
    label: str = "",
    loading: bool = False,
    portrait_size: QSize,
    landscape_size: QSize,
) -> ShimmerOverlay | None:
    subtitle = "No Episode Image" if mode == "still" else "No Poster"
    title = "EPISODE" if mode == "still" else (label or "TMDB")
    if mode != "still" and label:
        title = label.split(" (", 1)[0]

    size = poster.size() if poster.size().isValid() else (
        landscape_size if mode == "still" else portrait_size
    )
    placeholder = build_placeholder_pixmap(
        size,
        title=title,
        subtitle=subtitle,
        accent="#4a9eda" if mode == "still" else "#e5a00d",
        device_pixel_ratio=detail_artwork_device_pixel_ratio(poster),
    )
    poster.setPixmap(placeholder)
    poster.setText("")

    if loading:
        return shimmer or ShimmerOverlay(poster)

    stop_detail_shimmer(shimmer)
    return None


def detail_artwork_fetch_width(
    poster: QLabel,
    mode: str,
    *,
    portrait_size: QSize,
    landscape_size: QSize,
) -> int:
    logical = landscape_size if mode == "still" else portrait_size
    ratio = detail_artwork_device_pixel_ratio(poster)
    return max(500, min(1100, int(round(logical.width() * ratio * 1.6))))
