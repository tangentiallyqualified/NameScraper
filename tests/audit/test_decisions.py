from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from scripts.audit import _decisions


def _finding(**overrides: object) -> dict[str, object]:
    finding: dict[str, object] = {
        "analyzer": "vulture",
        "rule": "unused-method",
        "path": "plex_renamer/gui.py",
        "symbol": "plex_renamer.gui.Window.paintEvent#1",
        "line": 12,
        "column": 5,
        "message": "unused method 'paintEvent'",
    }
    finding.update(overrides)
    return finding


def _policy(**overrides: str) -> str:
    values = {
        "analyzer": "vulture",
        "rule": "unused-method",
        "path": "plex_renamer/gui.py",
        "symbol": "plex_renamer.gui.Window.paintEvent#1",
        "reason_code": "framework-callback",
        "reason": "Qt invokes this QWidget override.",
    }
    values.update(overrides)
    return "[[decision]]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in values.items()
    )


def test_decision_matches_only_the_exact_normalized_qualified_identity() -> None:
    decisions = _decisions.loads(_policy(path=r"plex_renamer\gui.py"))
    findings = [
        _finding(),
        _finding(rule="unused-function", symbol="plex_renamer.gui.Window.paintEvent#2"),
    ]

    annotated = _decisions.apply(findings, decisions)

    assert annotated[0]["decision"] == {
        "reason_code": "framework-callback",
        "reason": "Qt invokes this QWidget override.",
        "expiry": None,
    }
    assert annotated[0]["allowlisted"] is True
    assert annotated[1]["decision"] is None
    assert annotated[1]["allowlisted"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("analyzer", "ruff"),
        ("rule", "unused-variable"),
        ("path", "plex_renamer/other.py"),
        ("symbol", "plex_renamer.gui.Other.paintEvent#1"),
    ],
)
def test_decision_does_not_match_a_partial_identity(field: str, value: str) -> None:
    decision = _decisions.loads(_policy())

    with pytest.raises(_decisions.DecisionPolicyError, match="stale decision"):
        _decisions.apply([_finding(**{field: value})], decision)


@pytest.mark.parametrize(
    "reason_code",
    [
        "framework-callback",
        "serialized-field",
        "public-api",
        "test-seam",
        "intentional-reservation",
        "intentional-literal",
        "accepted-debt",
    ],
)
def test_all_documented_reason_codes_are_accepted(reason_code: str) -> None:
    assert _decisions.loads(_policy(reason_code=reason_code))[0].reason_code == reason_code


def test_unknown_reason_code_is_rejected() -> None:
    with pytest.raises(_decisions.DecisionPolicyError, match="unknown reason_code"):
        _decisions.loads(_policy(reason_code="misc"))


def test_blank_prose_reason_is_rejected() -> None:
    with pytest.raises(_decisions.DecisionPolicyError, match="reason must be a non-empty string"):
        _decisions.loads(_policy(reason="   "))


def test_duplicate_decision_identity_is_rejected() -> None:
    duplicate = _policy() + "\n" + _policy(reason="Duplicate prose.")

    with pytest.raises(_decisions.DecisionPolicyError, match="duplicate decision"):
        _decisions.loads(duplicate)


def test_stale_decision_is_rejected() -> None:
    decisions = _decisions.loads(_policy())

    with pytest.raises(_decisions.DecisionPolicyError, match="stale decision"):
        _decisions.apply([], decisions)


def test_expired_decision_is_rejected() -> None:
    text = _policy() + "expiry = 2026-07-13\n"

    with pytest.raises(_decisions.DecisionPolicyError, match="expired decision"):
        _decisions.loads(text, today=date(2026, 7, 14))


def test_expiry_today_is_still_valid() -> None:
    text = _policy() + "expiry = 2026-07-14\n"

    decision = _decisions.loads(text, today=date(2026, 7, 14))[0]

    assert decision.expiry == date(2026, 7, 14)


def test_future_aware_datetime_expiry_is_normalized_and_serialized_in_utc() -> None:
    text = _policy() + "expiry = 2026-07-14T08:00:00-07:00\n"

    decision = _decisions.loads(text, now=datetime(2026, 7, 14, 14, tzinfo=UTC))[0]
    annotated = _decisions.apply([_finding()], [decision])

    assert decision.expiry == datetime(2026, 7, 14, 15, tzinfo=UTC)
    assert annotated[0]["decision"] == {
        "reason_code": "framework-callback",
        "reason": "Qt invokes this QWidget override.",
        "expiry": "2026-07-14T15:00:00Z",
    }


def test_expired_aware_datetime_is_rejected() -> None:
    text = _policy() + "expiry = 2026-07-14T13:59:59Z\n"

    with pytest.raises(_decisions.DecisionPolicyError, match="expired decision"):
        _decisions.loads(text, now=datetime(2026, 7, 14, 14, tzinfo=UTC))


def test_datetime_offsets_for_the_same_instant_normalize_equally() -> None:
    utc_text = _policy() + "expiry = 2026-07-14T15:00:00Z\n"
    offset_text = _policy() + "expiry = 2026-07-14T08:00:00-07:00\n"
    now = datetime(2026, 7, 14, 14, tzinfo=UTC)

    utc_expiry = _decisions.loads(utc_text, now=now)[0].expiry
    offset_expiry = _decisions.loads(offset_text, now=now)[0].expiry

    assert utc_expiry == offset_expiry == datetime(2026, 7, 14, 15, tzinfo=UTC)


def test_naive_datetime_expiry_is_rejected_as_ambiguous() -> None:
    text = _policy() + "expiry = 2026-07-14T15:00:00\n"

    with pytest.raises(_decisions.DecisionPolicyError, match="timezone-aware"):
        _decisions.loads(text, now=datetime(2026, 7, 14, 14, tzinfo=UTC))
