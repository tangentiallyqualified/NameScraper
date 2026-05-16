"""State synchronization helpers for the settings tab."""

from __future__ import annotations

from typing import Any


class SettingsTabStateCoordinator:
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

    def sync_view_mode(self, mode: str) -> None:
        tab = self._tab
        tab._view_mode_combo.blockSignals(True)
        tab._view_mode_combo.setCurrentIndex(1 if mode == "compact" else 0)
        tab._view_mode_combo.blockSignals(False)

    def sync_companion_visibility(self, checked: bool) -> None:
        tab = self._tab
        tab._companion_cb.blockSignals(True)
        tab._companion_cb.setChecked(checked)
        tab._companion_cb.blockSignals(False)

    def sync_discovery_visibility(self, checked: bool) -> None:
        tab = self._tab
        tab._discovery_cb.blockSignals(True)
        tab._discovery_cb.setChecked(checked)
        tab._discovery_cb.blockSignals(False)

    def sync_language(self, tag: str) -> None:
        tab = self._tab
        display = self._tag_to_display.get(tag, "English (US)")
        index = tab._lang_combo.findText(display)
        if index < 0:
            index = 0
        tab._lang_combo.blockSignals(True)
        tab._lang_combo.setCurrentIndex(index)
        tab._lang_combo.blockSignals(False)

    def on_view_mode(self, index: int) -> None:
        tab = self._tab
        mode = "compact" if index == 1 else "normal"
        if tab._settings:
            tab._settings.view_mode = mode
        tab.view_mode_changed.emit(mode)

    def on_companion(self, checked: bool) -> None:
        tab = self._tab
        if tab._settings:
            tab._settings.show_companion_files = checked
        tab.companion_visibility_changed.emit(checked)

    def on_discovery(self, checked: bool) -> None:
        tab = self._tab
        if tab._settings:
            tab._settings.show_discovery_info = checked
        tab.discovery_visibility_changed.emit(checked)

    def on_language(self, display: str) -> None:
        tab = self._tab
        tag = self._language_options.get(display, "en-US")
        if tab._settings:
            tab._settings.match_language = tag
        tab.language_changed.emit(tag)

    def on_threshold(self, value: int) -> None:
        tab = self._tab
        float_value = value / 100
        tab._threshold_label.setText(f"{float_value:.2f}")
        if tab._settings:
            tab._settings.auto_accept_threshold = float_value
        tab.threshold_changed.emit(float_value)

    def on_episode_threshold(self, value: int) -> None:
        tab = self._tab
        float_value = value / 100
        tab._episode_threshold_label.setText(f"{float_value:.2f}")
        if tab._settings:
            tab._settings.episode_auto_accept_threshold = float_value
        tab.episode_threshold_changed.emit(float_value)

    def on_confidence_bars(self, checked: bool) -> None:
        tab = self._tab
        if tab._settings:
            tab._settings.show_confidence_bars = checked
