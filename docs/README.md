# Documentation Index

This folder contains tracked project documentation for Plex Renamer.

If you are looking for the current high-level project overview, start with the root [README.md](../README.md).

If you are looking for implementation status and Qt migration detail, use the documents below.

---

## Current Reference Docs

### [gui3-pyside6-migration-plan revised.md](gui3-pyside6-migration-plan%20revised.md)

The canonical tracked migration plan for the PySide6 shell.

Use this file for:

- current migration status
- completed phases and follow-up notes
- remaining recommended work
- architecture and rollout guidance

This is the primary source of truth for `dev/GUI3` migration progress.

### [gui3-pyside6-ui-design.md](gui3-pyside6-ui-design.md)

The design and interaction reference for the Qt shell.

Use this file for:

- theme and visual language
- layout rules
- status presentation
- component expectations
- interaction principles

---

## Audits

### [gui3-phase7-parity-audit.md](gui3-phase7-parity-audit.md)

Parity audit of the Qt shell vs tkinter, with addenda tracking resolution of findings.

Updated 2026-03-30 with a full code review addendum. The audit now concludes that the Qt shell has reached functional parity with tkinter, with one remaining must-fix bug (MatchPickerDialog UI-thread blocking). See the March 30 addendum for the updated assessment and tkinter retirement recommendation.

### [scan-improvement-plan.md](scan-improvement-plan.md)

Targeted planning document for scan/discovery behavior.

Use this when working specifically on scan quality, filesystem discovery heuristics, or related follow-up items.

---

## Test Data

### [test_library](test_library)

Representative media folders used for scanning and matching validation.

This is reference/test input data, not end-user documentation.

---

## Documentation Guidance

- Put durable, reviewed project documentation directly under `docs/`
- Keep one canonical version of long-lived plans instead of creating parallel top-level variants
- Treat audit documents as snapshots unless they are explicitly maintained as living docs

For GUI3 work specifically:

- use the migration plan for current implementation status
- use the UI design doc for visual and interaction intent
- use the parity audit only as historical context