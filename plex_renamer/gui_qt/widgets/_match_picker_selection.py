"""Selection and list-state helpers for MatchPickerDialog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QListWidgetItem

from ._match_picker_results import build_match_picker_result_entries

_NO_RESULTS_TEXT = "No results"
_NO_SYNOPSIS_TEXT = "No synopsis available."
_SUCCESS_COLOR = QColor("#3ea463")


class _MatchPickerSelectionDialog(Protocol):
    _title_key: str
    _score_results_callback: Callable[[list[dict]], list[tuple[dict, float]]] | None
    _year_hint: str | None
    _raw_name: str
    _selected: dict | None
    _results: list[dict]
    _result_list: Any
    _overview: Any
    _ok_button: Any


class MatchPickerSelectionCoordinator:
    def __init__(self, dialog: _MatchPickerSelectionDialog) -> None:
        self._dialog = dialog

    def set_results(self, results: list[dict]) -> None:
        dialog = self._dialog
        dialog._results = list(results)
        dialog._selected = None
        dialog._result_list.clear()
        dialog._overview.setText("")
        dialog._ok_button.setEnabled(False)

        if not results:
            dialog._result_list.addItem(_NO_RESULTS_TEXT)
            dialog._result_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            return

        entries = build_match_picker_result_entries(
            results,
            title_key=dialog._title_key,
            raw_name=dialog._raw_name,
            year_hint=dialog._year_hint,
            score_results_callback=dialog._score_results_callback,
        )
        for entry in entries:
            item = QListWidgetItem(entry.label)
            item.setData(Qt.ItemDataRole.UserRole, entry.index)
            if entry.highlight:
                item.setForeground(_SUCCESS_COLOR)
            if entry.overview:
                item.setToolTip(entry.overview)
            dialog._result_list.addItem(item)

        dialog._result_list.setCurrentRow(0)

    def apply_current_item(self, current: QListWidgetItem | None) -> None:
        dialog = self._dialog
        if current is None:
            dialog._selected = None
            dialog._overview.setText("")
            dialog._ok_button.setEnabled(False)
            return

        index = current.data(Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= index < len(dialog._results)):
            dialog._selected = None
            dialog._overview.setText("")
            dialog._ok_button.setEnabled(False)
            return

        dialog._selected = dialog._results[index]
        dialog._overview.setText(dialog._selected.get("overview", _NO_SYNOPSIS_TEXT))
        dialog._ok_button.setEnabled(True)
