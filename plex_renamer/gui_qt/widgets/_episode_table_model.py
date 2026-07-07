# plex_renamer/gui_qt/widgets/_episode_table_model.py
"""Read-model over ScanState + EpisodeGuide for the work-panel episode table (GUI V4 Plan 3)."""
from __future__ import annotations

import logging

from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Qt, Signal

from ...app.models.state_models import EpisodeGuide, EpisodeGuideRow
from ...engine import ScanState
from ...thread_pool import submit as _submit_bg
from ._formatting import clamped_percent
from ._media_helpers import (
    is_state_queue_approvable as _is_state_queue_approvable,
    preview_status_label as _preview_status_label,
    preview_status_tone as _preview_status_tone,
    season_label as _season_label,
)

ROW_KIND_ROLE = Qt.ItemDataRole.UserRole + 1
SECTION_KEY_ROLE = Qt.ItemDataRole.UserRole + 2
PREVIEW_INDEX_ROLE = Qt.ItemDataRole.UserRole + 3
GUIDE_ROW_ROLE = Qt.ItemDataRole.UserRole + 4
ROW_DATA_ROLE = Qt.ItemDataRole.UserRole + 5
EXPANDED_ROLE = Qt.ItemDataRole.UserRole + 6

_log = logging.getLogger(__name__)

_SKELETON_MIN_ROWS, _SKELETON_MAX_ROWS = 6, 20


class _GuideBridge(QObject):
    """Worker → GUI-thread hop for built guides (mirrors the overview bridge)."""

    guide_ready = Signal(object, object, object, int)   # state, guide, signature, token
    guide_failed = Signal(object, int)                  # state, token


_SECTION_COLLAPSED_PREFIX = "▸ "
_SECTION_EXPANDED_PREFIX = "▾ "

# preview_status_tone() returns "accent" for review rows; the table's tone
# vocabulary (used for pill coloring) only knows success/warning/error/muted.
_PREVIEW_TONE_REMAP = {"accent": "warning"}


def _percent_from_label(value: str) -> int | None:
    text = value.strip()
    if not text.endswith("%"):
        return None
    try:
        return max(0, min(100, int(round(float(text[:-1])))))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class EpisodeRowData:
    kind: str
    title: str
    status_text: str = ""
    status_tone: str = ""          # success|warning|error|muted
    filename: str = ""             # inline filename line ("" hides it)
    target: str = ""
    confidence_pct: int | None = None
    checked: bool | None = None    # movie-file rows only
    checkable: bool = False
    collapsed: bool = False        # section-header rows
    companion_count: int = 0
    tooltip: str = ""


@dataclass(frozen=True, slots=True)
class _Entry:
    kind: str
    section_key: str | None
    text: str
    preview_index: int | None
    guide_row: EpisodeGuideRow | None
    row_data: EpisodeRowData
    collapsible: bool = False


