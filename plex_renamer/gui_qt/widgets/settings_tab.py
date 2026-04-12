"""Settings tab — Phase 3 implementation.

Single scrollable column with section cards for Display, Matching,
API Keys, Cache, and Advanced settings.  All state goes through
SettingsService.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...thread_pool import submit as _submit_bg
from ._settings_tab_actions import SettingsTabActionsCoordinator
from ._settings_tab_sections import SettingsTabSectionsBuilder
from ._settings_tab_state import SettingsTabStateCoordinator

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
        self._actions_coordinator = SettingsTabActionsCoordinator(self)
        self._sections_builder = SettingsTabSectionsBuilder(
            self,
            language_options=_LANGUAGE_OPTIONS,
            tag_to_display=_TAG_TO_DISPLAY,
        )
        self._state_coordinator = SettingsTabStateCoordinator(
            self,
            language_options=_LANGUAGE_OPTIONS,
            tag_to_display=_TAG_TO_DISPLAY,
        )
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
        self._sections_builder.build_display_section()

    # ── Matching ─────────────────────────────────────────────────

    def _build_matching_section(self) -> None:
        self._sections_builder.build_matching_section()

    # ── API Keys ─────────────────────────────────────────────────

    def _build_api_keys_section(self) -> None:
        self._sections_builder.build_api_keys_section()

    # ── Cache ────────────────────────────────────────────────────

    def _build_cache_section(self) -> None:
        self._sections_builder.build_cache_section()

    # ── Data Management ──────────────────────────────────────────

    def _build_data_management_section(self) -> None:
        self._sections_builder.build_data_management_section()

    def _on_clear_history(self) -> None:
        self._actions_coordinator.clear_history(message_box_api=QMessageBox)

    # ── Advanced ─────────────────────────────────────────────────

    def _build_advanced_section(self) -> None:
        self._sections_builder.build_advanced_section()

    # ── Callbacks ────────────────────────────────────────────────

    def sync_view_mode(self, mode: str) -> None:
        self._state_coordinator.sync_view_mode(mode)

    def sync_companion_visibility(self, checked: bool) -> None:
        self._state_coordinator.sync_companion_visibility(checked)

    def sync_discovery_visibility(self, checked: bool) -> None:
        self._state_coordinator.sync_discovery_visibility(checked)

    def sync_language(self, tag: str) -> None:
        self._state_coordinator.sync_language(tag)

    def _on_view_mode(self, index: int) -> None:
        self._state_coordinator.on_view_mode(index)

    def _on_companion(self, checked: bool) -> None:
        self._state_coordinator.on_companion(checked)

    def _on_discovery(self, checked: bool) -> None:
        self._state_coordinator.on_discovery(checked)

    def _on_language(self, display: str) -> None:
        self._state_coordinator.on_language(display)

    def _on_threshold(self, value: int) -> None:
        self._state_coordinator.on_threshold(value)

    def _on_confidence_bars(self, checked: bool) -> None:
        self._state_coordinator.on_confidence_bars(checked)

    def _on_save_key(self) -> None:
        self._actions_coordinator.save_key()

    def _on_test_key(self) -> None:
        self._actions_coordinator.test_key(submit_bg=_submit_bg)

    def _show_test_result(self, success: bool, detail: str) -> None:
        self._actions_coordinator.show_test_result(success, detail)

    def _on_clear_cache(self) -> None:
        self._actions_coordinator.clear_cache()

    def _refresh_cache_stats(self) -> None:
        self._actions_coordinator.refresh_cache_stats()

    def _set_key_status(self, text: str, tone: str) -> None:
        self._actions_coordinator.set_key_status(text, tone)
