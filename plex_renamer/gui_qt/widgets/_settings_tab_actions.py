"""Action and status helpers for the settings tab."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QWidget

_TMDB_CACHE_NAMESPACE_PREFIX = "tmdb"


class SettingsTabActionsCoordinator:
    def __init__(self, tab: Any) -> None:
        self._tab = tab

    def clear_history(self, *, message_box_api: Any) -> None:
        tab = self._tab
        if tab._clear_history_callback is None:
            return
        pending = tab._history_count_callback() if tab._history_count_callback is not None else None
        if pending == 0:
            tab._history_confirm.setProperty("tone", "success")
            tab._history_confirm.setText("History is already empty.")
            repolish_widget(tab._history_confirm)
            return
        if pending is None:
            prompt = "Delete all job history entries?"
        else:
            noun = "entry" if pending == 1 else "entries"
            prompt = f"Delete {pending} job history {noun}?"
        if (
            message_box_api.question(
                tab,
                "Clear Job History",
                prompt + "\n\nStored undo data for revertible jobs will be lost.",
            )
            != message_box_api.StandardButton.Yes
        ):
            tab._history_confirm.setText("")
            return

        count, _revertible = tab._clear_history_callback()
        noun = "entry" if count == 1 else "entries"
        tab._history_confirm.setProperty("tone", "success")
        tab._history_confirm.setText(f"Cleared {count} history {noun}.")
        repolish_widget(tab._history_confirm)
        tab.history_cleared.emit()

    def save_key(self) -> None:
        tab = self._tab
        key = tab._api_key_input.text().strip()
        tvdb_key = tab._tvdb_key_input.text().strip()
        if not key and not tvdb_key:
            self.set_key_status("Please enter an API key.", "error")
            return

        try:
            from ...keys import save_api_key

            # The two saves are independent: a TVDB-only user (empty TMDB
            # field) must not be blocked by the TMDB branch, and vice versa.
            if key:
                save_api_key("TMDB", key)
            if tvdb_key:
                save_api_key("TVDB", tvdb_key)

            self.set_key_status("API key saved.", "success")
            tab.api_key_saved.emit()
            self.refresh_fallback_availability()
        except Exception as exc:
            self.set_key_status(f"Save failed: {exc}", "error")

    def on_tv_source_changed(self, index: int) -> None:
        tab = self._tab
        if tab._settings is None:
            return
        tab._settings.tv_metadata_source = str(tab._tv_source_combo.itemData(index))
        tab.api_key_saved.emit()  # drops cached clients; next scan uses the new source
        self.refresh_fallback_availability()

    def on_fallback_toggled(self, checked: bool) -> None:
        tab = self._tab
        if tab._settings is None:
            return
        tab._settings.tv_fallback_enabled = checked

    def on_id_tag_routing_toggled(self, checked: bool) -> None:
        tab = self._tab
        if tab._settings is None:
            return
        tab._settings.tv_id_tag_routing_enabled = checked

    def refresh_fallback_availability(self) -> None:
        """Disable the fallback checkbox (with an explanatory tooltip) when
        the non-active TV provider has no API key on file."""
        tab = self._tab
        if tab._settings is None or not hasattr(tab, "_fallback_cb"):
            return
        from ...providers import TV_PROVIDERS, get_tv_provider_spec

        active = get_tv_provider_spec(tab._settings.tv_metadata_source).name
        other = next((spec for name, spec in TV_PROVIDERS.items() if name != active), None)
        available = False
        if other is not None:
            try:
                from ...keys import get_api_key

                available = bool(get_api_key(other.key_service))
            except Exception:
                available = False
        tab._fallback_cb.setEnabled(available)
        tab._fallback_cb.setToolTip("" if available else "Requires an API key for the other source")

    def test_key(self, *, submit_bg: Callable[[Callable[[], None]], Any]) -> None:
        tab = self._tab
        key = tab._api_key_input.text().strip()
        if not key:
            self.set_key_status("Enter a key first.", "error")
            return

        self.set_key_status("Testing...", "muted")
        tab._test_key_btn.setEnabled(False)
        bridge = tab._api_test_bridge

        def _test_worker() -> None:
            try:
                import requests

                response = requests.get(
                    "https://api.themoviedb.org/3/configuration",
                    params={"api_key": key},
                    timeout=5,
                )
                ok = response.ok
                detail = "" if ok else str(response.status_code)
            except Exception as exc:
                ok = False
                detail = str(exc)

            with contextlib.suppress(RuntimeError):
                bridge.result_ready.emit(ok, detail)

        submit_bg(_test_worker)

    def show_test_result(self, success: bool, detail: str) -> None:
        tab = self._tab
        tab._test_key_btn.setEnabled(True)
        if success:
            self.set_key_status("TMDB connection successful.", "success")
            return
        self.set_key_status(f"TMDB test failed: {detail}", "error")

    def clear_cache(self, *, message_box_api: Any) -> None:
        tab = self._tab
        if tab._cache_service is None:
            return
        stats = tab._cache_service.stats(namespace_prefix=_TMDB_CACHE_NAMESPACE_PREFIX)
        pending = int(stats["item_count"])
        if pending == 0:
            tab._cache_confirm.setProperty("tone", "success")
            tab._cache_confirm.setText("TMDB cache is already empty.")
            repolish_widget(tab._cache_confirm)
            return
        noun = "entry" if pending == 1 else "entries"
        if (
            message_box_api.question(
                tab,
                "Clear TMDB Cache",
                f"Delete {pending} cached TMDB {noun}?\n\n"
                "Posters and show details will be re-fetched on the next scan.",
            )
            != message_box_api.StandardButton.Yes
        ):
            tab._cache_confirm.setText("")
            return

        removed = tab._cache_service.invalidate_namespace_prefix(_TMDB_CACHE_NAMESPACE_PREFIX)
        if tab._clear_tmdb_callback is not None:
            tab._clear_tmdb_callback()
        noun = "entry" if removed == 1 else "entries"
        tab._cache_confirm.setProperty("tone", "success")
        tab._cache_confirm.setText(f"Cleared {removed} TMDB cache {noun}.")
        repolish_widget(tab._cache_confirm)
        self.refresh_cache_stats()

    def refresh_cache_stats(self) -> None:
        tab = self._tab
        if tab._cache_service is None:
            tab._cache_stats.setText("Cache actions are unavailable in this context.")
            return

        stats = tab._cache_service.stats(namespace_prefix=_TMDB_CACHE_NAMESPACE_PREFIX)
        tab._cache_stats.setText(
            f"{stats['item_count']} entries · {format_bytes(stats['total_size_bytes'])} used "
            f"· cap {format_bytes(stats['max_size_bytes'])} / {stats['max_items']} items"
        )

    def set_key_status(self, text: str, tone: str) -> None:
        tab = self._tab
        tab._key_status.setText(text)
        tab._key_status.setProperty("tone", tone)
        repolish_widget(tab._key_status)


def format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024**3:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024**3):.1f} GB"


def repolish_widget(widget: QWidget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
