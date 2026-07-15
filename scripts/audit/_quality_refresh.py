"""Small policy helpers for safe quality-baseline refreshes."""

from __future__ import annotations


class QualityBaselineRefused(RuntimeError):
    """Raised when refresh would enroll new or enlarged debt."""


def coverage_ratchet_fields(kind: str) -> tuple[str, str, str]:
    """Translate a coverage violation into ratchet kind, message, and rule."""
    if kind == "coverage-scope-incomplete":
        return "new-debt", "coverage scope is incomplete", "scope-incomplete"
    if kind == "changed-line-coverage":
        return "new-debt", "changed executable line coverage is below policy", "changed-lines"
    return "enlarged-debt", "package statement coverage decreased", "package-floor"


def reject_new_debt(violations: list[dict[str, object]]) -> None:
    """Refuse a refresh containing anything except stale-baseline cleanup."""
    debt = [finding for finding in violations if finding["kind"] != "stale-baseline"]
    if not debt:
        return
    details = ", ".join(
        f"{finding['path']}:{finding['analyzer']}/{finding['rule']}" for finding in debt[:5]
    )
    suffix = "" if len(debt) <= 5 else f", plus {len(debt) - 5} more"
    raise QualityBaselineRefused(f"{len(debt)} new/enlarged debt entries ({details}{suffix})")
