"""State synchronization helpers for the settings tab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog

from ...app.services.output_destination_service import long_path_warning_text
from ._media_helpers import repolish as _repolish


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

    def on_cache_size(self, index: int) -> None:
        tab = self._tab
        value = tab._cache_size_combo.itemData(index)
        if value is None or tab._settings is None:
            return
        tab._settings.cache_max_size_bytes = int(value)
        if tab._cache_service is not None:
            tab._cache_service.set_max_size_bytes(tab._settings.cache_max_size_bytes)
        tab._actions_coordinator.refresh_cache_stats()

    def browse_output_folder(self, media_type: str) -> None:
        tab = self._tab
        if media_type == "tv":
            target = tab._tv_output_input
            title = "Choose TV output folder"
        else:
            target = tab._movie_output_input
            title = "Choose movie output folder"

        selected = QFileDialog.getExistingDirectory(tab, title, target.text().strip())
        if not selected:
            return
        target.setText(selected)

        warning = long_path_warning_text(selected)
        if warning:
            self._set_destination_status(warning, "warning")
        else:
            self._clear_destination_status()

    def on_save_destinations(self) -> None:
        tab = self._tab
        if not tab._settings:
            self._set_destination_status("Settings service is not available.", "error")
            return

        tv_text = tab._tv_output_input.text().strip()
        movie_text = tab._movie_output_input.text().strip()
        tv_path = ""
        movie_path = ""

        if tv_text:
            tv_status = tab._settings.validate_output_folder(tv_text)
            if not tv_status.valid:
                self._set_destination_status(tv_status.reason, "error")
                return
            tv_path = str(tv_status.path or Path(tv_text))

        if movie_text:
            movie_status = tab._settings.validate_output_folder(movie_text)
            if not movie_status.valid:
                self._set_destination_status(movie_status.reason, "error")
                return
            movie_path = str(movie_status.path or Path(movie_text))

        tab._settings.tv_output_folder = tv_path
        tab._settings.movie_output_folder = movie_path
        tab._tv_output_input.setText(tv_path)
        tab._movie_output_input.setText(movie_path)

        warning = long_path_warning_text(tv_path) or long_path_warning_text(movie_path)
        if warning:
            self._set_destination_status(warning, "warning")
        else:
            self._set_destination_status("Output destinations saved.", "success")

    def _set_destination_status(self, text: str, tone: str) -> None:
        status = self._tab._destinations_status
        status.setText(text)
        status.setProperty("tone", tone)
        _repolish(status)

    def _clear_destination_status(self) -> None:
        status = self._tab._destinations_status
        status.setText("")
        status.setProperty("tone", "")
        _repolish(status)
