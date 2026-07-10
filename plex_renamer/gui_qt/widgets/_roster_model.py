# plex_renamer/gui_qt/widgets/_roster_model.py
"""Read-model exposing ScanStates to the roster QListView (GUI V4 §7)."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QPixmap

from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from .. import _scale
from ._formatting import clamped_percent
from ._image_utils import pil_to_raw, raw_to_pixmap
from ._media_helpers import (
    confidence_band as _confidence_band,
    confidence_fill_color as _confidence_fill_color,
    is_state_queue_approvable as _is_state_queue_approvable,
    placeholder_initials as _placeholder_initials,
    roster_group as _roster_group,
    roster_item_key as _roster_item_key,
    state_status as _state_status,
    state_status_tone as _state_status_tone,
)
from ._workspace_widget_primitives import RosterPosterBridge
from .status_chip import ChipSpec, season_chip_specs

KIND_ROLE = Qt.ItemDataRole.UserRole + 1
GROUP_ROLE = Qt.ItemDataRole.UserRole + 2
STATE_INDEX_ROLE = Qt.ItemDataRole.UserRole + 3
ENTRY_KEY_ROLE = Qt.ItemDataRole.UserRole + 4
ROW_DATA_ROLE = Qt.ItemDataRole.UserRole + 5
POSTER_ROLE = Qt.ItemDataRole.UserRole + 6

_MAX_POSTER_CACHE = 128

ROSTER_GROUPS: tuple[tuple[str, str], ...] = (
    ("queued", "Queued"),
    ("fully-ready", "Fully Ready"),
    ("matched", "Matched"),
    ("review-match", "Needs Review — Match"),
    ("review-episodes", "Needs Review — Episodes"),
    ("specials-unmapped", "Specials & Unmapped Only"),
    ("unmatched", "No Match Found"),
    ("duplicate", "Duplicates"),
)


@dataclass(frozen=True, slots=True)
class RosterRowData:
    title: str
    status_text: str          # e.g. "FULLY READY" (upper)
    status_tone: str          # "success"|"info"|"error"|"muted"|"accent"
    band: str                 # "high"|"medium"|"low"|"muted"|"error"
    confidence_pct: int       # 0..100
    confidence_color: str     # hex str from theme via confidence_fill_color
    checked: bool
    checkable: bool
    chips: tuple[ChipSpec, ...]
    tooltip: str              # "" or duplicate-of note
    poster_key: tuple[str, int] | None
    placeholder_initials: str
    placeholder_accent: str   # hex str (status color) for placeholder pixmap


@dataclass(frozen=True, slots=True)
class _HeaderEntry:
    group: str
    title_text: str


@dataclass(frozen=True, slots=True)
class _StateEntry:
    state_index: int
    key: str
    row_data: RosterRowData


class RosterModel(QAbstractListModel):
    poster_loaded = Signal()  # emitted after any poster lands; drives the loading-screen poster warmup gate

    def __init__(
        self,
        *,
        media_type: str,
        settings_service=None,
        tmdb_provider=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._tmdb_provider = tmdb_provider
        self._compact = False
        self._states: list[ScanState] = []
        self._entries: list[_HeaderEntry | _StateEntry] = []
        self._poster_cache: OrderedDict[tuple[str, int], QPixmap] = OrderedDict()
        self._poster_inflight: set[tuple[str, int]] = set()
        self._poster_bridge = RosterPosterBridge(self)
        self._poster_bridge.poster_ready.connect(self._apply_poster)

    # -- QAbstractListModel overrides ------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._entries)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        entry = self._entries[index.row()]
        if isinstance(entry, _HeaderEntry):
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if isinstance(entry, _HeaderEntry):
            return self._header_data(entry, role)
        return self._state_data(entry, role)

    def _header_data(self, entry: _HeaderEntry, role: int):
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return entry.title_text
        if role == KIND_ROLE:
            return "header"
        if role == GROUP_ROLE:
            return entry.group
        if role == ENTRY_KEY_ROLE:
            return f"header:{entry.group}"
        return None

    def _state_data(self, entry: _StateEntry, role: int):
        row_data = entry.row_data
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return row_data.title
        if role == Qt.ItemDataRole.ToolTipRole:
            return row_data.tooltip
        if role == KIND_ROLE:
            return "state"
        if role == STATE_INDEX_ROLE:
            return entry.state_index
        if role == ENTRY_KEY_ROLE:
            return entry.key
        if role == ROW_DATA_ROLE:
            return row_data
        if role == POSTER_ROLE:
            if row_data.poster_key is None:
                return None
            return self._poster_cache.get(row_data.poster_key)
        return None

    # -- Public API -------------------------------------------------------

    def set_states(self, states: list[ScanState], *, collapsed_groups: dict[str, bool]) -> None:
        self.beginResetModel()
        self._states = states
        self._entries = list(self._build_entries(states, collapsed_groups))
        self.endResetModel()
        self._request_posters_for_all_entries()

    def refresh_state(self, state_index: int) -> None:
        row = self.row_for_state_index(state_index)
        if row < 0:
            return
        state = self._states[state_index]
        entry = self._entries[row]
        assert isinstance(entry, _StateEntry)
        self._entries[row] = _StateEntry(
            state_index=entry.state_index,
            key=entry.key,
            row_data=self._build_row_data(state),
        )
        index = self.index(row, 0)
        self.dataChanged.emit(index, index, [ROW_DATA_ROLE, Qt.ItemDataRole.DisplayRole])

    def entry_kind_at(self, row: int) -> str | None:
        if row < 0 or row >= len(self._entries):
            return None
        return "header" if isinstance(self._entries[row], _HeaderEntry) else "state"

    def group_at(self, row: int) -> str | None:
        if row < 0 or row >= len(self._entries):
            return None
        entry = self._entries[row]
        if isinstance(entry, _HeaderEntry):
            return entry.group
        return _roster_group(self._states[entry.state_index], media_type=self._media_type)

    def state_index_at(self, row: int) -> int | None:
        if row < 0 or row >= len(self._entries):
            return None
        entry = self._entries[row]
        if isinstance(entry, _StateEntry):
            return entry.state_index
        return None

    def row_for_state_index(self, state_index: int) -> int:
        for row, entry in enumerate(self._entries):
            if isinstance(entry, _StateEntry) and entry.state_index == state_index:
                return row
        return -1

    def first_state_row(self) -> int:
        for row, entry in enumerate(self._entries):
            if isinstance(entry, _StateEntry):
                return row
        return -1

    def header_row_before(self, row: int) -> int:
        for candidate in range(row - 1, -1, -1):
            if isinstance(self._entries[candidate], _HeaderEntry):
                return candidate
        return -1

    def set_compact(self, compact: bool) -> None:
        self._compact = compact
        rebuilt: list[_HeaderEntry | _StateEntry] = []
        for entry in self._entries:
            if isinstance(entry, _StateEntry):
                state = self._states[entry.state_index]
                rebuilt.append(
                    _StateEntry(
                        state_index=entry.state_index,
                        key=entry.key,
                        row_data=self._build_row_data(state),
                    )
                )
            else:
                rebuilt.append(entry)
        self._entries = rebuilt
        self.layoutChanged.emit()

    def is_compact(self) -> bool:
        return self._compact

    def loaded_posters(self) -> list[QPixmap]:
        return list(self._poster_cache.values())

    def pending_poster_count(self) -> int:
        return len(self._poster_inflight)

    # -- Entry building ---------------------------------------------------

    def _build_entries(self, states: list[ScanState], collapsed_groups: dict[str, bool]):
        for group, title in ROSTER_GROUPS:
            indices = [
                index
                for index, state in enumerate(states)
                if _roster_group(state, media_type=self._media_type) == group
            ]
            if not indices:
                continue
            collapsed = collapsed_groups.get(group, False)
            arrow = "▶" if collapsed else "▼"
            yield _HeaderEntry(group=group, title_text=f"{arrow}  {title.upper()} ({len(indices)})")
            if collapsed:
                continue
            for index in indices:
                state = states[index]
                yield _StateEntry(
                    state_index=index,
                    key=_roster_item_key(state),
                    row_data=self._build_row_data(state),
                )

    def _build_row_data(self, state: ScanState) -> RosterRowData:
        status_text, status_color = _state_status(state, media_type=self._media_type)
        chips: tuple[ChipSpec, ...] = ()
        if self._media_type == "tv":
            chips = tuple(season_chip_specs(state.completeness, drop_empty=True))
        tooltip = ""
        if state.duplicate_of is not None:
            tooltip = f"Same match as {state.duplicate_of_relative_folder or state.duplicate_of}"
        poster_key = (self._media_type, state.show_id) if state.show_id is not None else None
        return RosterRowData(
            title=state.display_name,
            status_text=status_text.upper(),
            status_tone=_state_status_tone(state, media_type=self._media_type),
            band=_confidence_band(state.confidence, state=state, media_type=self._media_type),
            confidence_pct=clamped_percent(state.confidence),
            confidence_color=_confidence_fill_color(state.confidence, state=state, media_type=self._media_type),
            checked=bool(state.checked),
            checkable=_is_state_queue_approvable(state, media_type=self._media_type),
            chips=chips,
            tooltip=tooltip,
            poster_key=poster_key,
            placeholder_initials=_placeholder_initials(state.display_name),
            placeholder_accent=status_color.name(),
        )

    # -- Poster pipeline (moved from _media_workspace_roster.py) ----------

    def _request_posters_for_all_entries(self) -> None:
        for entry in self._entries:
            if isinstance(entry, _StateEntry):
                self._request_poster(self._states[entry.state_index], entry.row_data)

    def warm_posters(self, states: list[ScanState]) -> None:
        """Prefetch posters for matched states (loading-screen feed, R2 LD2).
        Safe to call repeatedly: cache hits and in-flight keys are no-ops."""
        for state in states:
            if state.show_id is None:
                continue
            self._request_poster_for_key(state, (self._media_type, state.show_id))

    def _request_poster(self, state: ScanState, row_data: RosterRowData) -> None:
        if row_data.poster_key is None:
            return
        self._request_poster_for_key(state, row_data.poster_key)

    def _request_poster_for_key(self, state: ScanState, key: tuple[str, int]) -> None:
        if self._tmdb_provider is None:
            return
        if key in self._poster_cache:
            self._poster_cache.move_to_end(key)
            return
        if key in self._poster_inflight:
            return
        tmdb = self._tmdb_provider()
        if tmdb is None:
            return
        self._poster_inflight.add(key)
        target_width = self._poster_fetch_width()

        def _worker() -> None:
            try:
                image = tmdb.fetch_poster(state.show_id, media_type=self._media_type, target_width=target_width)
                if image is None:
                    return
                try:
                    self._poster_bridge.poster_ready.emit(key, pil_to_raw(image))
                except RuntimeError:
                    return
            finally:
                self._poster_inflight.discard(key)

        _submit_bg(_worker)

    def _poster_fetch_width(self) -> int:
        return max(220, min(420, _scale.px(64) * 2))

    def _apply_poster(self, key, raw_data) -> None:
        pixmap = raw_to_pixmap(raw_data)
        if pixmap.isNull():
            return
        self._poster_cache[key] = pixmap
        self._poster_cache.move_to_end(key)
        while len(self._poster_cache) > _MAX_POSTER_CACHE:
            self._poster_cache.popitem(last=False)
        for row, entry in enumerate(self._entries):
            if isinstance(entry, _StateEntry) and entry.row_data.poster_key == key:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [POSTER_ROLE])
        self.poster_loaded.emit()
