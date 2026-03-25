# Docs Conventions

This folder can hold both tracked project documentation and local audit or planning notes.

## Tracked docs

Place tracked documentation directly under `docs/` when it should be committed and reviewed with the project.

Examples:

- migration summaries that are approved for the repo
- architecture notes intended for long-term reference
- contributor-facing documentation

## Local docs

Place private or temporary working documents under `docs/local/`.

That folder is gitignored so you can keep:

- audit notes
- exploratory plans
- draft migration writeups
- scratch decision documents

without adding one-off ignore rules each time.

## Current note

The existing `docs/gui3-pyside6-migration-plan.md` file is individually ignored to avoid changing or moving it during the current audit phase. Future temporary documents should go in `docs/local/` instead.