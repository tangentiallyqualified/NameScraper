"""Validation helpers for user-configured output destinations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Windows MAX_PATH limit that non-long-path-aware code (and some legacy APIs)
# still enforce.
_WINDOWS_MAX_PATH = 260

# Reserve for the generated rename tail appended under the output root, e.g.
# "\Show Name (Year)\Season NN\Show Name - SNNEnn - Episode Title.ext".
# Conservative so the warning fires before real overflow rather than after.
_RENAME_TAIL_RESERVE = 160


def output_path_risks_long_paths(root: str | Path, *, reserve: int = _RENAME_TAIL_RESERVE) -> bool:
    """True when *root* is long enough that a generated rename path could
    exceed the Windows MAX_PATH limit. Pure/non-blocking: callers still
    accept the path, this only flags a warning."""
    root_len = len(str(root or ""))
    return root_len > 0 and (root_len + reserve) > _WINDOWS_MAX_PATH


def long_path_warning_text(root: str | Path) -> str:
    """User-facing, non-blocking warning for *root*, or "" if not at risk."""
    if not output_path_risks_long_paths(root):
        return ""
    return (
        "This output folder is long enough that some renamed files may exceed "
        "the Windows 260-character path limit. Consider a shorter destination "
        "or enable long-path support in Windows."
    )


@dataclass(frozen=True, slots=True)
class OutputDestinationStatus:
    valid: bool
    path: Path | None = None
    reason: str = ""


def validate_output_folder(path_value: str | Path | None) -> OutputDestinationStatus:
    """Validate that *path_value* names an existing directory."""
    text = str(path_value or "").strip()
    if not text:
        return OutputDestinationStatus(False, reason="Choose an output folder first.")

    path = Path(text).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return OutputDestinationStatus(False, reason=f"Output folder does not exist: {path}")

    if not resolved.is_dir():
        return OutputDestinationStatus(False, reason=f"Output path is not a folder: {resolved}")

    return OutputDestinationStatus(True, path=resolved)


def validate_scan_output_relationship(
    source_folder: str | Path,
    output_folder: str | Path,
) -> OutputDestinationStatus:
    """Validate that output is not the selected scan source or nested under it."""
    source_status = validate_output_folder(source_folder)
    if not source_status.valid:
        return OutputDestinationStatus(False, reason=f"Scan source is invalid: {source_status.reason}")

    output_status = validate_output_folder(output_folder)
    if not output_status.valid:
        return output_status

    assert source_status.path is not None
    assert output_status.path is not None
    source = source_status.path
    output = output_status.path

    if _same_path(source, output):
        return OutputDestinationStatus(
            False,
            path=output,
            reason="Output folder cannot be the same as the scanned folder.",
        )

    if _is_relative_to(output, source):
        return OutputDestinationStatus(
            False,
            path=output,
            reason="Output folder cannot be inside the scanned folder.",
        )

    return OutputDestinationStatus(True, path=output)


def _same_path(left: Path, right: Path) -> bool:
    return left == right or str(left).casefold() == str(right).casefold()


def _is_relative_to(child: Path, parent: Path) -> bool:
    if _same_path(child, parent):
        return True
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
