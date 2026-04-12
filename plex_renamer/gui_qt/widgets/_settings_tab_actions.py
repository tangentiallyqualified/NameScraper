"""Action and status helpers for the settings tab."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import QWidget


class SettingsTabActionsCoordinator:
    def __init__(self, tab: Any) -> None:
        self._tab = tab

    def clear_history(self, *, message_box_api: Any) -> None:
        tab = self._tab
        if tab._clear_history_callback is None:
            return
        if message_box_api.question(
            tab,
            "Clear Job History",
            "Delete all job history entries?\n\nStored undo data for revertible jobs will be lost.",
        ) != message_box_api.StandardButton.Yes:
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
        if not key:
            self.set_key_status("Please enter an API key.", "error")
            return

        try:
            from ...keys import save_api_key

            save_api_key("TMDB", key)
            self.set_key_status("API key saved.", "success")
            tab.api_key_saved.emit()
        except Exception as exc:
            self.set_key_status(f"Save failed: {exc}", "error")

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

            try:
                bridge.result_ready.emit(ok, detail)
            except RuntimeError:
                pass

        submit_bg(_test_worker)

    def show_test_result(self, success: bool, detail: str) -> None:
        tab = self._tab
        tab._test_key_btn.setEnabled(True)
        if success:
            self.set_key_status("TMDB connection successful.", "success")
            return
        self.set_key_status(f"TMDB test failed: {detail}", "error")

    def clear_cache(self) -> None:
        tab = self._tab
        if tab._cache_service is None:
            return

        removed = tab._cache_service.invalidate_namespace("tmdb")
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

        stats = tab._cache_service.stats()
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
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def repolish_widget(widget: QWidget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
