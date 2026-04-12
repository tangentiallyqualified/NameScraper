"""Dialog for choosing or searching TMDB matches in the Qt shell."""

from __future__ import annotations

from ...thread_pool import submit as _submit_bg
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...engine import score_results
from ._formatting import percent_text

_AUTO_ACCEPT_THRESHOLD = 0.70
_SUCCESS_COLOR = QColor("#3ea463")


def _label_for_result(result: dict, title_key: str, score: float | None = None) -> str:
    title = result.get(title_key) or result.get("name") or result.get("title") or "Unknown"
    year = result.get("year", "")
    label = f"{title} ({year})" if year else title
    if score is not None:
        label += f" \u2014 {percent_text(score)}"
    return label


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
        query = self._query.text().strip()
        if not query:
            QMessageBox.information(self, "Search Required", "Enter a title to search TMDB.")
            return
        self._search_in_progress = True
        self._search_button.setEnabled(False)
        self._query.setEnabled(False)
        self._result_list.setEnabled(False)

        if self._selected is None:
            self._result_list.clear()
            self._result_list.addItem("Searching...")
            self._result_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            self._overview.setText("")
            self._ok_button.setEnabled(False)
        else:
            self._overview.setText("Searching...")

        callback = self._search_callback
        year_hint = self._year_hint
        bridge = self._search_bridge

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
                pass  # Dialog closed before search finished

        _submit_bg(_worker)

    def _on_search_results(self, results: list[dict]) -> None:
        self._search_in_progress = False
        self._search_button.setEnabled(True)
        self._query.setEnabled(True)
        self._result_list.setEnabled(True)
        self._set_results(results)

    def accept(self) -> None:
        if self._search_in_progress:
            return
        super().accept()

    def _set_results(self, results: list[dict]) -> None:
        self._results = list(results)
        self._selected = None
        self._result_list.clear()
        self._overview.setText("")
        self._ok_button.setEnabled(False)

        if not results:
            self._result_list.addItem("No results")
            self._result_list.item(0).setFlags(Qt.ItemFlag.NoItemFlags)
            return

        if self._score_results_callback is not None:
            scored = self._score_results_callback(results)
        else:
            scored = score_results(results, self._raw_name, self._year_hint, title_key=self._title_key)
        score_map = {id(r): s for r, s in scored}

        max_score = max((s for s in score_map.values() if s is not None), default=0.0)
        rescale = 1.0 / max_score if max_score > 1.0 else 1.0

        for index, result in enumerate(results):
            raw_score = score_map.get(id(result))
            display_score = raw_score * rescale if raw_score is not None else None
            item = QListWidgetItem(_label_for_result(result, self._title_key, display_score))
            item.setData(Qt.ItemDataRole.UserRole, index)
            if raw_score is not None and raw_score >= _AUTO_ACCEPT_THRESHOLD:
                item.setForeground(_SUCCESS_COLOR)
            overview = result.get("overview", "")
            if overview:
                item.setToolTip(overview)
            self._result_list.addItem(item)

        self._result_list.setCurrentRow(0)

    def _on_current_item_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            self._selected = None
            self._overview.setText("")
            self._ok_button.setEnabled(False)
            return
        index = current.data(Qt.ItemDataRole.UserRole)
        if index is None or not (0 <= index < len(self._results)):
            self._selected = None
            self._overview.setText("")
            self._ok_button.setEnabled(False)
            return
        self._selected = self._results[index]
        self._overview.setText(self._selected.get("overview", "No synopsis available."))
        self._ok_button.setEnabled(True)

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