class EpisodeTableModel(QAbstractListModel):
    guide_loaded = Signal()

    def __init__(
        self,
        *,
        media_type: str,
        settings_service=None,
        guide_provider=None,
        cached_guide_provider=None,
        guide_builder=None,
        guide_store=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._media_type = media_type
        self._settings = settings_service
        self._guide_provider = guide_provider
        self._state: ScanState | None = None
        self._guide: EpisodeGuide | None = None
        self._collapsed_sections: set[str] = set()
        self._folder_preview: tuple[str, str] | None = None
        self._filter_mode = "all"
        self._search_text = ""
        self._expanded_row: int | None = None
        self._entries: list[_Entry] = []
        self._cached_guide_provider = cached_guide_provider
        self._guide_builder = guide_builder
        self._guide_store = guide_store
        self._guide_token = 0
        self._guide_error = False
        self._guide_bridge = _GuideBridge(self)
        self._guide_bridge.guide_ready.connect(self._on_guide_ready)
        self._guide_bridge.guide_failed.connect(self._on_guide_failed)

    # -- QAbstractListModel overrides ------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._entries)

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        entry = self._entries[index.row()]
        if entry.kind in {"section-header", "section-label", "folder", "bulk-hint", "skeleton"}:
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return entry.text
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.row_data.tooltip
        if role == ROW_KIND_ROLE:
            return entry.kind
        if role == SECTION_KEY_ROLE:
            return entry.section_key
        if role == PREVIEW_INDEX_ROLE:
            return entry.preview_index
        if role == GUIDE_ROW_ROLE:
            return entry.guide_row
        if role == ROW_DATA_ROLE:
            return entry.row_data
        if role == EXPANDED_ROLE:
            return index.row() == self._expanded_row
        return None

    # -- Public API -------------------------------------------------------

    def show_state(
        self,
        state: ScanState | None,
        *,
        collapsed_sections: set[str],
        folder_preview: tuple[str, str] | None = None,
    ) -> None:
        self.beginResetModel()
        self._state = state
        self._collapsed_sections = collapsed_sections
        self._folder_preview = folder_preview
        self._expanded_row = None
        if state is None:
            self._guide = None
            self._entries = []
        elif state.scan_error:
            self._guide = None
            self._entries = [self._scan_error_entry(state)]
        elif self._media_type == "movie":
            self._guide = None
            self._entries = list(self._build_movie_entries(state, folder_preview))
        else:
            self._guide = self._resolve_guide_or_schedule(state)
            if self._guide is None:
                self._entries = list(self._build_skeleton_entries(state))
            else:
                self._entries = list(
                    self._build_tv_entries(state, self._guide, folder_preview)
                )
        self.endResetModel()

    def state(self) -> ScanState | None:
        return self._state

    def guide(self) -> EpisodeGuide | None:
        return self._guide

    def set_filter_mode(self, mode: str) -> None:
        if mode == self._filter_mode:
            return
        self._filter_mode = mode
        self._rebuild()

    def filter_mode(self) -> str:
        return self._filter_mode

    def set_search_text(self, text: str) -> None:
        normalized = text.casefold()
        if normalized == self._search_text:
            return
        self._search_text = normalized
        self._rebuild()

    def search_text(self) -> str:
        return self._search_text

    def toggle_section(self, section_key: str) -> None:
        if section_key in self._collapsed_sections:
            self._collapsed_sections.discard(section_key)
        else:
            self._collapsed_sections.add(section_key)
        self._rebuild()

    def summary_text(self) -> str:
        if self._media_type == "movie":
            items = self._state.preview_items if self._state is not None else []
            total = len(items)
            mapped = sum(1 for item in items if item.is_actionable)
            companions = sum(len(item.companions) for item in items)
            unmapped = 0
            duplicates = sum(1 for item in items if item.is_duplicate)
        elif self._guide is None:
            # Scan-error states never enter the loading pipeline: their footer
            # reports plain counts, not loading/error strings (final-review I1).
            if self._state is not None and not self._state.scan_error:
                return "Guide unavailable" if self._guide_error else "Loading episodes…"
            total = mapped = companions = unmapped = duplicates = 0
        else:
            summary = self._guide.summary
            mapped = summary.mapped_primary_files
            companions = summary.companion_files
            unmapped = summary.unmapped_primary_files
            duplicates = summary.duplicate_files
            total = mapped + companions + unmapped + duplicates
        # Spec §3.2.5: zero-count segments drop out; files + mapped always render.
        parts = [f"{total} files", f"{mapped} mapped"]
        parts.extend(
            f"{count} {noun}"
            for count, noun in (
                (companions, "companions"),
                (unmapped, "unmapped"),
                (duplicates, "duplicates"),
            )
            if count
        )
        return " · ".join(parts)

    def row_kind_at(self, row: int) -> str | None:
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row].kind

    def preview_index_at(self, row: int) -> int | None:
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row].preview_index

    def guide_row_at(self, row: int) -> EpisodeGuideRow | None:
        if row < 0 or row >= len(self._entries):
            return None
        return self._entries[row].guide_row

    def row_for_preview_index(self, preview_index: int) -> int:
        for row, entry in enumerate(self._entries):
            if entry.preview_index == preview_index:
                return row
        return -1

    def section_header_row(self, section_key: str) -> int:
        for row, entry in enumerate(self._entries):
            if entry.kind == "section-header" and entry.section_key == section_key:
                return row
        return -1

    def season_section_key(self, season: int) -> str:
        return f"episode-guide-season:{season}"

    def first_problem_row_in_season(self, season: int) -> int:
        section_key = self.season_section_key(season)
        for row, entry in enumerate(self._entries):
            if entry.section_key != section_key or entry.kind != "episode":
                continue
            if entry.guide_row is not None and entry.guide_row.status != "Mapped":
                return row
        return -1

    def set_expanded_row(self, row: int | None) -> None:
        if row is not None and (row < 0 or row >= len(self._entries)):
            row = None
        old_row = self._expanded_row
        if old_row == row:
            return
        self._expanded_row = row
        changed_rows = [r for r in (old_row, row) if r is not None]
        for changed_row in changed_rows:
            index = self.index(changed_row, 0)
            self.dataChanged.emit(index, index, [EXPANDED_ROLE])

    def expanded_row(self) -> int | None:
        return self._expanded_row

    def refresh_checks(self) -> None:
        if self._media_type != "movie" or self._state is None or not self._entries:
            return
        self._rebuild()
        if self._entries:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._entries) - 1, 0)
            self.dataChanged.emit(top_left, bottom_right, [ROW_DATA_ROLE])

    # -- Internal rebuild helpers -----------------------------------------

    def _rebuild(self) -> None:
        state = self._state
        self.beginResetModel()
        self._expanded_row = None   # editors are dropped on reset; keep the sentinel honest
        if state is None:
            self._entries = []
        elif state.scan_error:
            self._entries = [self._scan_error_entry(state)]
        elif self._media_type == "movie":
            self._entries = list(self._build_movie_entries(state, self._folder_preview))
        else:
            self._guide = self._resolve_guide_or_schedule(state)
            if self._guide is None:
                self._entries = list(self._build_skeleton_entries(state))
            else:
                self._entries = list(self._build_tv_entries(state, self._guide, self._folder_preview))
        self.endResetModel()

    def _guide_for_state(self, state: ScanState) -> EpisodeGuide:
        if self._guide_provider is not None:
            return self._guide_provider(state)
        from ...app.services.episode_mapping_service import EpisodeMappingService

        return EpisodeMappingService().build_episode_guide(state)

    def _resolve_guide_or_schedule(self, state: ScanState) -> EpisodeGuide | None:
        """Cached guide, or None after scheduling an off-thread build.

        Every resolution bumps the token so any in-flight build is orphaned
        by the newer render — a mutation path can synchronously refresh the
        cache mid-flight, and without the bump the superseded build would
        still deliver (rendering pre-mutation rows and clobbering the fresh
        cache entry).

        Without async wiring (bare panels, existing tests) this stays the
        old synchronous pull.
        """
        self._guide_token += 1
        self._guide_error = False
        if self._cached_guide_provider is None or self._guide_builder is None:
            return self._guide_for_state(state)
        guide = self._cached_guide_provider(state)
        if guide is not None:
            return guide
        token = self._guide_token
        builder = self._guide_builder
        bridge = self._guide_bridge

        def _worker() -> None:
            try:
                built, signature = builder(state)
            except Exception:
                _log.exception("episode guide build failed for %s", state.folder)
                try:
                    bridge.guide_failed.emit(state, token)
                except RuntimeError:
                    pass    # bridge destroyed during shutdown
                return
            try:
                bridge.guide_ready.emit(state, built, signature, token)
            except RuntimeError:
                pass    # bridge destroyed during shutdown

        _submit_bg(_worker)
        return None

    def _on_guide_ready(self, state, guide, signature, token: int) -> None:
        if token != self._guide_token or state is not self._state:
            return    # stale build: a newer show_state/_rebuild superseded it
        if self._guide_store is not None:
            self._guide_store(state, guide, signature)
        self.beginResetModel()
        self._guide = guide
        self._entries = list(self._build_tv_entries(state, guide, self._folder_preview))
        self.endResetModel()
        self.guide_loaded.emit()

    def _on_guide_failed(self, state, token: int) -> None:
        if token != self._guide_token or state is not self._state:
            return    # stale failure: a newer resolve superseded it
        self._guide_error = True
        self.beginResetModel()
        self._entries = [self._guide_error_entry()]
        self.endResetModel()
        self.guide_loaded.emit()    # footer/toolbar refresh path (guide stays None)

    def _guide_error_entry(self) -> _Entry:
        title = "Episode guide failed to load — select the show again to retry"
        row_data = EpisodeRowData(
            kind="section-label",
            title=title,
            status_text=title,
            status_tone="error",
        )
        return _Entry(
            kind="section-label",
            section_key=None,
            text=row_data.title,
            preview_index=None,
            guide_row=None,
            row_data=row_data,
        )

    def _build_skeleton_entries(self, state: ScanState):
        count = max(
            _SKELETON_MIN_ROWS,
            min(len(state.preview_items) or _SKELETON_MIN_ROWS, _SKELETON_MAX_ROWS),
        )
        header = EpisodeRowData(
            kind="section-label", title="Loading episodes…",
            status_text="", status_tone="muted",
        )
        yield _Entry("section-label", None, "Loading episodes…", None, None, header)
        for _ in range(count):
            yield _Entry(
                "skeleton", None, "", None, None, EpisodeRowData(kind="skeleton", title="")
            )

    def _scan_error_entry(self, state: ScanState) -> _Entry:
        row_data = EpisodeRowData(
            kind="section-label",
            title=f"Scan failed: {state.scan_error}",
            status_text=f"Scan failed: {state.scan_error}",
            status_tone="error",
        )
        return _Entry(
            kind="section-label",
            section_key=None,
            text=row_data.title,
            preview_index=None,
            guide_row=None,
            row_data=row_data,
        )

    # -- TV composition ----------------------------------------------------

    def _build_tv_entries(
        self,
        state: ScanState,
        guide: EpisodeGuide,
        folder_preview: tuple[str, str] | None,
    ):
        if folder_preview is not None:
            yield from self._folder_section_entries(folder_preview)

        if (
            self._filter_mode == "problems"
            and guide.unmapped_primary_files
            and not any(row.status in ("Review", "Conflict") for row in guide.rows)
        ):
            n = len(guide.unmapped_primary_files)
            text = f"No problem episodes — {n} unmapped file(s). Open Bulk Assign to map them…"
            yield _Entry(
                kind="bulk-hint",
                section_key=None,
                text=text,
                preview_index=None,
                guide_row=None,
                row_data=EpisodeRowData(kind="bulk-hint", title=text, status_tone="info"),
            )

        if self._filter_mode in {"all", "problems", "unmapped"} and guide.unmapped_primary_files:
            yield self._label_entry(f"Unmapped Primary Files ({len(guide.unmapped_primary_files)})")
            for unmapped in guide.unmapped_primary_files:
                entry = self._unmapped_entry(state, unmapped)
                if entry is not None:
                    yield entry

        if self._filter_mode in {"all", "problems"} and guide.duplicate_files:
            yield self._label_entry(f"Duplicate Copies ({len(guide.duplicate_files)})")
            for duplicate in guide.duplicate_files:
                entry = self._duplicate_entry(state, duplicate)
                if entry is not None:
                    yield entry

        yield from self._season_section_entries(state, guide)

        if self._filter_mode in {"all", "problems", "unmapped"} and guide.orphan_companion_files:
            yield self._label_entry(f"Orphan Companion Files ({len(guide.orphan_companion_files)})")
            for companion in guide.orphan_companion_files:
                entry = self._orphan_entry(companion)
                if entry is not None:
                    yield entry

    def _folder_section_entries(self, folder_preview: tuple[str, str]):
        section_key = "folder-preview"
        is_collapsed = section_key in self._collapsed_sections
        prefix = _SECTION_COLLAPSED_PREFIX if is_collapsed else _SECTION_EXPANDED_PREFIX
        yield _Entry(
            kind="section-header",
            section_key=section_key,
            text=f"{prefix}FOLDER",
            preview_index=None,
            guide_row=None,
            row_data=EpisodeRowData(kind="section-header", title="FOLDER", collapsed=is_collapsed),
            collapsible=True,
        )
        if is_collapsed:
            return
        source_name, target_name = folder_preview
        row_data = EpisodeRowData(
            kind="folder",
            title=source_name,
            target=target_name,
        )
        if not self._passes_search(row_data):
            return
        yield _Entry(
            kind="folder",
            section_key=section_key,
            text=row_data.title,
            preview_index=None,
            guide_row=None,
            row_data=row_data,
        )

    def _label_entry(self, text: str) -> _Entry:
        row_data = EpisodeRowData(kind="section-label", title=text)
        return _Entry(
            kind="section-label",
            section_key=None,
            text=text,
            preview_index=None,
            guide_row=None,
            row_data=row_data,
        )

    def _unmapped_entry(self, state: ScanState, unmapped) -> _Entry | None:
        preview = unmapped.preview
        preview_index = (
            state.preview_items.index(preview)
            if preview is not None and preview in state.preview_items
            else None
        )
        row_data = EpisodeRowData(
            kind="unmapped",
            title=unmapped.original.name,
            status_text="Unassigned",
            status_tone="warning",
            filename=unmapped.original.name,
            tooltip=str(unmapped.reason),
        )
        if not self._passes_search(row_data):
            return None
        return _Entry(
            kind="unmapped",
            section_key=None,
            text=row_data.title,
            preview_index=preview_index,
            guide_row=None,
            row_data=row_data,
        )

    def _duplicate_entry(self, state: ScanState, duplicate) -> _Entry | None:
        preview = duplicate.preview
        preview_index = (
            state.preview_items.index(preview)
            if preview is not None and preview in state.preview_items
            else None
        )
        row_data = EpisodeRowData(
            kind="duplicate",
            title=duplicate.original.name,
            status_text="Duplicate",
            status_tone="muted",
            filename=duplicate.original.name,
            tooltip=str(duplicate.reason),
        )
        if not self._passes_search(row_data):
            return None
        return _Entry(
            kind="duplicate",
            section_key=None,
            text=row_data.title,
            preview_index=preview_index,
            guide_row=None,
            row_data=row_data,
        )

    def _orphan_entry(self, companion) -> _Entry | None:
        row_data = EpisodeRowData(
            kind="orphan",
            title=companion.original.name,
            status_text="Orphan Companion",
            status_tone="muted",
            filename=companion.original.name,
        )
        if not self._passes_search(row_data):
            return None
        return _Entry(
            kind="orphan",
            section_key=None,
            text=row_data.title,
            preview_index=None,
            guide_row=None,
            row_data=row_data,
        )

    def _season_section_entries(self, state: ScanState, guide: EpisodeGuide):
        all_rows_by_season: dict[int, list[EpisodeGuideRow]] = {}
        for row in guide.rows:
            all_rows_by_season.setdefault(row.season, []).append(row)

        rows_by_season: dict[int, list[EpisodeGuideRow]] = {}
        for row in guide.rows:
            if self._filter_mode == "unmapped":
                continue
            if self._filter_mode == "problems" and row.status == "Mapped":
                continue
            rows_by_season.setdefault(row.season, []).append(row)

        for season_num, rows in sorted(rows_by_season.items()):
            section_key = self.season_section_key(season_num)
            auto_collapsed_key = f"{section_key}:auto-collapsed"
            season_rows = all_rows_by_season.get(season_num, rows)
            if (
                season_rows
                and all(row.status == "Missing File" for row in season_rows)
                and auto_collapsed_key not in self._collapsed_sections
            ):
                self._collapsed_sections.add(section_key)
                self._collapsed_sections.add(auto_collapsed_key)
            is_collapsed = section_key in self._collapsed_sections

            season_name = state.season_names.get(season_num, "")
            season_title = _season_label(season_num, name=season_name)
            season_title += self._season_ratio_text(state, season_num, rows)
            season_title += self._season_missing_text(state, season_num)
            prefix = _SECTION_COLLAPSED_PREFIX if is_collapsed else _SECTION_EXPANDED_PREFIX
            yield _Entry(
                kind="section-header",
                section_key=section_key,
                text=prefix + season_title,
                preview_index=None,
                guide_row=None,
                row_data=EpisodeRowData(kind="section-header", title=season_title, collapsed=is_collapsed),
                collapsible=True,
            )
            if is_collapsed:
                continue
            for row in rows:
                entry = self._episode_entry(state, row, section_key)
                if entry is not None:
                    yield entry

    def _season_ratio_text(self, state: ScanState, season_num: int, rows: list[EpisodeGuideRow]) -> str:
        completeness = state.completeness
        if completeness is None:
            return ""
        season = completeness.specials if season_num == 0 else completeness.seasons.get(season_num)
        if season is None or season.expected <= 0:
            return ""
        mapped = sum(1 for row in rows if row.primary_file is not None and row.status != "Conflict")
        return f" — {mapped}/{season.expected}"

    def _season_missing_text(self, state: ScanState, season_num: int) -> str:
        completeness = state.completeness
        if completeness is None:
            return ""
        season = completeness.specials if season_num == 0 else completeness.seasons.get(season_num)
        if season is None or season.is_complete or not season.missing:
            return ""
        numbers = [f"E{episode:02d}" for episode, _title in season.missing[:3]]
        text = ", ".join(numbers)
        if len(season.missing) > 3:
            text += ", …"
        return f" · missing {text}"

    def _episode_entry(self, state: ScanState, row: EpisodeGuideRow, section_key: str) -> _Entry | None:
        preview_index = None
        if row.primary_file is not None and row.primary_file in state.preview_items:
            preview_index = state.preview_items.index(row.primary_file)

        title = f"S{row.season:02d}E{row.episode:02d}"
        if row.title:
            title = f"{title} · {row.title}"

        filename = ""
        if row.primary_file is not None:
            filename = row.primary_file.original.name

        status_tone = _STATUS_TONE.get(row.status, "muted")
        row_data = EpisodeRowData(
            kind="episode",
            title=title,
            status_text=row.status,
            status_tone=status_tone,
            filename=filename,
            target=row.target_rename,
            confidence_pct=_percent_from_label(row.confidence_label),
            companion_count=len(row.companions),
            tooltip=row.target_rename or "",
        )
        if not self._passes_search(row_data):
            return None
        return _Entry(
            kind="episode",
            section_key=section_key,
            text=row_data.title,
            preview_index=preview_index,
            guide_row=row,
            row_data=row_data,
        )

    # -- Movie composition --------------------------------------------------

    def _build_movie_entries(self, state: ScanState, folder_preview: tuple[str, str] | None):
        if folder_preview is not None:
            yield from self._folder_section_entries(folder_preview)
        for index, preview in enumerate(state.preview_items):
            entry = self._movie_entry(state, index, preview)
            if entry is not None:
                yield entry

    def _movie_entry(self, state: ScanState, index: int, preview) -> _Entry | None:
        tone = _preview_status_tone(preview)
        tone = _PREVIEW_TONE_REMAP.get(tone, tone)
        approvable = _is_state_queue_approvable(state, media_type=self._media_type)
        checkable = preview.is_actionable and approvable
        checked = None
        if checkable:
            binding = state.check_vars.get(str(index))
            checked = binding.get() if binding is not None else False
        row_data = EpisodeRowData(
            kind="movie-file",
            title=preview.original.name,
            status_text=_preview_status_label(preview),
            status_tone=tone,
            target=preview.new_name or "",
            confidence_pct=clamped_percent(preview.episode_confidence),
            checked=checked,
            checkable=checkable,
            companion_count=len(preview.companions),
        )
        if not self._passes_search(row_data):
            return None
        return _Entry(
            kind="movie-file",
            section_key=None,
            text=row_data.title,
            preview_index=index,
            guide_row=None,
            row_data=row_data,
        )

    # -- Search --------------------------------------------------------------

    def _passes_search(self, row_data: EpisodeRowData) -> bool:
        if not self._search_text:
            return True
        haystacks = (row_data.title, row_data.filename, row_data.target)
        return any(self._search_text in haystack.casefold() for haystack in haystacks if haystack)


_STATUS_TONE = {
    "Mapped": "success",
    "Review": "warning",
    "Conflict": "error",
    "Missing File": "muted",
    "Unassigned": "warning",
    "Duplicate": "muted",
    "Orphan Companion": "muted",
}
