"""AutoMux settings page (spec §3) — replaces the hidden Tools shell.

The page persists directly through SettingsService on every edit, like
the other settings pages. When mkvmerge cannot be resolved the body is
disabled and a notice explains why (spec §3.1).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..._lang_normalize import normalize_lang, normalize_lang_list
from ..._mkv_locate import find_mkvmerge
from ...engine._audio_codecs import DEFAULT_CODEC_WEIGHTS
from .. import _scale
from ._settings_page import SettingsSectionCard


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
            "Leave empty to auto-detect (PATH, then MKVToolNix install folder)"
        )
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
            self, "Locate mkvmerge", "", "mkvmerge (mkvmerge*)"
        )
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
                "above — AutoMux stays off until then."
            )
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
            body, "Merge external subtitles into the MKV", "automux_merge_subs"
        )
        self._merge_langs_edit = self._lang_list_row(
            body, "Merge languages (priority order, comma-separated)", "automux_merge_sub_languages"
        )
        self._lang_row(body, "Default subtitle language", "automux_default_sub_language")
        self._lang_row(
            body,
            "Language for untagged external subs (empty = und)",
            "automux_untagged_sub_language",
        )

        body.addWidget(self._group_label("Subtitle Stripping"))
        self._toggle(body, "Strip embedded subtitles not in the retain list", "automux_strip_subs")
        self._lang_list_row(body, "Retained subtitle languages", "automux_retain_sub_languages")

        body.addWidget(self._group_label("Audio Stripping"))
        self._toggle(body, "Strip embedded audio not in the retain list", "automux_strip_audio")
        self._lang_list_row(body, "Retained audio languages", "automux_retain_audio_languages")
        self._default_audio_edit = self._lang_row(
            body, "Default audio language", "automux_default_audio_language"
        )

        self._toggle(
            body,
            "When stripping, also drop commentary tracks (audio & subtitles)",
            "automux_exclude_commentary",
        )

        body.addWidget(self._group_label("Audio dedup"))
        self._dedupe_cb = self._toggle(
            body,
            "Remove redundant same-language audio tracks",
            "automux_dedupe_audio",
        )
        self._keep_per_layout_cb = self._toggle(
            body,
            "Keep the best track from every channel layout",
            "automux_dedupe_keep_per_layout",
        )
        self._lossless_policy_combo = self._build_lossless_policy_combo(body)
        self._tie_cb = self._toggle(
            body, "On ties, keep the smaller track", "automux_tie_prefer_smaller"
        )
        self._tolerance_spin = self._int_spin_row(
            body,
            "Tie tolerance (%)",
            "automux_tie_tolerance_pct",
            0,
            50,
        )
        self._transparency_spin = self._int_spin_row(
            body,
            "Transparency ceiling (kb/s per channel)",
            "automux_transparency_kbps_per_channel",
            32,
            512,
        )
        self._build_codec_weight_grid(body)

        body.addWidget(self._group_label("General"))
        self._convert_containers_cb = self._toggle(
            body, "Convert non-MKV containers to MKV", "automux_convert_containers"
        )
        self._toggle(body, "Strip track names from remuxed files", "automux_strip_track_names")
        self._no_fear_cb = self._toggle(body, "No Fear mode", "automux_no_fear")
        no_fear_note = QLabel(
            "Deletes the original source video and merged subtitle files "
            "after each successful remux. Irreversible."
        )
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
        box.toggled.connect(lambda checked, k=key: self._set_setting(k, bool(checked)))
        layout.addWidget(box)
        return box

    def _lang_list_row(self, layout: QVBoxLayout, label: str, key: str) -> QLineEdit:
        edit = self._labeled_edit(layout, label, "e.g. eng, jpn")
        if self._settings is not None:
            edit.setText(", ".join(str(v) for v in self._settings.get(key)))
        edit.editingFinished.connect(lambda e=edit, k=key: self._commit_lang_list(e, k))
        return edit

    def _lang_row(self, layout: QVBoxLayout, label: str, key: str) -> QLineEdit:
        edit = self._labeled_edit(layout, label, "e.g. eng")
        if self._settings is not None:
            edit.setText(str(self._settings.get(key)))
        edit.editingFinished.connect(lambda e=edit, k=key: self._commit_lang(e, k))
        return edit

    def _build_lossless_policy_combo(self, layout: QVBoxLayout) -> QComboBox:
        row = QHBoxLayout()
        row.setSpacing(_scale.px(8))
        row.addWidget(QLabel("Lossless track policy"))
        combo = QComboBox()
        combo.addItem("Prefer quality (keep lossless)", "quality")
        combo.addItem(
            "Prefer space (drop lossless when a transparent track exists "
            "— may reduce channel count)",
            "space",
        )
        if self._settings is not None:
            index = combo.findData(self._settings.automux_lossless_policy)
            combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(self._on_lossless_policy_changed)
        row.addWidget(combo, stretch=1)
        layout.addLayout(row)
        return combo

    def _on_lossless_policy_changed(self, index: int) -> None:
        self._set_setting("automux_lossless_policy", self._lossless_policy_combo.itemData(index))

    def _int_spin_row(
        self,
        layout: QVBoxLayout,
        label: str,
        key: str,
        minimum: int,
        maximum: int,
    ) -> QSpinBox:
        row = QHBoxLayout()
        row.setSpacing(_scale.px(8))
        row.addWidget(QLabel(label))
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        if self._settings is not None:
            spin.setValue(int(self._settings.get(key)))
        spin.valueChanged.connect(lambda value, k=key: self._set_setting(k, int(value)))
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    def _build_codec_weight_grid(self, layout: QVBoxLayout) -> None:
        layout.addWidget(self._group_label("Codec weights"))
        weights = self._settings.automux_codec_weights if self._settings is not None else {}
        grid = QGridLayout()
        grid.setSpacing(_scale.px(8))
        self._codec_weight_spins: dict[str, QDoubleSpinBox] = {}
        for row_index, (codec, default) in enumerate(DEFAULT_CODEC_WEIGHTS.items()):
            grid.addWidget(QLabel(codec), row_index, 0)
            spin = QDoubleSpinBox()
            spin.setRange(0.1, 5.0)
            spin.setSingleStep(0.1)
            spin.setDecimals(1)
            spin.setValue(float(weights.get(codec, default)))
            spin.valueChanged.connect(
                lambda value, c=codec: self._on_codec_weight_changed(c, value)
            )
            grid.addWidget(spin, row_index, 1)
            self._codec_weight_spins[codec] = spin
        layout.addLayout(grid)

        self._restore_weights_btn = QPushButton("Restore default weights")
        self._restore_weights_btn.setProperty("cssClass", "secondary")
        self._restore_weights_btn.clicked.connect(self._on_restore_default_weights)
        layout.addWidget(self._restore_weights_btn)

    def _on_codec_weight_changed(self, codec: str, value: float) -> None:
        if self._settings is None:
            return
        weights = dict(self._settings.automux_codec_weights)
        weights[codec] = round(float(value), 1)
        self._settings.automux_codec_weights = weights

    def _on_restore_default_weights(self) -> None:
        if self._settings is not None:
            self._settings.automux_codec_weights = {}
        for codec, spin in self._codec_weight_spins.items():
            spin.blockSignals(True)
            spin.setValue(DEFAULT_CODEC_WEIGHTS[codec])
            spin.blockSignals(False)

    def _labeled_edit(
        self,
        layout: QVBoxLayout,
        label: str,
        placeholder: str,
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
            part.strip() for part in edit.text().split(",") if part.strip()
        )
        self._set_setting(key, normalized)
        edit.setText(", ".join(normalized))

    def _commit_lang(self, edit: QLineEdit, key: str) -> None:
        normalized = normalize_lang(edit.text().strip()) or ""
        self._set_setting(key, normalized)
        edit.setText(normalized)
