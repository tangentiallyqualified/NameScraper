"""Machine-readable decisions for normalized audit findings."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

ALLOWED_REASON_CODES = frozenset(
    {
        "accepted-debt",
        "framework-callback",
        "intentional-reservation",
        "public-api",
        "serialized-field",
        "test-seam",
    }
)

DecisionKey = tuple[str, str, str, str]
Finding = dict[str, object]


class DecisionPolicyError(ValueError):
    """Raised when decision policy is invalid or no longer matches evidence."""


@dataclass(frozen=True, slots=True)
class Decision:
    analyzer: str
    rule: str
    path: str
    symbol: str
    reason_code: str
    reason: str
    expiry: date | None = None

    @property
    def key(self) -> DecisionKey:
        return self.analyzer, self.rule, self.path, self.symbol


def _normalized_path(value: object) -> str:
    return str(value or "").replace("\\", "/")


def finding_key(finding: Mapping[str, object]) -> DecisionKey:
    return (
        str(finding.get("analyzer") or finding.get("source") or "unknown"),
        str(finding.get("rule") or "unknown"),
        _normalized_path(finding.get("path")),
        str(finding.get("symbol") or ""),
    )


def _required_text(record: Mapping[str, object], field: str, index: int) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DecisionPolicyError(f"decision {index} requires non-empty {field}")
    return value.strip()


def _parse_expiry(value: object, index: int) -> date | None:
    if value is None:
        return None
    if type(value) is not date:
        raise DecisionPolicyError(f"decision {index} expiry must be a TOML date")
    return value


def _decision(record: Mapping[str, object], index: int, today: date) -> Decision:
    reason_code = _required_text(record, "reason_code", index)
    if reason_code not in ALLOWED_REASON_CODES:
        raise DecisionPolicyError(f"decision {index} has unknown reason_code: {reason_code}")
    expiry = _parse_expiry(record.get("expiry"), index)
    decision = Decision(
        analyzer=_required_text(record, "analyzer", index),
        rule=_required_text(record, "rule", index),
        path=_normalized_path(_required_text(record, "path", index)),
        symbol=_required_text(record, "symbol", index),
        reason_code=reason_code,
        reason=_required_text(record, "reason", index),
        expiry=expiry,
    )
    if expiry is not None and expiry < today:
        raise DecisionPolicyError(f"expired decision: {_format_key(decision.key)} ({expiry})")
    return decision


def _format_key(key: DecisionKey) -> str:
    analyzer, rule, path, symbol = key
    return f"{analyzer}/{rule} {path} [{symbol}]"


def loads(text: str, *, today: date | None = None) -> list[Decision]:
    try:
        payload = cast(dict[str, object], tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise DecisionPolicyError(f"invalid decisions TOML: {exc}") from exc
    records = payload.get("decision", [])
    if not isinstance(records, list):
        raise DecisionPolicyError("decision policy must contain [[decision]] tables")
    typed_records = cast(list[object], records)
    decisions: list[Decision] = []
    seen: set[DecisionKey] = set()
    for index, raw_record in enumerate(typed_records, 1):
        if not isinstance(raw_record, dict):
            raise DecisionPolicyError(f"decision {index} must be a table")
        decision = _decision(cast(dict[str, object], raw_record), index, today or date.today())
        if decision.key in seen:
            raise DecisionPolicyError(f"duplicate decision: {_format_key(decision.key)}")
        seen.add(decision.key)
        decisions.append(decision)
    return decisions


def load(path: Path, *, today: date | None = None) -> list[Decision]:
    if not path.exists():
        return []
    return loads(path.read_text(encoding="utf-8"), today=today)


def filter_open(repo_root: Path, findings: list[Finding]) -> list[Finding]:
    """Validate repository decisions and return undecided findings without annotations."""
    policy_path = repo_root / "scripts" / "audit" / "decisions.toml"
    annotated = apply(findings, load(policy_path))
    return [
        dict(original)
        for original, result in zip(findings, annotated, strict=True)
        if not result["allowlisted"]
    ]


def apply(findings: list[Finding], decisions: list[Decision]) -> list[Finding]:
    by_key = {decision.key: decision for decision in decisions}
    matched: set[DecisionKey] = set()
    annotated: list[Finding] = []
    for original in findings:
        finding = {**original, "path": _normalized_path(original.get("path"))}
        decision = by_key.get(finding_key(finding))
        if decision is None:
            finding.update(decision=None, allowlisted=False, allowlist_reason=None)
        else:
            matched.add(decision.key)
            decision_data = {
                "reason_code": decision.reason_code,
                "reason": decision.reason,
                "expiry": decision.expiry.isoformat() if decision.expiry else None,
            }
            finding.update(
                decision=decision_data,
                allowlisted=True,
                allowlist_reason=decision.reason,
            )
        annotated.append(finding)
    stale = sorted(set(by_key) - matched)
    if stale:
        details = ", ".join(_format_key(key) for key in stale)
        raise DecisionPolicyError(f"stale decision: {details}")
    return annotated
