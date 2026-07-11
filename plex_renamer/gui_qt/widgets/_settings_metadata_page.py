"""Metadata export settings page (spec: local-metadata-artwork).

Master switch + per-artifact toggles. Persists directly through
SettingsService on every edit, like the AutoMux page. Settings are
frozen into each job's plan at queue time — changes here never affect
already-queued jobs.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..._mkv_locate import find_mkvpropedit
from .. import _scale
from ._settings_tab_sections import SettingsSectionCard


class MetadataSettingsPage(SettingsSectionCard):
    def __init__(self, settings_service=None, parent: QWidget | None = None) -> None:
        super().__init__("Metadata", parent=parent)
        self.setProperty("sectionRole", "page")
        self._settings = settings_service
        self._build_master_block()
        self._build_body()
        self._sync_body_enabled()

    # ── Master switch ─────────────────────────────────────────────────

    def _build_master_block(self) -> None:
        self._master_cb = QCheckBox(
            "Export local metadata with rename/AutoMux jobs")
        if self._settings is not None:
            self._master_cb.setChecked(
                bool(self._settings.get("metadata_enabled")))
        self._master_cb.toggled.connect(self._on_master_toggled)
        self.add_widget(self._master_cb)

        note = QLabel(
            "Writes Kodi/Jellyfin-style NFO files and artwork next to the "
            "renamed files so libraries browse fully offline. Plex picks up "
            "the artwork; descriptions on Plex still come from its own "
            "matching.")
        note.setProperty("cssClass", "caption")
        note.setWordWrap(True)
        self.add_widget(note)

    def _on_master_toggled(self, checked: bool) -> None:
        self._set_setting("metadata_enabled", bool(checked))
        self._sync_body_enabled()

    def _sync_body_enabled(self) -> None:
        self._body.setEnabled(self._master_cb.isChecked())

    # ── Body ──────────────────────────────────────────────────────────

    def _build_body(self) -> None:
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(_scale.px(10))

        body.addWidget(self._group_label("Sources"))
        source_row = QHBoxLayout()
        source_row.setSpacing(_scale.px(8))
        source_row.addWidget(QLabel("When metadata files already exist"))
        self._source_combo = QComboBox()
        self._source_combo.addItem("Always use TMDB", False)
        self._source_combo.addItem("Prefer existing local files", True)
        prefer_local = (bool(self._settings.get("metadata_prefer_local"))
                        if self._settings is not None else False)
        self._source_combo.setCurrentIndex(1 if prefer_local else 0)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        source_row.addWidget(self._source_combo)
        source_row.addStretch()
        body.addLayout(source_row)

        body.addWidget(self._group_label("Files to write"))
        self._nfo_cb = self._toggle(
            body, "Show/movie NFO", "metadata_write_nfo")
        self._episode_nfo_cb = self._toggle(
            body, "Episode NFOs", "metadata_write_episode_nfo")
        self._poster_cb = self._toggle(
            body, "Poster", "metadata_write_poster")
        self._fanart_cb = self._toggle(
            body, "Fanart (backdrop)", "metadata_write_fanart")
        self._season_posters_cb = self._toggle(
            body, "Season posters", "metadata_write_season_posters")
        self._episode_thumbs_cb = self._toggle(
            body, "Episode thumbnails (TMDB stills)",
            "metadata_write_episode_thumbs")
        self._clearlogo_cb = self._toggle(
            body, "Logo (clearlogo)", "metadata_write_clearlogo")
        self._plex_naming_cb = self._toggle(
            body, "Also write Plex-style artwork names",
            "metadata_plex_naming")
        plex_note = QLabel(
            "Duplicates season posters and episode thumbnails under the "
            "names Plex reads (Season01.jpg, episode-name.jpg).")
        plex_note.setProperty("cssClass", "caption")
        plex_note.setWordWrap(True)
        body.addWidget(plex_note)

        body.addWidget(self._group_label("Embedded metadata"))
        self._embed_title_cb = self._toggle(
            body, "Set the MKV title to the final name",
            "metadata_embed_title")
        self._propedit_status = QLabel("")
        self._propedit_status.setProperty("cssClass", "caption")
        self._propedit_status.setWordWrap(True)
        body.addWidget(self._propedit_status)
        self.refresh_propedit_status()

        self.add_widget(self._body)

    def refresh_propedit_status(self) -> None:
        explicit = (str(self._settings.get("mkvmerge_path"))
                    if self._settings is not None else "")
        found = find_mkvpropedit(explicit)
        if found is None:
            self._propedit_status.setText(
                "mkvpropedit was not found (it ships with MKVToolNix, next "
                "to mkvmerge). Titles are skipped until it is available; "
                "AutoMux jobs still embed titles during the mux.")
        else:
            self._propedit_status.setText(f"Found: {found}")

    # ── Row builders / persistence ────────────────────────────────────

    @staticmethod
    def _group_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("cssClass", "field-label")
        return label

    def _toggle(self, layout: QVBoxLayout, label: str, key: str) -> QCheckBox:
        box = QCheckBox(label)
        if self._settings is not None:
            box.setChecked(bool(self._settings.get(key)))
        box.toggled.connect(
            lambda checked, k=key: self._set_setting(k, bool(checked)))
        layout.addWidget(box)
        return box

    def _on_source_changed(self, index: int) -> None:
        self._set_setting(
            "metadata_prefer_local", bool(self._source_combo.itemData(index)))

    def _set_setting(self, key: str, value) -> None:
        if self._settings is not None:
            self._settings.set(key, value)
