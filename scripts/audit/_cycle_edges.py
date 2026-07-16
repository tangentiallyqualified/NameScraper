"""Validation and rendering for classified engine cycle edges."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import TypeAlias, TypedDict

CYCLE_EDGE_CLASSIFICATIONS = Path("docs/audit/engine-cycle-edges.toml")
CYCLE_EDGE_FIELDS = {"source", "target", "owner", "purpose", "disposition"}
CYCLE_EDGE_DISPOSITIONS = {
    "algorithm-call",
    "facade-backedge",
    "runtime-construction",
    "shared-model",
}


class CycleEdgeClassification(TypedDict):
    source: str
    target: str
    owner: str
    purpose: str
    disposition: str


class CycleGraphEntry(TypedDict):
    modules: list[str]
    edges: list[list[str]]


class CycleGraph(TypedDict):
    cycles: list[CycleGraphEntry]


TomlScalar: TypeAlias = str | int | float | bool | datetime | date | time
TomlValue: TypeAlias = TomlScalar | list["TomlValue"] | dict[str, "TomlValue"]
TomlTable: TypeAlias = dict[str, TomlValue]


def _edge_text(edge: tuple[str, str]) -> str:
    return f"{edge[0]} -> {edge[1]}"


def _engine_cycle_edges(graph: CycleGraph) -> list[tuple[str, str]]:
    prefix = "plex_renamer.engine."
    return sorted(
        (source, target)
        for cycle in graph["cycles"]
        for source, target in cycle["edges"]
        if source.startswith(prefix) and target.startswith(prefix)
    )


def _required_string(record: TomlTable, index: int, field: str) -> str:
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"cycle edge classification {index} {field} must be a non-empty string")
    return value


def _validated_record(record: TomlValue, index: int) -> CycleEdgeClassification:
    if not isinstance(record, dict):
        raise ValueError(f"cycle edge classification {index} must be a table")
    fields = set(record)
    missing_fields = sorted(CYCLE_EDGE_FIELDS - fields)
    unexpected_fields = sorted(fields - CYCLE_EDGE_FIELDS)
    if missing_fields:
        raise ValueError(
            f"cycle edge classification {index} missing fields: {', '.join(missing_fields)}"
        )
    if unexpected_fields:
        raise ValueError(
            "cycle edge classification "
            f"{index} has unexpected fields: {', '.join(unexpected_fields)}"
        )
    source = _required_string(record, index, "source")
    target = _required_string(record, index, "target")
    owner = _required_string(record, index, "owner")
    purpose = _required_string(record, index, "purpose")
    disposition = _required_string(record, index, "disposition")
    if disposition not in CYCLE_EDGE_DISPOSITIONS:
        allowed = ", ".join(sorted(CYCLE_EDGE_DISPOSITIONS))
        raise ValueError(
            f"cycle edge classification {index} has unsupported disposition "
            f"{disposition!r}; expected one of: {allowed}"
        )
    return CycleEdgeClassification(
        source=source,
        target=target,
        owner=owner,
        purpose=purpose,
        disposition=disposition,
    )


def _validate_edge_coverage(records: list[CycleEdgeClassification], graph: CycleGraph) -> None:
    expected = set(_engine_cycle_edges(graph))
    actual = {(record["source"], record["target"]) for record in records}
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if not missing and not unexpected:
        return
    details: list[str] = []
    if missing:
        details.append("missing: " + ", ".join(_edge_text(edge) for edge in missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(_edge_text(edge) for edge in unexpected))
    raise ValueError("cycle edge classification coverage mismatch; " + "; ".join(details))


def load_cycle_edge_classifications(
    repo_root: Path, graph: CycleGraph
) -> list[CycleEdgeClassification]:
    """Load and validate exact classifications for live engine SCC edges."""
    path = repo_root / CYCLE_EDGE_CLASSIFICATIONS
    if not path.exists():
        raise ValueError(f"cycle edge classification file is missing: {path}")
    data: TomlTable = tomllib.loads(path.read_text(encoding="utf-8"))
    if type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("cycle edge classification version must be 1")
    raw_records_value = data.get("edges")
    if not isinstance(raw_records_value, list):
        raise ValueError("cycle edge classifications must contain an edges array")
    records: list[CycleEdgeClassification] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_record in enumerate(raw_records_value, 1):
        record = _validated_record(raw_record, index)
        edge = (record["source"], record["target"])
        if edge in seen:
            raise ValueError(f"duplicate classification for {_edge_text(edge)}")
        seen.add(edge)
        records.append(record)

    _validate_edge_coverage(records, graph)
    return sorted(records, key=lambda record: (record["source"], record["target"]))


def _cycle_node_id(module: str) -> str:
    node_id = re.sub(r"\W", "_", module.rsplit(".", 1)[-1])
    return f"module_{node_id}" if node_id[:1].isdigit() else node_id


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_classified_cycle_map(classifications: Sequence[CycleEdgeClassification]) -> str:
    """Render deterministic Mermaid and detail rows from TOML classifications."""
    lines = ["```mermaid", "graph LR"]
    for record in classifications:
        source = _cycle_node_id(record["source"])
        target = _cycle_node_id(record["target"])
        lines.append(f"    {source} -->|{record['disposition']}| {target}")
    lines.append("```")
    rows = [
        "| "
        + " | ".join(
            (
                f"`{record['source']}`",
                f"`{record['target']}`",
                _markdown_cell(record["owner"]),
                _markdown_cell(record["purpose"]),
                record["disposition"],
            )
        )
        + " |"
        for record in classifications
    ]
    return (
        "### Classified cycle edges\n\n"
        + "\n".join(lines)
        + "\n\n| Source | Target | Owner | Import purpose | Disposition |\n"
        "|---|---|---|---|---|\n" + "\n".join(rows)
    )
