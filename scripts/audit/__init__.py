"""Audit harness: staged codebase mapping/audit pipeline.

See docs/ai-audit-cadence.md and scripts/audit/policy.toml.
Run via scripts/audit.cmd or `python -m audit` with scripts/ on PYTHONPATH.

Exit-code semantics: in full-pipeline runs, a failure in a non-hard stage
degrades the overall run to exit 2 (partial success) rather than aborting;
but when a single stage is explicitly requested on the command line and it
fails with an unexpected error, the run exits 1, because the one artifact
the caller asked for was not produced.
"""
