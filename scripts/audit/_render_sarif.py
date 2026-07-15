"""Deterministic SARIF 2.1.0 rendering for normalized audit findings."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from . import _artifacts

Finding = Mapping[str, object]

_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/Schemata/sarif-schema-2.1.0.json"
)


def _text(finding: Finding, key: str, fallback: str = "") -> str:
    value = finding.get(key)
    return str(value) if value is not None else fallback


def _rule_id(finding: Finding) -> str:
    analyzer = _text(finding, "analyzer", _text(finding, "source", "unknown"))
    return f"{analyzer}/{_text(finding, 'rule', 'unknown')}"


def _integer(finding: Finding, key: str, default: int) -> int:
    value = finding.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _sort_key(finding: Finding) -> tuple[str, int, int, str, str]:
    return (
        _text(finding, "path").replace("\\", "/"),
        _integer(finding, "line", 0),
        _integer(finding, "column", 0),
        _rule_id(finding),
        _text(finding, "symbol"),
    )


def _location(finding: Finding) -> dict[str, object]:
    region: dict[str, int] = {"startLine": max(_integer(finding, "line", 1), 1)}
    column = _integer(finding, "column", 0)
    if column > 0:
        region["startColumn"] = column
    return {
        "physicalLocation": {
            "artifactLocation": {
                "uri": _text(finding, "path").replace("\\", "/"),
                "uriBaseId": "%SRCROOT%",
            },
            "region": region,
        }
    }


def _decision(finding: Finding) -> Mapping[str, object] | None:
    value = finding.get("decision")
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _result(finding: Finding, rule_indexes: dict[str, int]) -> dict[str, object]:
    rule_id = _rule_id(finding)
    result: dict[str, object] = {
        "level": "warning",
        "locations": [_location(finding)],
        "message": {"text": _text(finding, "message", rule_id)},
        "properties": {
            "analyzer": rule_id.split("/", 1)[0],
            "category": _text(finding, "category", "quality"),
            "qualifiedSymbol": _text(finding, "symbol"),
        },
        "ruleId": rule_id,
        "ruleIndex": rule_indexes[rule_id],
    }
    decision = _decision(finding)
    if decision is not None:
        reason_code = _text(decision, "reason_code")
        reason = _text(decision, "reason")
        result["suppressions"] = [{"kind": "external", "justification": f"{reason_code}: {reason}"}]
    return result


def render(findings: list[dict[str, object]]) -> str:
    ordered = sorted(findings, key=_sort_key)
    rule_ids = sorted({_rule_id(finding) for finding in ordered})
    rule_indexes = {rule_id: index for index, rule_id in enumerate(rule_ids)}
    rules = [
        {
            "id": rule_id,
            "name": rule_id.replace("/", "-"),
            "shortDescription": {"text": rule_id},
        }
        for rule_id in rule_ids
    ]
    payload = {
        "$schema": _SCHEMA,
        "runs": [
            {
                "results": [_result(finding, rule_indexes) for finding in ordered],
                "tool": {
                    "driver": {
                        "name": "NameScraper audit",
                        "rules": rules,
                        "semanticVersion": "1.0.0",
                    }
                },
            }
        ],
        "version": "2.1.0",
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def run(repo_root: Path, options: object) -> int:
    artifact = _artifacts.read_artifact(repo_root, "findings")
    raw_findings = artifact.get("findings", [])
    if not isinstance(raw_findings, list):
        raise ValueError("findings artifact has unsupported schema")
    findings: list[dict[str, object]] = []
    for item in cast(list[object], raw_findings):
        if not isinstance(item, dict):
            raise ValueError("findings artifact has unsupported schema")
        findings.append(cast(dict[str, object], item))
    _artifacts.write_text_lf(repo_root / "audit.sarif", render(findings))
    print(f"render-sarif: {len(findings)} results in audit.sarif")
    return 0
