"""Small shared formatting helpers for Qt widgets."""

from __future__ import annotations


def clamped_percent(score: float) -> int:
    return max(0, min(100, int(round(score * 100))))


def percent_text(score: float) -> str:
    return f"{clamped_percent(score)}%"