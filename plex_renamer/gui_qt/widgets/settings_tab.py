"""Settings tab — Phase 3 implementation.

Single scrollable column with section cards for Display, Matching,
API Keys, Cache, and Advanced settings.  All state goes through
SettingsService.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    QScrollArea,
    QSizePolicy,
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


class SettingsTab(QScrollArea):
    """Scrollable settings panel with section cards."""

    def __init__(
        self,
        settings_service: "SettingsService | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_service
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
        self._build_advanced_section()

        self._layout.addStretch()
        self.setWidget(content)

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
        self._clear_cache_btn = QPushButton("Clear TMDB Cache (not yet wired)")
        self._clear_cache_btn.setProperty("cssClass", "secondary")
        self._clear_cache_btn.setEnabled(False)
        self._clear_cache_btn.setToolTip("Will be wired to PersistentCacheService in Phase 4")
        row.addWidget(self._clear_cache_btn)

        self._clear_all_btn = QPushButton("Clear All Data (not yet wired)")
        self._clear_all_btn.setProperty("cssClass", "danger")
        self._clear_all_btn.setEnabled(False)
        self._clear_all_btn.setToolTip("Will be wired with confirmation dialog in Phase 4")
        row.addWidget(self._clear_all_btn)
        row.addStretch()
        section.add_layout(row)

        self._cache_confirm = QLabel("")
        self._cache_confirm.setProperty("cssClass", "caption")
        section.add_widget(self._cache_confirm)

        self._layout.addWidget(section)

    # ── Advanced ─────────────────────────────────────────────────

    def _build_advanced_section(self) -> None:
        group = QGroupBox("Advanced")
        group_layout = QVBoxLayout(group)

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

        self._layout.addWidget(group)

    # ── Callbacks ────────────────────────────────────────────────

    def _on_view_mode(self, index: int) -> None:
        if self._settings:
            self._settings.view_mode = "compact" if index == 1 else "normal"

    def _on_companion(self, checked: bool) -> None:
        if self._settings:
            self._settings.show_companion_files = checked

    def _on_discovery(self, checked: bool) -> None:
        if self._settings:
            self._settings.show_discovery_info = checked

    def _on_language(self, display: str) -> None:
        tag = _LANGUAGE_OPTIONS.get(display, "en-US")
        if self._settings:
            self._settings.match_language = tag

    def _on_threshold(self, value: int) -> None:
        fval = value / 100
        self._threshold_label.setText(f"{fval:.2f}")
        if self._settings:
            self._settings.auto_accept_threshold = fval

    def _on_confidence_bars(self, checked: bool) -> None:
        if self._settings:
            self._settings.show_confidence_bars = checked

    def _on_save_key(self) -> None:
        key = self._api_key_input.text().strip()
        if not key:
            self._key_status.setText("Please enter an API key.")
            self._key_status.setStyleSheet("color: #d44040;")
            return
        try:
            from ...keys import save_api_key
            save_api_key("TMDB", key)
            self._key_status.setText("API key saved.")
            self._key_status.setStyleSheet("color: #3ea463;")
        except Exception as e:
            self._key_status.setText(f"Save failed: {e}")
            self._key_status.setStyleSheet("color: #d44040;")

    def _on_test_key(self) -> None:
        key = self._api_key_input.text().strip()
        if not key:
            self._key_status.setText("Enter a key first.")
            self._key_status.setStyleSheet("color: #d44040;")
            return
        self._key_status.setText("Testing...")
        self._key_status.setStyleSheet("color: #777777;")
        self._test_key_btn.setEnabled(False)

        import threading

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

            # Marshal result back to main thread via QTimer.singleShot
            from PySide6.QtCore import QTimer
            if ok:
                QTimer.singleShot(0, lambda: self._show_test_result(True, ""))
            else:
                QTimer.singleShot(0, lambda: self._show_test_result(False, str(code)))

        threading.Thread(target=_test_worker, daemon=True).start()

    def _show_test_result(self, success: bool, detail: str) -> None:
        self._test_key_btn.setEnabled(True)
        if success:
            self._key_status.setText("TMDB connection successful.")
            self._key_status.setStyleSheet("color: #3ea463;")
        else:
            self._key_status.setText(f"TMDB test failed: {detail}")
            self._key_status.setStyleSheet("color: #d44040;")


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
        sep.setStyleSheet("background-color: #3a3a3a; max-height: 1px;")
        self._layout.addWidget(sep)

    def add_widget(self, widget: QWidget) -> None:
        self._layout.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._layout.addLayout(layout)
