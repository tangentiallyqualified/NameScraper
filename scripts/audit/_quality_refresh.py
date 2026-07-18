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


def gate_refresh_debt(violations: list[dict[str, object]], accept_enlarged: bool) -> None:
    """Refuse non-stale debt unless the caller explicitly opted to accept it.

    With acceptance, print one ASCII summary line per accepted entry plus a
    total, so the terminal transcript records exactly what was enrolled.
    """
    if not accept_enlarged:
        reject_new_debt(violations)
        return
    debt = [finding for finding in violations if finding["kind"] != "stale-baseline"]
    for finding in debt:
        print(
            f"quality baseline: accepted {finding['kind']}: {finding['path']}: "
            f"{finding['analyzer']}/{finding['rule']} "
            f"({finding['baseline']} -> {finding['current']})"
        )
    if debt:
        label = "entry" if len(debt) == 1 else "entries"
        print(f"quality baseline: accepted {len(debt)} new/enlarged debt {label}")
