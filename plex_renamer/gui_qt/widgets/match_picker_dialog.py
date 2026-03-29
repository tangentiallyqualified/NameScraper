"""Dialog for choosing or searching TMDB matches in the Qt shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
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


def _label_for_result(result: dict, title_key: str) -> str:
    title = result.get(title_key) or result.get("name") or result.get("title") or "Unknown"
    year = result.get("year", "")
    return f"{title} ({year})" if year else title


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
        year_hint: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 520)
        self._title_key = title_key
        self._search_callback = search_callback
        self._year_hint = year_hint
        self._selected: dict | None = None
        self._results: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        helper = QLabel("Choose an existing result or search TMDB again.")
        helper.setWordWrap(True)
        layout.addWidget(helper)

        search_row = QHBoxLayout()
        self._query = QLineEdit(initial_query)
        self._query.setPlaceholderText("Search TMDB")
        self._query.returnPressed.connect(self._run_search)
        search_row.addWidget(self._query, stretch=1)

        self._search_button = QPushButton("Search")
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
        self._ok_button.setEnabled(False)
        layout.addWidget(buttons)

        self._set_results(initial_results)

    @property
    def selected_result(self) -> dict | None:
        return self._selected

    def _run_search(self) -> None:
        query = self._query.text().strip()
        if not query:
            QMessageBox.information(self, "Search Required", "Enter a title to search TMDB.")
            return
        results = self._search_callback(query, self._year_hint)
        if not results and self._year_hint:
            results = self._search_callback(query, None)
        self._set_results(results)

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

        for index, result in enumerate(results):
            item = QListWidgetItem(_label_for_result(result, self._title_key))
            item.setData(Qt.ItemDataRole.UserRole, index)
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
        year_hint: str | None = None,
        parent: QWidget | None = None,
    ) -> dict | None:
        dialog = cls(
            title=title,
            title_key=title_key,
            initial_query=initial_query,
            initial_results=initial_results,
            search_callback=search_callback,
            year_hint=year_hint,
            parent=parent,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_result
        return None