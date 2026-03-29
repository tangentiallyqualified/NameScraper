"""Compact segmented control widget for toolbar-style filters."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget


class SegmentedControl(QWidget):
    """Exclusive segmented buttons keyed by their visible labels."""

    currentTextChanged = Signal(str)

    def __init__(
        self,
        options: Iterable[str],
        *,
        current_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "segmented-control")
        self._buttons: dict[str, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonToggled.connect(self._on_button_toggled)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        option_list = list(options)
        for index, text in enumerate(option_list):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("cssClass", "segment")
            if index == 0:
                button.setProperty("segmentPosition", "first")
            elif index == len(option_list) - 1:
                button.setProperty("segmentPosition", "last")
            else:
                button.setProperty("segmentPosition", "middle")
            self._buttons[text] = button
            self._group.addButton(button)
            layout.addWidget(button)

        initial = current_text if current_text in self._buttons else (option_list[0] if option_list else None)
        if initial is not None:
            self.setCurrentText(initial)

    def currentText(self) -> str:
        checked = self._group.checkedButton()
        return checked.text() if checked is not None else ""

    def setCurrentText(self, text: str) -> None:
        button = self._buttons.get(text)
        if button is None:
            return
        if button.isChecked():
            return
        button.setChecked(True)

    def _on_button_toggled(self, button: QPushButton, checked: bool) -> None:
        if checked:
            self.currentTextChanged.emit(button.text())