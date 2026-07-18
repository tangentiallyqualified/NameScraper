"""Episode assignment dialog: multi-select slots or pick a file.

Both directions of the fix flow share this module:
  - ``EpisodeAssignDialog`` (file -> episodes, multi-select, contiguity-gated)
  - ``EpisodeAssignDialog.pick_file`` (episode -> file, single-select)

Season groups are collapsible (``QTreeWidget``). All sizing flows through
gui_qt._scale (HiDPI requirement); long rows elide (no horizontal scrollbar).
"""

from __future__ import annotations

import itertools

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...app.models.state_models import EpisodeSlotChoice
from .. import _scale

_SLOT_ROLE = Qt.ItemDataRole.UserRole
_MIN_W = 460
_MIN_H = 420


def _dialog_size() -> tuple[int, int]:
    """Comfortable, DPI-aware (width, height) capped to the screen."""
    min_w, min_h = _scale.px(_MIN_W), _scale.px(_MIN_H)
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return min_w, min_h
    avail = screen.availableGeometry()
    width = min(int(avail.width() * 0.5), _scale.px(620))
    height = min(int(avail.height() * 0.6), _scale.px(640))
    return max(width, min_w), max(height, min_h)


def _season_header(season: int, count: int) -> str:
    label = "Specials" if season == 0 else f"Season {season:02d}"
    return f"{label} ({count})"


def _configure_tree(tree: QTreeWidget) -> None:
    tree.setColumnCount(1)
    tree.setHeaderHidden(True)
    tree.setUniformRowHeights(True)
    tree.setIndentation(_scale.px(12))
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)


def _file_name_label(file_label: str, parent) -> QLabel:
    label = QLabel(file_label, parent)
    label.setProperty("cssClass", "caption")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


