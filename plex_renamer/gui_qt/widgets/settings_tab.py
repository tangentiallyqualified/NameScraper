"""Settings tab — Phase 3 implementation.

Single scrollable column with section cards for Display, Matching,
API Keys, Cache, and Advanced settings.  All state goes through
SettingsService.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from ...app.services.settings_service import SettingsService

# Language options: display name → TMDB language tag
_LANGUAGE_OPTIONS = {
    "English (US)": "en-US",
    "English (UK)": "en-GB",
    "French": "fr-FR",
    "German": "de-DE",
    "Spanish (Spain)": "es-ES",
    "Spanish (Latin America)": "es-MX",
    "Italian": "it-IT",
    "Portuguese (Brazil)": "pt-BR",
    "Portuguese (Portugal)": "pt-PT",
    "Japanese": "ja-JP",
    "Korean": "ko-KR",
    "Chinese (Simplified)": "zh-CN",
    "Chinese (Traditional)": "zh-TW",
    "Russian": "ru-RU",
    "Dutch": "nl-NL",
    "Swedish": "sv-SE",
    "Danish": "da-DK",
    "Norwegian": "no-NO",
    "Finnish": "fi-FI",
    "Polish": "pl-PL",
    "Turkish": "tr-TR",
    "Arabic": "ar-SA",
    "Hindi": "hi-IN",
    "Thai": "th-TH",
}

_TAG_TO_DISPLAY = {v: k for k, v in _LANGUAGE_OPTIONS.items()}


class _ApiKeyTestBridge(QObject):
    result_ready = Signal(bool, str)


class SettingsTab(QScrollArea):
    """Scrollable settings panel with section cards."""

    view_mode_changed = Signal(str)
    companion_visibility_changed = Signal(bool)
    discovery_visibility_changed = Signal(bool)
    language_changed = Signal(str)
    threshold_changed = Signal(float)
    api_key_saved = Signal()
    history_cleared = Signal()

    def __init__(
        self,
        settings_service: "SettingsService | None" = None,
        cache_service=None,
        clear_tmdb_callback: Callable[[], None] | None = None,
        clear_history_callback: Callable[[], tuple[int, int]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self._cache_service = cache_service
        self._clear_tmdb_callback = clear_tmdb_callback
        self._clear_history_callback = clear_history_callback
        self._api_test_bridge = _ApiKeyTestBridge(self)
        self._api_test_bridge.result_ready.connect(self._show_test_result)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(32, 24, 32, 24)
        self._layout.setSpacing(16)

        self._build_display_section()
        self._build_matching_section()
        self._build_api_keys_section()
        self._build_cache_section()
        self._build_data_management_section()
        self._build_advanced_section()

        self._layout.addStretch()
        self.setWidget(content)
        self._refresh_cache_stats()

    # ── Display ──────────────────────────────────────────────────

    def _build_display_section(self) -> None:
        section = _SectionCard("Display")

        # View mode
        row = QHBoxLayout()
        row.addWidget(QLabel("Default view mode"))
        self._view_mode_combo = QComboBox()
        self._view_mode_combo.addItems(["Normal", "Compact"])
        if self._settings and self._settings.view_mode == "compact":
            self._view_mode_combo.setCurrentIndex(1)
        self._view_mode_combo.currentIndexChanged.connect(self._on_view_mode)
        row.addWidget(self._view_mode_combo)
        row.addStretch()
        section.add_layout(row)

        # Show companion files
        self._companion_cb = QCheckBox("Show companion files in preview")
        if self._settings:
            self._companion_cb.setChecked(self._settings.show_companion_files)
        self._companion_cb.toggled.connect(self._on_companion)
        section.add_widget(self._companion_cb)

        # Show discovery info
        self._discovery_cb = QCheckBox("Show discovery info in detail panel")
        if self._settings:
            self._discovery_cb.setChecked(self._settings.show_discovery_info)
        self._discovery_cb.toggled.connect(self._on_discovery)
        section.add_widget(self._discovery_cb)

        self._layout.addWidget(section)

    # ── Matching ─────────────────────────────────────────────────

    def _build_matching_section(self) -> None:
        section = _SectionCard("Matching")

        # Match language
        row = QHBoxLayout()
        row.addWidget(QLabel("Match language"))
        self._lang_combo = QComboBox()
        self._lang_combo.addItems(list(_LANGUAGE_OPTIONS.keys()))
        if self._settings:
            current = _TAG_TO_DISPLAY.get(self._settings.match_language, "English (US)")
            idx = self._lang_combo.findText(current)
            if idx >= 0:
                self._lang_combo.setCurrentIndex(idx)
        self._lang_combo.currentTextChanged.connect(self._on_language)
        row.addWidget(self._lang_combo)
        row.addStretch()
        section.add_layout(row)

        # Auto-accept threshold
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Auto-accept confidence threshold"))
        self._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self._threshold_slider.setRange(50, 100)
        self._threshold_slider.setSingleStep(1)
        current_val = 85
        if self._settings:
            current_val = int(self._settings.auto_accept_threshold * 100)
        self._threshold_slider.setValue(current_val)
        self._threshold_slider.setFixedWidth(200)
        row2.addWidget(self._threshold_slider)

        self._threshold_label = QLabel(f"{current_val / 100:.2f}")
        self._threshold_label.setFixedWidth(40)
        row2.addWidget(self._threshold_label)
        row2.addStretch()

        self._threshold_slider.valueChanged.connect(self._on_threshold)
        section.add_layout(row2)

        # Show confidence bars
        self._confidence_cb = QCheckBox("Show episode confidence bars in preview")
        if self._settings:
            self._confidence_cb.setChecked(self._settings.show_confidence_bars)
        self._confidence_cb.toggled.connect(self._on_confidence_bars)
        section.add_widget(self._confidence_cb)

        self._layout.addWidget(section)

    # ── API Keys ─────────────────────────────────────────────────

    def _build_api_keys_section(self) -> None:
        section = _SectionCard("API Keys")

        row = QHBoxLayout()
        row.addWidget(QLabel("TMDB API key"))
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("Enter TMDB API key...")
        self._api_key_input.setMinimumWidth(280)

        # Try loading existing key
        try:
            from ...keys import get_api_key
            existing = get_api_key("TMDB")
            if existing:
                self._api_key_input.setText(existing)
        except Exception:
            pass

        row.addWidget(self._api_key_input)

        self._save_key_btn = QPushButton("Save")
        self._save_key_btn.setFixedWidth(60)
        self._save_key_btn.clicked.connect(self._on_save_key)
        row.addWidget(self._save_key_btn)

        self._test_key_btn = QPushButton("Test")
        self._test_key_btn.setProperty("cssClass", "secondary")
        self._test_key_btn.setFixedWidth(60)
        self._test_key_btn.clicked.connect(self._on_test_key)
        row.addWidget(self._test_key_btn)
        row.addStretch()

        section.add_layout(row)

        self._key_status = QLabel("")
        self._key_status.setProperty("cssClass", "caption")
        section.add_widget(self._key_status)

        self._layout.addWidget(section)

    # ── Cache ────────────────────────────────────────────────────

    def _build_cache_section(self) -> None:
        section = _SectionCard("Cache")

        # Stats row (populated when cache is available)
        self._cache_stats = QLabel("Cache statistics will appear here after first scan.")
        self._cache_stats.setProperty("cssClass", "text-dim")
        section.add_widget(self._cache_stats)

        # Buttons
        row = QHBoxLayout()
        self._clear_cache_btn = QPushButton("Clear TMDB Cache")
        self._clear_cache_btn.setProperty("cssClass", "secondary")
        self._clear_cache_btn.setEnabled(self._cache_service is not None)
        self._clear_cache_btn.clicked.connect(self._on_clear_cache)
        if self._cache_service is None:
            self._clear_cache_btn.setToolTip("Cache actions are not available yet.")
        row.addWidget(self._clear_cache_btn)

        self._clear_all_btn = QPushButton("Clear All Data")
        self._clear_all_btn.setProperty("cssClass", "danger")
        self._clear_all_btn.hide()
        row.addWidget(self._clear_all_btn)
        row.addStretch()
        section.add_layout(row)

        self._cache_confirm = QLabel("")
        self._cache_confirm.setProperty("cssClass", "caption")
        section.add_widget(self._cache_confirm)

        self._layout.addWidget(section)

    # ── Data Management ──────────────────────────────────────────

    def _build_data_management_section(self) -> None:
        section = _SectionCard("Data Management")

        row = QHBoxLayout()
        self._clear_history_btn = QPushButton("Clear Job History")
        self._clear_history_btn.setProperty("cssClass", "danger")
        self._clear_history_btn.setEnabled(self._clear_history_callback is not None)
        self._clear_history_btn.clicked.connect(self._on_clear_history)
        row.addWidget(self._clear_history_btn)
        row.addStretch()
        section.add_layout(row)

        self._history_confirm = QLabel("")
        self._history_confirm.setProperty("cssClass", "caption")
        section.add_widget(self._history_confirm)

        self._layout.addWidget(section)

    def _on_clear_history(self) -> None:
        if self._clear_history_callback is None:
            return
        if QMessageBox.question(
            self,
            "Clear Job History",
            "Delete all job history entries?\n\nStored undo data for revertible jobs will be lost.",
        ) != QMessageBox.StandardButton.Yes:
            return
        count, revertible = self._clear_history_callback()
        noun = "entry" if count == 1 else "entries"
        self._history_confirm.setProperty("tone", "success")
        self._history_confirm.setText(f"Cleared {count} history {noun}.")
        _repolish(self._history_confirm)
        self.history_cleared.emit()

    # ── Advanced ─────────────────────────────────────────────────

    def _build_advanced_section(self) -> None:
        self._advanced_group = QGroupBox("Advanced")
        self._advanced_group.hide()
        group_layout = QVBoxLayout(self._advanced_group)

        row = QHBoxLayout()
        row.addWidget(QLabel("Log level"))
        self._log_combo = QComboBox()
        self._log_combo.addItems(["Normal", "Verbose", "Debug"])
        row.addWidget(self._log_combo)
        row.addStretch()
        group_layout.addLayout(row)

        self._export_log_btn = QPushButton("Export Diagnostic Log")
        self._export_log_btn.setProperty("cssClass", "secondary")
        self._export_log_btn.setFixedWidth(200)
        group_layout.addWidget(self._export_log_btn)

        self._layout.addWidget(self._advanced_group)

    # ── Callbacks ────────────────────────────────────────────────

    def sync_view_mode(self, mode: str) -> None:
        self._view_mode_combo.blockSignals(True)
        self._view_mode_combo.setCurrentIndex(1 if mode == "compact" else 0)
        self._view_mode_combo.blockSignals(False)

    def sync_companion_visibility(self, checked: bool) -> None:
        self._companion_cb.blockSignals(True)
        self._companion_cb.setChecked(checked)
        self._companion_cb.blockSignals(False)

    def sync_discovery_visibility(self, checked: bool) -> None:
        self._discovery_cb.blockSignals(True)
        self._discovery_cb.setChecked(checked)
        self._discovery_cb.blockSignals(False)

    def sync_language(self, tag: str) -> None:
        display = _TAG_TO_DISPLAY.get(tag, "English (US)")
        index = self._lang_combo.findText(display)
        if index < 0:
            index = 0
        self._lang_combo.blockSignals(True)
        self._lang_combo.setCurrentIndex(index)
        self._lang_combo.blockSignals(False)

    def _on_view_mode(self, index: int) -> None:
        mode = "compact" if index == 1 else "normal"
        if self._settings:
            self._settings.view_mode = mode
        self.view_mode_changed.emit(mode)

    def _on_companion(self, checked: bool) -> None:
        if self._settings:
            self._settings.show_companion_files = checked
        self.companion_visibility_changed.emit(checked)

    def _on_discovery(self, checked: bool) -> None:
        if self._settings:
            self._settings.show_discovery_info = checked
        self.discovery_visibility_changed.emit(checked)

    def _on_language(self, display: str) -> None:
        tag = _LANGUAGE_OPTIONS.get(display, "en-US")
        if self._settings:
            self._settings.match_language = tag
        self.language_changed.emit(tag)

    def _on_threshold(self, value: int) -> None:
        fval = value / 100
        self._threshold_label.setText(f"{fval:.2f}")
        if self._settings:
            self._settings.auto_accept_threshold = fval
        self.threshold_changed.emit(fval)

    def _on_confidence_bars(self, checked: bool) -> None:
        if self._settings:
            self._settings.show_confidence_bars = checked

    def _on_save_key(self) -> None:
        key = self._api_key_input.text().strip()
        if not key:
            self._set_key_status("Please enter an API key.", "error")
            return
        try:
            from ...keys import save_api_key
            save_api_key("TMDB", key)
            self._set_key_status("API key saved.", "success")
            self.api_key_saved.emit()
        except Exception as e:
            self._set_key_status(f"Save failed: {e}", "error")

    def _on_test_key(self) -> None:
        key = self._api_key_input.text().strip()
        if not key:
            self._set_key_status("Enter a key first.", "error")
            return
        self._set_key_status("Testing...", "muted")
        self._test_key_btn.setEnabled(False)
        bridge = self._api_test_bridge

        def _test_worker() -> None:
            try:
                import requests
                resp = requests.get(
                    "https://api.themoviedb.org/3/configuration",
                    params={"api_key": key},
                    timeout=5,
                )
                ok = resp.ok
                code = resp.status_code
            except Exception as e:
                ok = False
                code = str(e)

            try:
                bridge.result_ready.emit(ok, "" if ok else str(code))
            except RuntimeError:
                pass

        threading.Thread(target=_test_worker, daemon=True).start()

    def _show_test_result(self, success: bool, detail: str) -> None:
        self._test_key_btn.setEnabled(True)
        if success:
            self._set_key_status("TMDB connection successful.", "success")
        else:
            self._set_key_status(f"TMDB test failed: {detail}", "error")

    def _on_clear_cache(self) -> None:
        if self._cache_service is None:
            return
        removed = self._cache_service.invalidate_namespace("tmdb")
        if self._clear_tmdb_callback is not None:
            self._clear_tmdb_callback()
        noun = "entry" if removed == 1 else "entries"
        self._cache_confirm.setProperty("tone", "success")
        self._cache_confirm.setText(f"Cleared {removed} TMDB cache {noun}.")
        _repolish(self._cache_confirm)
        self._refresh_cache_stats()

    def _refresh_cache_stats(self) -> None:
        if self._cache_service is None:
            self._cache_stats.setText("Cache actions are unavailable in this context.")
            return
        stats = self._cache_service.stats()
        self._cache_stats.setText(
            f"{stats['item_count']} entries · {_format_bytes(stats['total_size_bytes'])} used "
            f"· cap {_format_bytes(stats['max_size_bytes'])} / {stats['max_items']} items"
        )

    def _set_key_status(self, text: str, tone: str) -> None:
        self._key_status.setText(text)
        self._key_status.setProperty("tone", tone)
        _repolish(self._key_status)


class _SectionCard(QFrame):
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

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setProperty("cssClass", "separator")
        sep.setFixedHeight(1)
        self._layout.addWidget(sep)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)


def _format_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
