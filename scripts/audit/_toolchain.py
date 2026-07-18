"""Validate deterministic analyzer versions against checked-in constraints."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

CONSTRAINTS_REL = Path("scripts") / "audit" / "constraints.txt"
REQUIRED_ANALYZERS = ("coverage", "radon", "ruff", "vulture")


def _exact_constraints(path: Path) -> tuple[dict[str, str], list[str]]:
    pins: dict[str, str] = {}
    errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.count("==") != 1:
            errors.append(f"constraint line {line_number} is not an exact pin: {line}")
            continue
        name, version = (part.strip() for part in line.split("==", 1))
        normalized = name.lower().replace("_", "-")
        if not normalized or not version:
            errors.append(f"constraint line {line_number} is not an exact pin: {line}")
            continue
        pins[normalized] = version
    return pins, errors


def validate(repo_root: Path) -> list[str]:
    """Return stable incompatibility messages for the enrolled analyzer toolchain."""
    path = repo_root / CONSTRAINTS_REL
    if not path.exists():
        return [f"missing audit constraints: {CONSTRAINTS_REL.as_posix()}"]
    pins, errors = _exact_constraints(path)
    for name in REQUIRED_ANALYZERS:
        required = pins.get(name)
        if required is None:
            errors.append(f"missing exact analyzer constraint: {name}")
            continue
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            errors.append(f"analyzer not installed: {name}=={required}")
            continue
        if installed != required:
            errors.append(f"{name} version mismatch: installed {installed}, required {required}")
    return sorted(errors)
