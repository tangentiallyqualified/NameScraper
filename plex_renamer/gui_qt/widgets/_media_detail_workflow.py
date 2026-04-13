"""Async selection and payload workflow for MediaDetailPanel."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtGui import QPixmap

from ...engine import PreviewItem, ScanState
from ...thread_pool import submit as _submit_bg
from ._image_utils import raw_to_pixmap
from ._media_detail_state import (
    begin_detail_payload_load,
    cache_detail_payload,
    clear_detail_metadata_cache,
    get_cached_detail_payload,
    make_detail_token,
    selection_preview_pending,
)


def _selection_artwork_mode(preview: PreviewItem | None) -> str:
    return "poster"


class _MediaDetailWorkflowPanel(Protocol):
    _tmdb_provider: Callable[[], object | None] | None
    _settings: Any
    _current_token: str
    _current_state: ScanState | None
    _current_preview: PreviewItem | None
    _current_queue_reason: str
    _current_folder_plan: str
    _poster_pixmap: QPixmap | None
    _metadata_cache: OrderedDict[str, tuple[dict, QPixmap | None]]
    _loading_tokens: set[str]
    _MAX_METADATA_CACHE_ENTRIES: int
    _bridge: Any
    _title: Any
    _subtitle: Any
    _overview: Any
    _extra: Any
    _poster: Any

    def clear(self, text: str = "Choose a roster item to inspect details.") -> None: ...

    def _fallback_rows(
        self,
        state: ScanState,
        preview: PreviewItem | None,
        queue_reason: str,
        folder_plan: str,
    ) -> list[tuple[str, str]]: ...

    def _build_payload(
        self,
        tmdb: Any,
        state: ScanState,
        preview: PreviewItem | None,
        queue_reason: str,
        folder_plan: str,
        target_width: int,
    ): ...

    def _set_artwork_mode(self, mode: str) -> None: ...

    def _show_artwork_placeholder(self, label: str = "", *, loading: bool = False) -> None: ...

    def _set_meta_rows(self, rows: list[tuple[str, str]]) -> None: ...

    def _stop_shimmer(self) -> None: ...

    def _render_poster(self) -> None: ...

    def _artwork_fetch_width(self, mode: str) -> int: ...


class MediaDetailWorkflowCoordinator:
    def __init__(self, panel: _MediaDetailWorkflowPanel) -> None:
        self._panel = panel

    def clear_metadata_cache(self) -> None:
        clear_detail_metadata_cache(self._panel._metadata_cache, self._panel._loading_tokens)

    def set_selection(
        self,
        state: ScanState | None,
        preview: PreviewItem | None = None,
        queue_reason: str = "",
        folder_plan: str = "",
    ) -> None:
        panel = self._panel
        if state is None:
            panel.clear()
            return

        panel._current_state = state
        panel._current_preview = preview
        panel._current_queue_reason = queue_reason
        panel._current_folder_plan = folder_plan
        token = make_detail_token(state, preview, queue_reason, folder_plan)
        panel._current_token = token
        panel._title.setText(state.display_name)

        tmdb = panel._tmdb_provider() if panel._tmdb_provider is not None else None
        if tmdb is None or not state.show_id:
            self._show_fallback_state(
                state,
                preview,
                queue_reason,
                folder_plan,
                subtitle=queue_reason or "TMDB metadata unavailable.",
            )
            return

        if selection_preview_pending(state, preview):
            self._show_fallback_state(
                state,
                preview,
                queue_reason,
                folder_plan,
                subtitle="Preview is still loading...",
            )
            return

        cached = get_cached_detail_payload(panel._metadata_cache, token)
        if cached is not None:
            self.apply_payload(cached[0], cached[1], token)
            return

        artwork_mode = _selection_artwork_mode(preview)
        panel._subtitle.setText(queue_reason or "Fetching metadata...")
        panel._set_artwork_mode(artwork_mode)
        panel._show_artwork_placeholder(state.display_name, loading=True)
        panel._set_meta_rows(panel._fallback_rows(state, preview, queue_reason, folder_plan))
        if not begin_detail_payload_load(panel._loading_tokens, token):
            return

        target_width = panel._artwork_fetch_width(artwork_mode)

        def _worker() -> None:
            payload = panel._build_payload(tmdb, state, preview, queue_reason, folder_plan, target_width)
            try:
                panel._bridge.metadata_ready.emit(payload[0], payload[1], token)
            except RuntimeError:
                pass

        _submit_bg(_worker)

    def refresh_current(self) -> None:
        panel = self._panel
        if panel._current_state is None:
            return
        self.set_selection(
            panel._current_state,
            preview=panel._current_preview,
            queue_reason=panel._current_queue_reason,
            folder_plan=panel._current_folder_plan,
        )

    def apply_payload(self, payload: dict | None, image_data: Any, token: str) -> None:
        panel = self._panel
        panel._loading_tokens.discard(token)
        if payload is None:
            return

        if isinstance(image_data, QPixmap):
            pixmap = image_data
        elif image_data is not None:
            pixmap = raw_to_pixmap(image_data)
        else:
            pixmap = None

        cache_detail_payload(
            panel._metadata_cache,
            token,
            payload,
            pixmap,
            max_entries=panel._MAX_METADATA_CACHE_ENTRIES,
        )
        if token != panel._current_token:
            return

        panel._stop_shimmer()
        panel._title.setText(payload.get("title", "Selection"))
        panel._subtitle.setText(payload.get("subtitle", ""))
        panel._overview.setText(payload.get("overview", ""))
        panel._extra.setText(payload.get("extra", ""))
        panel._set_artwork_mode(payload.get("artwork_mode", "poster"))
        panel._set_meta_rows(payload.get("rows", []))

        if pixmap is None or pixmap.isNull():
            panel._poster_pixmap = None
            panel._show_artwork_placeholder(payload.get("title", "Selection"))
            return

        panel._poster_pixmap = pixmap
        panel._poster.setText("")
        panel._render_poster()

    def _show_fallback_state(
        self,
        state: ScanState,
        preview: PreviewItem | None,
        queue_reason: str,
        folder_plan: str,
        *,
        subtitle: str,
    ) -> None:
        panel = self._panel
        panel._poster_pixmap = None
        panel._set_artwork_mode(_selection_artwork_mode(preview))
        panel._overview.setText("")
        panel._extra.setText("")
        panel._subtitle.setText(subtitle)
        panel._show_artwork_placeholder(state.display_name)
        panel._set_meta_rows(panel._fallback_rows(state, preview, queue_reason, folder_plan))
