# Documentation Index

This folder contains tracked project documentation for Plex Renamer.

If you are looking for the current high-level project overview, start with the root [README.md](../README.md).

If you are looking for implementation status and Qt migration detail, use the documents below.

---

## Current Reference Docs

### [ai-assistant-workflows.md](ai-assistant-workflows.md)

User-facing guide for AI shorthand prompts, helper-script workflows, and future script documentation.

Use this file for:

- short prompt conventions for Copilot or Claude
- AI-assisted commit/push workflow usage
- Windows-specific helper-script guidance
- future prompt/script workflow documentation

### [ai-publish-workflow.md](ai-publish-workflow.md)

Technical reference for the publish helper scripts and AI-driven commit/push flow.

Use this file for:

- exact publish behavior
- shorthand token definitions
- agent-facing workflow expectations
- wrapper vs PowerShell implementation details

### [gui3-pyside6-migration-plan revised.md](gui3-pyside6-migration-plan%20revised.md)

The canonical tracked migration plan for the PySide6 shell.

Use this file for:

- current migration status
- completed phases and follow-up notes
- remaining recommended work
- architecture and rollout guidance

This is the primary source of truth for `dev/GUI3` migration progress.

Updated 2026-04-01 with a nightly progress note covering completion of the April 1 trust, selection, queue/history, and media-clarity implementation pass.

### [gui3-pyside6-ui-design.md](gui3-pyside6-ui-design.md)

The design and interaction reference for the Qt shell.

Use this file for:

- theme and visual language
- layout rules
- status presentation
- component expectations
- interaction principles

Updated 2026-04-01 with an implementation-status section so the design intent and shipped GUI3 behavior stay aligned.

---

## Audits

### [gui3-phase7-parity-audit.md](gui3-phase7-parity-audit.md)

Parity audit of the Qt shell vs tkinter, with addenda tracking resolution of findings.

Updated 2026-04-01 with an additional addendum covering the queue/history operational pass and the latest media-clarity work. The audit still treats the MatchPickerDialog UI-thread blocking issue as the remaining retirement blocker.

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
- use the AI assistant workflow docs for shorthand prompts and helper-script behavior