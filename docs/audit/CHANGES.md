# Audit Change Log

<!-- audit:input-digest: cc8c385e6d35830aab881f4253c4afbfd314d2e0922abaa17409042a5c4e9fc7 -->
<!-- audit:baseline-input-digest: f609ca7fd5b8fe4cee0974994c3831553cc1b94c42376eef65e3a953b3e329ed -->

## Audit cc8c385e6d35 vs baseline (f609ca7fd5b8)

- Headline: 185 modules, 41881 LOC, 0 high-confidence dead symbols, 0 cycles
- Added: `plex_renamer/_ffprobe.py`, `plex_renamer/_parsing_id_tags.py`, `plex_renamer/engine/_audio_codecs.py`, `plex_renamer/engine/_mux_audio_dedup.py`, `plex_renamer/engine/_mux_models.py`
- Notable movements:
  - `plex_renamer/_mkv_probe.py`: loc 131 -> 260
  - `plex_renamer/_mkv_probe.py`: max_complexity 7 -> 14
  - `plex_renamer/gui_qt/_main_window_tmdb.py`: loc 121 -> 217
  - `plex_renamer/gui_qt/widgets/_automux_tracks.py`: new dead symbol `_conversion_label` at line 78 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_automux_tracks.py`: new dead symbol `_conversion_label` at line 136 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_automux_tracks.py`: new dead symbol `_conversion_label` at line 143 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_automux_tracks.py`: new dead symbol `_conversion_label` at line 274 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_media_workspace_queue_actions.py`: loc 211 -> 321
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: loc 210 -> 332
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: new dead symbol `_convert_containers_cb` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: new dead symbol `_dedupe_cb` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: new dead symbol `_keep_per_layout_cb` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: new dead symbol `_tie_cb` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: new dead symbol `_tolerance_spin` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_settings_automux_page.py`: new dead symbol `_transparency_spin` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_work_panel.py`: new dead symbol `source_button` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: new dead symbol `paintEvent` at line 53 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: new dead symbol `paintEvent` at line 90 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: resolved dead symbol `paintEvent` at line 52 (was dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: resolved dead symbol `paintEvent` at line 89 (was dynamic-or-unresolved, 60%)
