# Audit Change Log

<!-- audit:input-digest: 3951be682fb4a0ff1f345ffe919737da07b92d364b43b6d38c0c6963e47b8cdf -->
<!-- audit:baseline-input-digest: 3e52a6d469019148137916b97dfa7457524aed18b43f442075ca59becfb89fe4 -->

## Audit 3951be682fb4 vs baseline (3e52a6d46901)

- Headline: 176 modules, 38404 LOC, 0 high-confidence dead symbols, 2 cycles
- Notable movements:
  - coverage methodology changed or is unknown; per-module coverage movements suppressed
  - `plex_renamer/app/models/state_models.py`: new dead symbol `REFRESHING_CACHE` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_episode_expansion.py`: new dead symbol `paintEvent` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/_workspace_widget_primitives.py`: new dead symbol `paintEvent` (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: new dead symbol `paintEvent` at line 52 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/busy_overlay.py`: new dead symbol `paintEvent` at line 89 (dynamic-or-unresolved, 60%)
  - `plex_renamer/gui_qt/widgets/scan_progress.py`: new dead symbol `paintEvent` (dynamic-or-unresolved, 60%)
- Documentation status changes:
  - `README.md`: current -> stale
