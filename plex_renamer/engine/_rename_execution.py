"""Preview duplicate-detection helper used by the batch scan flows.

Operates on preview items without depending on the scanning/orchestration
classes in ``_core``.  The live rename-execution path is
``plex_renamer.job_executor._execute_rename``, which works from queued
``RenameJob`` records rather than in-memory preview items.
"""

from __future__ import annotations

from .models import PreviewItem


def check_duplicates(items: list[PreviewItem]) -> None:
    """Flag items that would collide on the same target path."""
    seen: dict[tuple[str, str], str] = {}
    for item in items:
        if item.new_name is None:
            continue
        target_dir = item.target_dir or item.original.parent
        key = (str(target_dir).lower(), item.new_name.lower())
        if key in seen:
            item.status = f"CONFLICT: same target as {seen[key]}"
        else:
            seen[key] = item.original.name
