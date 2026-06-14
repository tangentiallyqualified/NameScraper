"""Episode assignment dialog: multi-select slots or pick a file.

Both directions of the fix flow share this module:
  - ``EpisodeAssignDialog`` (file -> episodes, multi-select, contiguity-gated)
  - ``EpisodeAssignDialog.pick_file`` (episode -> file, single-select)

All sizing flows through gui_qt._scale (HiDPI requirement).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .. import _scale
from ...app.models.state_models import EpisodeSlotChoice

_SLOT_ROLE = Qt.ItemDataRole.UserRole


class EpisodeAssignDialog(QDialog):
    """Season-grouped multi-select episode picker with contiguity gating."""

    def __init__(
        self,
        *,
        slots: list[EpisodeSlotChoice],
        parent=None,
        title: str = "Assign Episodes",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(_scale.px(420))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale.margins(8))
        layout.setSpacing(_scale.px(6))

        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        current_season: int | None = None
        for choice in slots:
            if choice.season != current_season:
                current_season = choice.season
                header_text = (
                    "Specials" if choice.season == 0 else f"Season {choice.season:02d}"
                )
                header = QListWidgetItem(header_text)
                header.setFlags(Qt.ItemFlag.NoItemFlags)
                self._list.addItem(header)
            text = choice.label
            if choice.claimed_by:
                text = f"{text}    [claimed by {choice.claimed_by}]"
            else:
                text = f"{text}    [missing]"
            item = QListWidgetItem(text)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(_SLOT_ROLE, (choice.season, choice.episode))
            self._list.addItem(item)
        self._list.itemChanged.connect(lambda _item: self._revalidate())
        layout.addWidget(self._list)

        self._validation = QLabel("", self)
        self._validation.setProperty("cssClass", "caption")
        self._validation.setWordWrap(True)
        layout.addWidget(self._validation)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._revalidate()

    # ── selection state ─────────────────────────────────────────────

    def _checked_keys(self) -> list[tuple[int, int]]:
        keys: list[tuple[int, int]] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            key = item.data(_SLOT_ROLE)
            if key is not None and item.checkState() == Qt.CheckState.Checked:
                keys.append(tuple(key))
        return sorted(keys)

    def selected_episodes(self) -> list[tuple[int, int]]:
        return self._checked_keys()

    def set_checked(self, keys: list[tuple[int, int]]) -> None:
        wanted = set(keys)
        for index in range(self._list.count()):
            item = self._list.item(index)
            key = item.data(_SLOT_ROLE)
            if key is None:
                continue
            item.setCheckState(
                Qt.CheckState.Checked
                if tuple(key) in wanted
                else Qt.CheckState.Unchecked
            )
        self._revalidate()

    def _validate(self) -> str:
        keys = self._checked_keys()
        if not keys:
            return "Select at least one episode."
        seasons = {season for season, _episode in keys}
        if len(seasons) > 1:
            return "All selected episodes must be in the same season."
        episodes = [episode for _season, episode in keys]
        if any(b - a != 1 for a, b in zip(episodes, episodes[1:])):
            return "Selected episodes must be a contiguous run."
        return ""

    def is_selection_valid(self) -> bool:
        return self._validate() == ""

    def validation_text(self) -> str:
        return self._validation.text()

    def slot_row_text(self, season: int, episode: int) -> str:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(_SLOT_ROLE) == (season, episode):
                return item.text()
        return ""

    def _revalidate(self) -> None:
        message = self._validate()
        self._validation.setText(message)
        ok = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setEnabled(message == "")

    # ── entry points ────────────────────────────────────────────────

    @classmethod
    def pick_episodes(
        cls,
        *,
        parent,
        title: str,
        slots: list[EpisodeSlotChoice],
        preselected: list[tuple[int, int]] | None = None,
    ) -> list[tuple[int, int]] | None:
        dialog = cls(slots=slots, parent=parent, title=title)
        if preselected:
            dialog.set_checked(preselected)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selection = dialog.selected_episodes()
        return selection or None

    @staticmethod
    def pick_file(
        *,
        parent,
        title: str,
        unassigned: list[tuple[int, str]],
        assigned: list[tuple[int, str]],
        shareable: list[tuple[int, str]] | None = None,
    ) -> int | None:
        """Single-select file picker; returns the chosen file_id."""
        dialog = QDialog(parent)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(_scale.px(420))
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(_scale.margins(8))
        layout.setSpacing(_scale.px(6))

        list_widget = QListWidget(dialog)

        def add_group(header_text: str, entries: list[tuple[int, str]]) -> None:
            if not entries:
                return
            header = QListWidgetItem(header_text)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            list_widget.addItem(header)
            for file_id, label in entries:
                item = QListWidgetItem(label)
                item.setData(_SLOT_ROLE, file_id)
                list_widget.addItem(item)

        add_group("Unassigned files", unassigned)
        add_group("Share / extend (keeps current episode)", shareable or [])
        add_group("Already assigned (will be reassigned)", assigned)
        list_widget.itemDoubleClicked.connect(lambda _item: dialog.accept())
        layout.addWidget(list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)

        def _update_ok() -> None:
            current = list_widget.currentItem()
            enabled = (
                current is not None
                and bool(current.flags() & Qt.ItemFlag.ItemIsSelectable)
            )
            if ok_btn is not None:
                ok_btn.setEnabled(enabled)

        list_widget.currentItemChanged.connect(lambda _cur, _prev: _update_ok())
        _update_ok()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item = list_widget.currentItem()
        if item is None:
            return None
        file_id = item.data(_SLOT_ROLE)
        return int(file_id) if file_id is not None else None
