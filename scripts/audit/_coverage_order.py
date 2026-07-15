"""Ordered executable-statement comparison for changed coverage."""

from __future__ import annotations

from typing import TypedDict


class ExecutableLine(TypedDict):
    fingerprint: str
    covered: bool


def changed_lines(
    baseline_order: list[str], current_lines: list[ExecutableLine]
) -> list[ExecutableLine]:
    """Return inserted statements and both endpoints of statement-order inversions."""
    current_order = [line["fingerprint"] for line in current_lines]
    reordered = _reordered_fingerprints(baseline_order, current_order)
    known = set(baseline_order)
    return [
        line
        for line in current_lines
        if line["fingerprint"] not in known or line["fingerprint"] in reordered
    ]


def _reordered_fingerprints(baseline_order: list[str], current_order: list[str]) -> set[str]:
    baseline_positions = {fingerprint: index for index, fingerprint in enumerate(baseline_order)}
    common = [fingerprint for fingerprint in current_order if fingerprint in baseline_positions]
    positions = [baseline_positions[fingerprint] for fingerprint in common]
    prefix_max = _prior_maxima(positions)
    suffix_min = _following_minima(positions, len(baseline_order))
    return {
        fingerprint
        for index, fingerprint in enumerate(common)
        if prefix_max[index] > positions[index] or suffix_min[index] < positions[index]
    }


def _prior_maxima(positions: list[int]) -> list[int]:
    prefix_max: list[int] = []
    maximum = -1
    for position in positions:
        prefix_max.append(maximum)
        maximum = max(maximum, position)
    return prefix_max


def _following_minima(positions: list[int], missing: int) -> list[int]:
    suffix_min = [missing] * len(positions)
    minimum = missing
    for index in range(len(positions) - 1, -1, -1):
        suffix_min[index] = minimum
        minimum = min(minimum, positions[index])
    return suffix_min
