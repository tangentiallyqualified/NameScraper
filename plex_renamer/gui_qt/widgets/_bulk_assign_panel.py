# plex_renamer/gui_qt/widgets/_bulk_assign_panel.py
"""BulkAssignPanel — two-pane files→slots surface for GUI V4 Plan 4 (Bulk Assign).

Two ``QListView``s (unassigned files / episode slots) over two small
``QAbstractListModel``s, plus a purely local staging dict. Nothing here calls
into ``EpisodeMappingService`` — staging is panel-local; the owner applies the
staged pairs via ``apply_requested`` (Task 4 wiring, not this module).
"""
from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QDrag, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from .. import _scale

FILE_ID_ROLE = Qt.ItemDataRole.UserRole + 1     # int (files model)
SLOT_KEY_ROLE = Qt.ItemDataRole.UserRole + 1    # tuple[int, int] | None (slots model)
_MIME_FILE_ID = "application/x-namescraper-file-id"


# ── files pane ───────────────────────────────────────────────────────────

class BulkFilesModel(QAbstractListModel):
    """Unassigned-file rows: checkable, searchable, staged-aware."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._previews: list = []            # all previews, sorted
        self._visible: list = []              # filtered by search
        self._search_text: str = ""
        self._staged: dict[int, tuple[int, int]] = {}
        self._checked: set[int] = set()

    def set_files(self, previews: list) -> None:
        self.beginResetModel()
        self._previews = sorted(previews, key=lambda p: p.original.name.casefold())
        self._checked = set()
        self._apply_filter()
        self.endResetModel()

    def set_search(self, text: str) -> None:
        self.beginResetModel()
        self._search_text = text.casefold()
        self._apply_filter()
        self.endResetModel()

    def set_staged(self, staged: dict[int, tuple[int, int]]) -> None:
        self._staged = staged
        self._checked -= staged.keys()
        if not self._visible:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._visible) - 1, 0)
        self.dataChanged.emit(top_left, bottom_right)

    def checked_file_ids(self) -> list[int]:
        return [
            preview.file_id for preview in self._visible
            if preview.file_id in self._checked
        ]

    def unstaged_file_ids(self) -> list[int]:
        """Visible (search-filtered) file ids not yet staged, in display order."""
        return [
            preview.file_id for preview in self._visible
            if preview.file_id not in self._staged
        ]

    def file_id_at(self, row: int) -> int | None:
        if 0 <= row < len(self._visible):
            return self._visible[row].file_id
        return None

    def _apply_filter(self) -> None:
        if not self._search_text:
            self._visible = list(self._previews)
            return
        self._visible = [
            preview for preview in self._previews
            if self._search_text in preview.original.name.casefold()
        ]

    # -- QAbstractListModel overrides ------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._visible)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        preview = self._visible[index.row()]
        flags = (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
        )
        if preview.file_id not in self._staged:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        preview = self._visible[index.row()]
        staged_key = self._staged.get(preview.file_id)
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            name = preview.original.name
            if staged_key is not None:
                season, episode = staged_key
                return f"{name}  →  S{season:02d}E{episode:02d}"
            return name
        if role == Qt.ItemDataRole.ToolTipRole:
            tooltip = str(preview.original)
            if staged_key is not None:
                season, episode = staged_key
                tooltip = f"{tooltip} — S{season:02d}E{episode:02d}"
            return tooltip
        if role == Qt.ItemDataRole.CheckStateRole:
            if staged_key is not None:
                return None
            return (
                Qt.CheckState.Checked.value
                if preview.file_id in self._checked
                else Qt.CheckState.Unchecked.value
            )
        if role == Qt.ItemDataRole.ForegroundRole:
            if staged_key is not None:
                return theme.qcolor("accent")
            return None
        if role == FILE_ID_ROLE:
            return preview.file_id
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        preview = self._visible[index.row()]
        if preview.file_id in self._staged:
            return False
        checked = value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked
        if checked:
            self._checked.add(preview.file_id)
        else:
            self._checked.discard(preview.file_id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def mimeTypes(self) -> list[str]:  # noqa: N802
        return [_MIME_FILE_ID]

    def mimeData(self, indexes) -> QMimeData:  # noqa: N802
        mime = QMimeData()
        for index in indexes:
            if not index.isValid():
                continue
            file_id = self._visible[index.row()].file_id
            if file_id is not None:
                mime.setData(_MIME_FILE_ID, str(file_id).encode("utf-8"))
                break
        return mime


class BulkFilesView(QListView):
    """Drag source: unassigned-file rows, shift-range check toggling."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QListView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._last_check_row: int = -1

    def _check_zone_rect(self, index: QModelIndex):
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        option.rect = self.visualRect(index)
        style = self.style()
        return style.subElementRect(
            style.SubElement.SE_ItemViewItemCheckIndicator, option, self,
        )

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        if index.isValid() and bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            check_rect = self._check_zone_rect(index)
            if check_rect.contains(pos):
                model = self.model()
                current = index.data(Qt.ItemDataRole.CheckStateRole)
                next_value = (
                    Qt.CheckState.Unchecked.value
                    if current == Qt.CheckState.Checked.value
                    else Qt.CheckState.Checked.value
                )
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and self._last_check_row != -1:
                    lo, hi = sorted((self._last_check_row, index.row()))
                    for row in range(lo, hi + 1):
                        target = model.index(row, 0)
                        if target.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                            model.setData(target, next_value, Qt.ItemDataRole.CheckStateRole)
                else:
                    model.setData(index, next_value, Qt.ItemDataRole.CheckStateRole)
                self._last_check_row = index.row()
                return
        super().mousePressEvent(event)

    def startDrag(self, supportedActions) -> None:  # noqa: N802
        index = self.currentIndex()
        model = self.model()
        if model is None or not index.isValid():
            return
        mime = model.mimeData([index])
        if mime is None:
            return
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


