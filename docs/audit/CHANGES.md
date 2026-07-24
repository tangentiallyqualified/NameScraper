# Audit Change Log

<!-- audit:input-digest: 4a7796affcc80143e1b345039cebac1a1e654f7e21a1adbb96d754a8882c778d -->
<!-- audit:baseline-input-digest: dae3d14c745fe5570c13af14e57c8f3ca9126831b8a32ebc934708f8bb1800a4 -->

## Audit 4a7796affcc8 vs baseline (dae3d14c745f)

- Headline: 197 modules, 43763 LOC, 0 high-confidence dead symbols, 0 cycles
- Added: `plex_renamer/engine/_batch_types.py`, `plex_renamer/metadata_types.py`
- Notable movements:
  - coverage methodology changed or is unknown; per-module coverage movements suppressed
  - `plex_renamer/engine/show_details.py`: loc 59 -> 110
  - `plex_renamer/engine/show_details.py`: resolved dead symbol `first_air_date` (was dynamic-or-unresolved, 60%)