class EpisodeAssignDialog(QDialog):
    """Season-grouped, collapsible multi-select episode picker."""

    def __init__(
        self,
        *,
        slots: list[EpisodeSlotChoice],
        parent=None,
        title: str = "Assign Episodes",
        file_label: str = "",
        current_keys: set[tuple[int, int]] | None = None,
        preselected: list[tuple[int, int]] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        current = set(current_keys or set())
        preselect = set(preselected or set())

        self.setMinimumSize(_scale.px(_MIN_W), _scale.px(_MIN_H))
        width, height = _dialog_size()
        self.resize(width, height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scale.margins(12))
        layout.setSpacing(_scale.px(6))

        instruction = QLabel("Assign this file to one or more contiguous episodes:", self)
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        self._file_label: QLabel | None = None
        if file_label:
            self._file_label = _file_name_label(file_label, self)
            layout.addWidget(self._file_label)

        self._tree = QTreeWidget(self)
        _configure_tree(self._tree)

        seasons: dict[int, list[EpisodeSlotChoice]] = {}
        for choice in slots:
            seasons.setdefault(choice.season, []).append(choice)

        # Expand the seasons holding a preselected/current key; if none, expand all.
        focus = {season for season, _episode in (preselect | current)}
        expand_all = not focus

        self._season_items: dict[int, QTreeWidgetItem] = {}
        self._leaf_items: list[QTreeWidgetItem] = []
        for season in sorted(seasons):
            choices = seasons[season]
            parent_item = QTreeWidgetItem([_season_header(season, len(choices))])
            parent_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            parent_item.setData(0, _SLOT_ROLE, None)
            self._tree.addTopLevelItem(parent_item)
            parent_item.setExpanded(expand_all or season in focus)
            self._season_items[season] = parent_item
            for choice in choices:
                key = (choice.season, choice.episode)
                if key in current:
                    suffix = "[current]"
                elif choice.claimed_by:
                    suffix = f"[claimed by {choice.claimed_by}]"
                else:
                    suffix = "[missing]"
                text = f"{choice.label}    {suffix}"
                leaf = QTreeWidgetItem([text])
                leaf.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                leaf.setData(0, _SLOT_ROLE, key)
                leaf.setToolTip(0, text)
                leaf.setCheckState(
                    0,
                    Qt.CheckState.Checked if key in preselect else Qt.CheckState.Unchecked,
                )
                parent_item.addChild(leaf)
                self._leaf_items.append(leaf)

        self._tree.itemChanged.connect(lambda *_args: self._revalidate())
        layout.addWidget(self._tree, stretch=1)

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
        for leaf in self._leaf_items:
            key = leaf.data(0, _SLOT_ROLE)
            if key is not None and leaf.checkState(0) == Qt.CheckState.Checked:
                keys.append(tuple(key))
        return sorted(keys)

    def selected_episodes(self) -> list[tuple[int, int]]:
        return self._checked_keys()

    def set_checked(self, keys: list[tuple[int, int]]) -> None:
        wanted = set(keys)
        for leaf in self._leaf_items:
            key = leaf.data(0, _SLOT_ROLE)
            if key is None:
                continue
            leaf.setCheckState(
                0,
                Qt.CheckState.Checked if tuple(key) in wanted else Qt.CheckState.Unchecked,
            )
        self._revalidate()

    def is_season_expanded(self, season: int) -> bool:
        item = self._season_items.get(season)
        return bool(item is not None and item.isExpanded())

    def _validate(self) -> str:
        keys = self._checked_keys()
        if not keys:
            return "Select at least one episode."
        seasons = {season for season, _episode in keys}
        if len(seasons) > 1:
            return "All selected episodes must be in the same season."
        episodes = [episode for _season, episode in keys]
        if any(b - a != 1 for a, b in itertools.pairwise(episodes)):
            return "Selected episodes must be a contiguous run."
        return ""

    def is_selection_valid(self) -> bool:
        return self._validate() == ""

    def validation_text(self) -> str:
        return self._validation.text()

    def slot_row_text(self, season: int, episode: int) -> str:
        for leaf in self._leaf_items:
            if leaf.data(0, _SLOT_ROLE) == (season, episode):
                return leaf.text(0)
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
        current_keys: set[tuple[int, int]] | None = None,
        file_label: str = "",
    ) -> list[tuple[int, int]] | None:
        dialog = cls(
            slots=slots,
            parent=parent,
            title=title,
            file_label=file_label,
            current_keys=current_keys,
            preselected=preselected,
        )
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
        dialog.setMinimumSize(_scale.px(_MIN_W), _scale.px(_MIN_H))
        width, height = _dialog_size()
        dialog.resize(width, height)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(_scale.margins(12))
        layout.setSpacing(_scale.px(6))

        tree = QTreeWidget(dialog)
        _configure_tree(tree)

        def add_group(header_text: str, entries: list[tuple[int, str]]) -> None:
            if not entries:
                return
            group = QTreeWidgetItem([f"{header_text} ({len(entries)})"])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setData(0, _SLOT_ROLE, None)
            tree.addTopLevelItem(group)
            group.setExpanded(True)
            for file_id, label in entries:
                leaf = QTreeWidgetItem([label])
                leaf.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                leaf.setData(0, _SLOT_ROLE, file_id)
                leaf.setToolTip(0, label)
                group.addChild(leaf)

        add_group("Unassigned files", unassigned)
        add_group("Share / extend (keeps current episode)", shareable or [])
        add_group("Already assigned (will be reassigned)", assigned)

        def _accept_if_file(item: QTreeWidgetItem, _column: int) -> None:
            if item is not None and item.data(0, _SLOT_ROLE) is not None:
                dialog.accept()

        tree.itemDoubleClicked.connect(_accept_if_file)
        layout.addWidget(tree, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)

        def _update_ok() -> None:
            current = tree.currentItem()
            enabled = current is not None and current.data(0, _SLOT_ROLE) is not None
            if ok_btn is not None:
                ok_btn.setEnabled(enabled)

        tree.currentItemChanged.connect(lambda _cur, _prev: _update_ok())
        _update_ok()

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item = tree.currentItem()
        if item is None:
            return None
        file_id = item.data(0, _SLOT_ROLE)
        return int(file_id) if file_id is not None else None
