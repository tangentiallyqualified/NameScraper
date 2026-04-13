"""Async search workflow for MatchPickerDialog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ...thread_pool import submit as _submit_bg


class _MatchPickerSearchDialog(Protocol):
    _search_callback: Callable[[str, str | None], list[dict]]
    _year_hint: str | None
    _selected: dict | None
    _search_in_progress: bool
    _search_bridge: Any
    _query: Any
    _search_button: Any
    _result_list: Any
    _overview: Any
    _ok_button: Any

    def _set_results(self, results: list[dict]) -> None: ...


class MatchPickerSearchCoordinator:
    def __init__(self, dialog: _MatchPickerSearchDialog) -> None:
        self._dialog = dialog

    def run_search(self) -> bool:
        dialog = self._dialog
        query = dialog._query.text().strip()
        if not query:
            QMessageBox.information(dialog, "Search Required", "Enter a title to search TMDB.")
            return False

        dialog._search_in_progress = True
        dialog._search_button.setEnabled(False)
        dialog._query.setEnabled(False)
        dialog._result_list.setEnabled(False)

        if dialog._selected is None:
            dialog._result_list.clear()
            dialog._result_list.addItem("Searching...")
            dialog._result_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            dialog._overview.setText("")
            dialog._ok_button.setEnabled(False)
        else:
            dialog._overview.setText("Searching...")

        callback = dialog._search_callback
        year_hint = dialog._year_hint
        bridge = dialog._search_bridge

        def _worker() -> None:
            try:
                results = callback(query, year_hint)
                if not results and year_hint:
                    results = callback(query, None)
            except Exception:
                results = []
            try:
                bridge.results_ready.emit(results)
            except RuntimeError:
                pass

        _submit_bg(_worker)
        return True

    def apply_search_results(self, results: list[dict]) -> None:
        dialog = self._dialog
        dialog._search_in_progress = False
        dialog._search_button.setEnabled(True)
        dialog._query.setEnabled(True)
        dialog._result_list.setEnabled(True)
        dialog._set_results(results)
