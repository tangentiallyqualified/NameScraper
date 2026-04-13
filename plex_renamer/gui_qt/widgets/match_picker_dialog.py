"""Dialog for choosing or searching TMDB matches in the Qt shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ._match_picker_search import MatchPickerSearchCoordinator
from ._match_picker_selection import MatchPickerSelectionCoordinator


class _SearchBridge(QObject):
    """Thread-safe bridge for TMDB search results."""

    results_ready = Signal(object)


class MatchPickerDialog(QDialog):
    """Pick from cached TMDB results or run a new search."""

    def __init__(
        self,
        *,
        title: str,
        title_key: str,
        initial_query: str,
        initial_results: list[dict],
        search_callback: Callable[[str, str | None], list[dict]],
        score_results_callback: Callable[[list[dict]], list[tuple[dict, float]]] | None = None,
        year_hint: str | None = None,
        raw_name: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 520)
        self._title_key = title_key
        self._search_callback = search_callback
        self._score_results_callback = score_results_callback
        self._year_hint = year_hint
        self._raw_name = raw_name or initial_query
        self._selected: dict | None = None
        self._results: list[dict] = []
        self._search_in_progress = False
        self._search_bridge = _SearchBridge(self)
        self._search_workflow = MatchPickerSearchCoordinator(self)
        self._selection_workflow = MatchPickerSelectionCoordinator(self)
        self._search_bridge.results_ready.connect(self._on_search_results)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        helper = QLabel("Choose an existing result or search TMDB again.")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        search_row = QHBoxLayout()
        self._query = QLineEdit(initial_query)
        self._query.setPlaceholderText("Search TMDB")
        search_row.addWidget(self._query, stretch=1)

        self._search_button = QPushButton("Search")
        self._search_button.setAutoDefault(False)
        self._search_button.setDefault(False)
        self._search_button.clicked.connect(self._run_search)
        search_row.addWidget(self._search_button)
        layout.addLayout(search_row)

        self._result_list = QListWidget()
        self._result_list.itemDoubleClicked.connect(lambda _item: self.accept())
        self._result_list.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self._result_list, stretch=1)

        self._overview = QLabel("")
        self._overview.setWordWrap(True)
        self._overview.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._overview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok_button.setAutoDefault(False)
        self._ok_button.setDefault(False)
        self._ok_button.setEnabled(False)
        layout.addWidget(buttons)

        self._set_results(initial_results)

    @property
    def selected_result(self) -> dict | None:
        return self._selected

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.focusWidget() is self._query:
            self._run_search()
            event.accept()
            return
        super().keyPressEvent(event)

    def _run_search(self) -> None:
        self._search_workflow.run_search()

    def _on_search_results(self, results: list[dict]) -> None:
        self._search_workflow.apply_search_results(results)

    def accept(self) -> None:
        if self._search_in_progress:
            return
        super().accept()

    def _set_results(self, results: list[dict]) -> None:
        self._selection_workflow.set_results(results)

    def _on_current_item_changed(self, current, _previous) -> None:
        self._selection_workflow.apply_current_item(current)

    @classmethod
    def pick(
        cls,
        *,
        title: str,
        title_key: str,
        initial_query: str,
        initial_results: list[dict],
        search_callback: Callable[[str, str | None], list[dict]],
        score_results_callback: Callable[[list[dict]], list[tuple[dict, float]]] | None = None,
        year_hint: str | None = None,
        raw_name: str | None = None,
        parent: QWidget | None = None,
    ) -> dict | None:
        dialog = cls(
            title=title,
            title_key=title_key,
            initial_query=initial_query,
            initial_results=initial_results,
            search_callback=search_callback,
            score_results_callback=score_results_callback,
            year_hint=year_hint,
            raw_name=raw_name,
            parent=parent,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_result
        return None
