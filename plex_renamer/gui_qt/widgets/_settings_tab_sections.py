"""Section-building helpers for the settings tab."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class SettingsSectionCard(QFrame):
    """A settings section card with a heading and content area."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("cssClass", "settings-section")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)

        heading = QLabel(title)
        heading.setProperty("cssClass", "heading")
        self._layout.addWidget(heading)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setProperty("cssClass", "separator")
        separator.setFixedHeight(1)
        self._layout.addWidget(separator)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


class SettingsTabSectionsBuilder:
    def __init__(
        self,
        tab: Any,
        *,
        language_options: dict[str, str],
        tag_to_display: dict[str, str],
    ) -> None:
        self._tab = tab
        self._language_options = language_options
        self._tag_to_display = tag_to_display

    def build_display_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard("Display")

        row = QHBoxLayout()
        row.addWidget(QLabel("Default view mode"))
        tab._view_mode_combo = QComboBox()
        tab._view_mode_combo.addItems(["Normal", "Compact"])
        if tab._settings and tab._settings.view_mode == "compact":
            tab._view_mode_combo.setCurrentIndex(1)
        tab._view_mode_combo.currentIndexChanged.connect(tab._on_view_mode)
        row.addWidget(tab._view_mode_combo)
        row.addStretch()
        section.add_layout(row)

        tab._companion_cb = QCheckBox("Show companion files in preview")
        if tab._settings:
            tab._companion_cb.setChecked(tab._settings.show_companion_files)
        tab._companion_cb.toggled.connect(tab._on_companion)
        section.add_widget(tab._companion_cb)

        tab._discovery_cb = QCheckBox("Show discovery info in detail panel")
        if tab._settings:
            tab._discovery_cb.setChecked(tab._settings.show_discovery_info)
        tab._discovery_cb.toggled.connect(tab._on_discovery)
        section.add_widget(tab._discovery_cb)

        tab._layout.addWidget(section)

    def build_matching_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard("Matching")

        row = QHBoxLayout()
        row.addWidget(QLabel("Match language"))
        tab._lang_combo = QComboBox()
        tab._lang_combo.addItems(list(self._language_options.keys()))
        if tab._settings:
            current = self._tag_to_display.get(tab._settings.match_language, "English (US)")
            index = tab._lang_combo.findText(current)
            if index >= 0:
                tab._lang_combo.setCurrentIndex(index)
        tab._lang_combo.currentTextChanged.connect(tab._on_language)
        row.addWidget(tab._lang_combo)
        row.addStretch()
        section.add_layout(row)

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Auto-accept confidence threshold"))
        tab._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        tab._threshold_slider.setRange(50, 100)
        tab._threshold_slider.setSingleStep(1)
        current_value = 85
        if tab._settings:
            current_value = int(tab._settings.auto_accept_threshold * 100)
        tab._threshold_slider.setValue(current_value)
        tab._threshold_slider.setFixedWidth(200)
        threshold_row.addWidget(tab._threshold_slider)

        tab._threshold_label = QLabel(f"{current_value / 100:.2f}")
        tab._threshold_label.setFixedWidth(40)
        threshold_row.addWidget(tab._threshold_label)
        threshold_row.addStretch()

        tab._threshold_slider.valueChanged.connect(tab._on_threshold)
        section.add_layout(threshold_row)

        episode_threshold_row = QHBoxLayout()
        episode_threshold_row.addWidget(QLabel("Episode auto-map confidence threshold"))
        tab._episode_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        tab._episode_threshold_slider.setRange(50, 100)
        tab._episode_threshold_slider.setSingleStep(1)
        episode_current_value = 85
        if tab._settings:
            episode_current_value = int(tab._settings.episode_auto_accept_threshold * 100)
        tab._episode_threshold_slider.setValue(episode_current_value)
        tab._episode_threshold_slider.setFixedWidth(200)
        episode_threshold_row.addWidget(tab._episode_threshold_slider)

        tab._episode_threshold_label = QLabel(f"{episode_current_value / 100:.2f}")
        tab._episode_threshold_label.setFixedWidth(40)
        episode_threshold_row.addWidget(tab._episode_threshold_label)
        episode_threshold_row.addStretch()

        tab._episode_threshold_slider.valueChanged.connect(tab._on_episode_threshold)
        section.add_layout(episode_threshold_row)

        tab._confidence_cb = QCheckBox("Show episode confidence bars in preview")
        if tab._settings:
            tab._confidence_cb.setChecked(tab._settings.show_confidence_bars)
        tab._confidence_cb.toggled.connect(tab._on_confidence_bars)
        section.add_widget(tab._confidence_cb)

        tab._layout.addWidget(section)

    def build_api_keys_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard("API Keys")

        row = QHBoxLayout()
        row.addWidget(QLabel("TMDB API key"))
        tab._api_key_input = QLineEdit()
        tab._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        tab._api_key_input.setPlaceholderText("Enter TMDB API key...")
        tab._api_key_input.setMinimumWidth(280)

        try:
            from ...keys import get_api_key

            existing = get_api_key("TMDB")
            if existing:
                tab._api_key_input.setText(existing)
        except Exception:
            pass

        row.addWidget(tab._api_key_input)

        tab._save_key_btn = QPushButton("Save")
        tab._save_key_btn.setFixedWidth(60)
        tab._save_key_btn.clicked.connect(tab._on_save_key)
        row.addWidget(tab._save_key_btn)

        tab._test_key_btn = QPushButton("Test")
        tab._test_key_btn.setProperty("cssClass", "secondary")
        tab._test_key_btn.setFixedWidth(60)
        tab._test_key_btn.clicked.connect(tab._on_test_key)
        row.addWidget(tab._test_key_btn)
        row.addStretch()

        section.add_layout(row)

        tab._key_status = QLabel("")
        tab._key_status.setProperty("cssClass", "caption")
        section.add_widget(tab._key_status)

        tab._layout.addWidget(section)

    def build_cache_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard("Cache")

        tab._cache_stats = QLabel("Cache statistics will appear here after first scan.")
        tab._cache_stats.setProperty("cssClass", "text-dim")
        section.add_widget(tab._cache_stats)

        row = QHBoxLayout()
        tab._clear_cache_btn = QPushButton("Clear TMDB Cache")
        tab._clear_cache_btn.setProperty("cssClass", "secondary")
        tab._clear_cache_btn.setEnabled(tab._cache_service is not None)
        tab._clear_cache_btn.clicked.connect(tab._on_clear_cache)
        if tab._cache_service is None:
            tab._clear_cache_btn.setToolTip("Cache actions are not available yet.")
        row.addWidget(tab._clear_cache_btn)

        tab._clear_all_btn = QPushButton("Clear All Data")
        tab._clear_all_btn.setProperty("cssClass", "danger")
        tab._clear_all_btn.hide()
        row.addWidget(tab._clear_all_btn)
        row.addStretch()
        section.add_layout(row)

        tab._cache_confirm = QLabel("")
        tab._cache_confirm.setProperty("cssClass", "caption")
        section.add_widget(tab._cache_confirm)

        tab._layout.addWidget(section)

    def build_data_management_section(self) -> None:
        tab = self._tab
        section = SettingsSectionCard("Data Management")

        row = QHBoxLayout()
        tab._clear_history_btn = QPushButton("Clear Job History")
        tab._clear_history_btn.setProperty("cssClass", "danger")
        tab._clear_history_btn.setEnabled(tab._clear_history_callback is not None)
        tab._clear_history_btn.clicked.connect(tab._on_clear_history)
        row.addWidget(tab._clear_history_btn)
        row.addStretch()
        section.add_layout(row)

        tab._history_confirm = QLabel("")
        tab._history_confirm.setProperty("cssClass", "caption")
        section.add_widget(tab._history_confirm)

        tab._layout.addWidget(section)

    def build_advanced_section(self) -> None:
        tab = self._tab
        tab._advanced_group = QGroupBox("Advanced")
        tab._advanced_group.hide()
        group_layout = QVBoxLayout(tab._advanced_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Log level"))
        tab._log_combo = QComboBox()
        tab._log_combo.addItems(["Normal", "Verbose", "Debug"])
        row.addWidget(tab._log_combo)
        row.addStretch()
        group_layout.addLayout(row)

        tab._export_log_btn = QPushButton("Export Diagnostic Log")
        tab._export_log_btn.setProperty("cssClass", "secondary")
        tab._export_log_btn.setFixedWidth(200)
        group_layout.addWidget(tab._export_log_btn)

        tab._layout.addWidget(tab._advanced_group)