# ── slots pane ───────────────────────────────────────────────────────────

class BulkSlotsModel(QAbstractListModel):
    """Season-grouped slot rows: header rows + claim/staged/missing slot rows."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[tuple[int, int] | None, str, str]] = []
        # each row: (slot_key_or_None, display_text, foreground_token)
        self._claimed_keys: set[tuple[int, int]] = set()

    def set_slots(self, choices: list, staged_names: dict[tuple[int, int], str]) -> None:
        self.beginResetModel()
        self._rows = []
        self._claimed_keys = {
            (choice.season, choice.episode)
            for choice in choices if choice.claimed_by
        }
        by_season: dict[int, list] = {}
        for choice in choices:
            by_season.setdefault(choice.season, []).append(choice)
        for season in sorted(by_season):
            season_choices = by_season[season]
            header = "Specials" if season == 0 else f"Season {season:02d}"
            self._rows.append((None, f"{header} ({len(season_choices)})", ""))
            for choice in sorted(season_choices, key=lambda c: c.episode):
                key = (choice.season, choice.episode)
                staged_name = staged_names.get(key)
                if staged_name is not None:
                    text = f"{choice.label}  →  {staged_name}"
                    tone = "accent"
                elif choice.claimed_by:
                    text = f"{choice.label} — {choice.claimed_by}"
                    tone = "text_dim"
                else:
                    text = f"{choice.label} — missing"
                    tone = "warning"
                self._rows.append((key, text, tone))
        self.endResetModel()

    def slot_key_at(self, row: int) -> tuple[int, int] | None:
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return None

    def is_claimed(self, key: tuple[int, int]) -> bool:
        return key in self._claimed_keys

    def row_for_key(self, key: tuple[int, int]) -> int:
        for row, (row_key, _text, _tone) in enumerate(self._rows):
            if row_key == key:
                return row
        return -1

    # -- QAbstractListModel overrides ------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        key, _text, _tone = self._rows[index.row()]
        if key is None:
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        key, text, tone = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return text
        if role == Qt.ItemDataRole.ToolTipRole:
            return text
        if role == Qt.ItemDataRole.ForegroundRole:
            if tone:
                return theme.qcolor(tone)
            return None
        if role == SLOT_KEY_ROLE:
            return key
        return None


class BulkSlotsView(QListView):
    """Drop target: emits pair_dropped when a file is dragged onto a free slot row."""

    pair_dropped = Signal(int, tuple)  # file_id, (season, episode)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)

    def _droppable_key_at(self, pos) -> tuple[int, int] | None:
        index = self.indexAt(pos)
        if not index.isValid():
            return None
        model = self.model()
        if not isinstance(model, BulkSlotsModel):
            return None
        key = model.slot_key_at(index.row())
        if key is None or model.is_claimed(key):
            return None
        return key

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(_MIME_FILE_ID):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(_MIME_FILE_ID):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if not mime.hasFormat(_MIME_FILE_ID):
            event.ignore()
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        key = self._droppable_key_at(pos)
        if key is None:
            event.ignore()
            return
        raw = bytes(mime.data(_MIME_FILE_ID)).decode("utf-8")
        try:
            file_id = int(raw)
        except ValueError:
            event.ignore()
            return
        self.pair_dropped.emit(file_id, key)
        event.acceptProposedAction()


# ── panel ────────────────────────────────────────────────────────────────

class BulkAssignPanel(QFrame):
    """Files/slots two-pane staging surface for GUI V4 Plan 4 Bulk Assign."""

    apply_requested = Signal(list)   # list[tuple[int, int, int]] (file_id, season, episode)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = None
        self._service = None
        self._choices: list = []
        self._previews: list = []
        self._staged: dict[int, tuple[int, int]] = {}
        self._anchor_key: tuple[int, int] | None = None
        self._build_ui()

    # -- UI scaffold ------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        margin = _scale.px(12)
        outer.setContentsMargins(margin, margin, margin, margin)
        outer.setSpacing(_scale.px(8))

        panes = QHBoxLayout()
        panes.setSpacing(_scale.px(12))

        left = QVBoxLayout()
        left.setSpacing(_scale.px(4))
        self._files_caption = QLabel("Unassigned files (0)")
        self._files_caption.setProperty("cssClass", "caption")
        left.addWidget(self._files_caption)
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter files…")
        self._search_box.setClearButtonEnabled(True)
        self._search_box.textChanged.connect(self._on_search_changed)
        left.addWidget(self._search_box)
        self._files_model = BulkFilesModel(self)
        self._files_view = BulkFilesView()
        self._files_view.setModel(self._files_model)
        left.addWidget(self._files_view, stretch=1)
        panes.addLayout(left, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(_scale.px(4))
        self._slots_caption = QLabel("Episode slots")
        self._slots_caption.setProperty("cssClass", "caption")
        right.addWidget(self._slots_caption)
        self._slots_model = BulkSlotsModel(self)
        self._slots_view = BulkSlotsView()
        self._slots_view.setModel(self._slots_model)
        self._slots_view.pair_dropped.connect(self._handle_drop)
        self._slots_view.clicked.connect(self._on_slot_clicked)
        right.addWidget(self._slots_view, stretch=1)
        panes.addLayout(right, stretch=1)

        outer.addLayout(panes, stretch=1)

        button_row = QHBoxLayout()
        button_row.setSpacing(_scale.px(8))
        self._assign_button = QPushButton("Assign in order")
        self._assign_button.setProperty("cssClass", "primary")
        self._assign_button.clicked.connect(self.assign_in_order)
        button_row.addWidget(self._assign_button)

        self._auto_map_button = QPushButton("Auto-map remaining")
        self._auto_map_button.setProperty("cssClass", "secondary")
        self._auto_map_button.clicked.connect(self.auto_map_remaining)
        button_row.addWidget(self._auto_map_button)

        self._reset_button = QPushButton("Reset")
        self._reset_button.setProperty("cssClass", "secondary")
        self._reset_button.clicked.connect(self.reset_staging)
        button_row.addWidget(self._reset_button)

        button_row.addStretch()

        self._status_label = QLabel("")
        self._status_label.setProperty("cssClass", "caption")
        button_row.addWidget(self._status_label)

        self._apply_button = QPushButton("Apply")
        self._apply_button.setProperty("cssClass", "primary")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._on_apply_clicked)
        button_row.addWidget(self._apply_button)

        self._cancel_button = QPushButton("Cancel")
        self._cancel_button.setProperty("cssClass", "secondary")
        self._cancel_button.clicked.connect(self.cancelled.emit)
        button_row.addWidget(self._cancel_button)

        outer.addLayout(button_row)

    # -- Public API -------------------------------------------------------

    def show_state(self, state, service) -> None:
        self._state = state
        self._service = service
        self._choices = service.episode_slot_choices(state)
        self._previews = service.unassigned_file_previews(state)
        self._staged = {}
        self._anchor_key = None
        self._status_label.setText("")
        self._files_model.set_files(self._previews)
        self._files_caption.setText(f"Unassigned files ({len(self._previews)})")
        self._refresh_views()

    def staged_pairs(self) -> list[tuple[int, int, int]]:
        return [
            (file_id, season, episode)
            for file_id, (season, episode) in sorted(self._staged.items())
        ]

    def assign_in_order(self) -> None:
        file_ids = self._files_model.checked_file_ids()
        keys = self._free_keys_sorted()
        if self._anchor_key is not None:
            ordered_keys = [key for key in keys if key >= self._anchor_key]
        else:
            ordered_keys = keys
        staged_now: list[int] = []
        for file_id, key in zip(file_ids, ordered_keys):
            self._staged[file_id] = key
            staged_now.append(file_id)
        leftover = len(file_ids) - len(staged_now)
        if leftover > 0:
            self._status_label.setText(f"{leftover} file(s) left unstaged — no free slots")
        else:
            self._status_label.setText("")
        self._refresh_views()

    def auto_map_remaining(self) -> None:
        file_ids = self._files_model.unstaged_file_ids()
        keys = self._free_keys_sorted()
        for file_id, key in zip(file_ids, keys):
            self._staged[file_id] = key
        self._refresh_views()

    def reset_staging(self) -> None:
        self._staged = {}
        self._anchor_key = None
        self._status_label.setText("")
        self._refresh_views()

    # -- Drag / click handlers ---------------------------------------------

    def _handle_drop(self, file_id: int, key: tuple[int, int]) -> None:
        if self._is_claimed(key) or self._is_staged(key):
            return
        self._staged = {
            fid: existing_key for fid, existing_key in self._staged.items()
            if fid != file_id
        }
        self._staged[file_id] = key
        self._refresh_views()

    def _on_slot_clicked(self, index: QModelIndex) -> None:
        key = self._slots_model.slot_key_at(index.row())
        if key is None:
            return
        self._anchor_key = key
        season, episode = key
        self._status_label.setText(f"Start at S{season:02d}E{episode:02d}")

    def _on_search_changed(self, text: str) -> None:
        self._files_model.set_search(text)

    def _on_apply_clicked(self) -> None:
        self.apply_requested.emit(self.staged_pairs())

    # -- Internal helpers ---------------------------------------------------

    def _is_claimed(self, key: tuple[int, int]) -> bool:
        return self._slots_model.is_claimed(key)

    def _is_staged(self, key: tuple[int, int]) -> bool:
        return key in self._staged.values()

    def _free_keys_sorted(self) -> list[tuple[int, int]]:
        return sorted(
            (choice.season, choice.episode)
            for choice in self._choices
            if not choice.claimed_by
            and (choice.season, choice.episode) not in self._staged.values()
        )

    def _refresh_views(self) -> None:
        self._files_model.set_staged(dict(self._staged))
        staged_names = {
            key: self._file_name(file_id)
            for file_id, key in self._staged.items()
        }
        self._slots_model.set_slots(self._choices, staged_names)
        self._apply_button.setEnabled(bool(self._staged))

    def _file_name(self, file_id: int) -> str:
        for preview in self._previews:
            if preview.file_id == file_id:
                return preview.original.name
        return ""
