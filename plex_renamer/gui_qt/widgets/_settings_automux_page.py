"""AutoMux settings page (spec §3) — replaces the hidden Tools shell.

The page persists directly through SettingsService on every edit, like
the other settings pages. When mkvmerge cannot be resolved the body is
disabled and a notice explains why (spec §3.1).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..._lang_normalize import normalize_lang, normalize_lang_list
from ..._mkv_locate import find_mkvmerge
from .. import _scale
from ._settings_tab_sections import SettingsSectionCard


class AutoMuxSettingsPage(SettingsSectionCard):
    def __init__(self, settings_service=None, parent: QWidget | None = None) -> None:
        super().__init__("AutoMux", parent=parent)
        self.setProperty("sectionRole", "page")
        self._settings = settings_service
        self._build_binary_row()
        self._build_body()
        self.refresh_binary_status()

    # ── mkvmerge binary ───────────────────────────────────────────────

    def _build_binary_row(self) -> None:
        wrapper = QVBoxLayout()
        wrapper.setSpacing(_scale.px(6))
        title = QLabel("mkvmerge path")
        title.setProperty("cssClass", "field-label")
        wrapper.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(_scale.px(8))
        self._path_edit = QLineEdit()
        self._path_edit.setProperty("cssClass", "path-input")
        self._path_edit.setPlaceholderText(
            "Leave empty to auto-detect (PATH, then MKVToolNix install folder)")
        if self._settings is not None:
            self._path_edit.setText(self._settings.mkvmerge_path)
        self._path_edit.editingFinished.connect(self._on_path_edited)
        row.addWidget(self._path_edit, stretch=1)

        browse = QPushButton("Browse")
        browse.setProperty("cssClass", "secondary")
        browse.clicked.connect(self._on_browse)
        row.addWidget(browse)
        wrapper.addLayout(row)

        self._binary_status = QLabel("")
        self._binary_status.setProperty("cssClass", "caption")
        self._binary_status.setWordWrap(True)
        wrapper.addWidget(self._binary_status)
        self.add_layout(wrapper)

    def _on_browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Locate mkvmerge", "", "mkvmerge (mkvmerge*)")
        if path:
            self._path_edit.setText(path)
            self._on_path_edited()

    def _on_path_edited(self) -> None:
        if self._settings is not None:
            self._settings.mkvmerge_path = self._path_edit.text().strip()
        self.refresh_binary_status()

    def refresh_binary_status(self) -> None:
        explicit = self._settings.mkvmerge_path if self._settings else ""
        found = find_mkvmerge(explicit)
        if found is None:
            self._binary_status.setText(
                "mkvmerge was not found. Install MKVToolNix or set the path "
                "above — AutoMux stays off until then.")
        else:
            self._binary_status.setText(f"Found: {found}")
        self._body.setEnabled(found is not None)

    # ── Body (everything gated on the binary) ─────────────────────────

    def _build_body(self) -> None:
        self._body = QWidget()
        body = QVBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(_scale.px(10))

        body.addWidget(self._group_label("Subtitle Merging"))
        self._merge_subs_cb = self._toggle(
            body, "Merge external subtitles into the MKV", "automux_merge_subs")
        self._merge_langs_edit = self._lang_list_row(
            body, "Merge languages (priority order, comma-separated)",
            "automux_merge_sub_languages")
        self._lang_row(
            body, "Default subtitle language", "automux_default_sub_language")
        self._lang_row(
            body, "Language for untagged external subs (empty = und)",
            "automux_untagged_sub_language")

        body.addWidget(self._group_label("Subtitle Stripping"))
        self._toggle(
            body, "Strip embedded subtitles not in the retain list",
            "automux_strip_subs")
        self._lang_list_row(
            body, "Retained subtitle languages", "automux_retain_sub_languages")

        body.addWidget(self._group_label("Audio Stripping"))
        self._toggle(
            body, "Strip embedded audio not in the retain list",
            "automux_strip_audio")
        self._lang_list_row(
            body, "Retained audio languages", "automux_retain_audio_languages")
        self._default_audio_edit = self._lang_row(
            body, "Default audio language", "automux_default_audio_language")

        body.addWidget(self._group_label("General"))
        self._toggle(
            body, "Strip track names from remuxed files",
            "automux_strip_track_names")
        self._no_fear_cb = self._toggle(
            body, "No Fear mode", "automux_no_fear")
        no_fear_note = QLabel(
            "Deletes the original source video and merged subtitle files "
            "after each successful remux. Irreversible.")
        no_fear_note.setProperty("cssClass", "caption")
        no_fear_note.setWordWrap(True)
        body.addWidget(no_fear_note)

        self.add_widget(self._body)

    # ── Row builders ──────────────────────────────────────────────────

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

    def _lang_list_row(self, layout: QVBoxLayout, label: str, key: str) -> QLineEdit:
        edit = self._labeled_edit(layout, label, "e.g. eng, jpn")
        if self._settings is not None:
            edit.setText(", ".join(str(v) for v in self._settings.get(key)))
        edit.editingFinished.connect(
            lambda e=edit, k=key: self._commit_lang_list(e, k))
        return edit

    def _lang_row(self, layout: QVBoxLayout, label: str, key: str) -> QLineEdit:
        edit = self._labeled_edit(layout, label, "e.g. eng")
        if self._settings is not None:
            edit.setText(str(self._settings.get(key)))
        edit.editingFinished.connect(
            lambda e=edit, k=key: self._commit_lang(e, k))
        return edit

    def _labeled_edit(
        self, layout: QVBoxLayout, label: str, placeholder: str,
    ) -> QLineEdit:
        row = QHBoxLayout()
        row.setSpacing(_scale.px(8))
        title = QLabel(label)
        row.addWidget(title)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setMinimumWidth(_scale.px(180))
        row.addWidget(edit)
        row.addStretch()
        layout.addLayout(row)
        return edit

    # ── Persistence ───────────────────────────────────────────────────

    def _set_setting(self, key: str, value) -> None:
        if self._settings is not None:
            self._settings.set(key, value)

    def _commit_lang_list(self, edit: QLineEdit, key: str) -> None:
        normalized = normalize_lang_list(
            part.strip() for part in edit.text().split(",") if part.strip())
        self._set_setting(key, normalized)
        edit.setText(", ".join(normalized))

    def _commit_lang(self, edit: QLineEdit, key: str) -> None:
        normalized = normalize_lang(edit.text().strip()) or ""
        self._set_setting(key, normalized)
        edit.setText(normalized)
