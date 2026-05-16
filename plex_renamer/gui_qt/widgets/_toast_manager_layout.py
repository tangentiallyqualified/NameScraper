"""Layout and overflow helpers for toast notifications."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToastManagerGeometry:
    x: int
    y: int
    width: int
    height: int


def count_direct_toasts(toasts: list[Any], *, summary_toast: Any | None) -> int:
    return sum(1 for toast in toasts if toast is not summary_toast)


def summary_toast_copy(overflow_count: int) -> tuple[str, str]:
    title = "More notifications"
    noun = "notification" if overflow_count == 1 else "notifications"
    return title, f"{overflow_count} more {noun} collapsed."


def plan_toast_manager_geometry(
    parent_width: int,
    parent_height: int,
    *,
    toast_heights: list[int],
    spacing: int,
    margin: int = 16,
    min_width: int = 280,
    max_width: int = 380,
) -> ToastManagerGeometry:
    width = min(max_width, max(min_width, parent_width // 3))
    height = sum(toast_heights)
    if len(toast_heights) > 1:
        height += spacing * (len(toast_heights) - 1)
    return ToastManagerGeometry(
        x=parent_width - width - margin,
        y=parent_height - height - margin,
        width=width,
        height=height,
    )
