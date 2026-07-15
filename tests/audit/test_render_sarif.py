from __future__ import annotations

import json

from scripts.audit import _render_sarif


def test_sarif_21_has_deterministic_rules_results_and_locations() -> None:
    findings: list[dict[str, object]] = [
        {
            "analyzer": "vulture",
            "rule": "unused-method",
            "path": "plex_renamer/gui.py",
            "line": 12,
            "column": 5,
            "symbol": "plex_renamer.gui.Window.paintEvent#1",
            "message": "unused method 'paintEvent'",
            "category": "dead-code",
            "decision": {
                "reason_code": "framework-callback",
                "reason": "Qt invokes this override.",
                "expiry": None,
            },
        },
        {
            "analyzer": "ruff",
            "rule": "F401",
            "path": "plex_renamer/alpha.py",
            "line": 3,
            "column": 1,
            "symbol": "plex_renamer.alpha::unused-import::json#1",
            "message": "json imported but unused",
            "category": "lint",
            "decision": None,
        },
    ]

    first = _render_sarif.render(findings)
    second = _render_sarif.render(list(reversed(findings)))

    assert first == second
    payload = json.loads(first)
    assert payload["version"] == "2.1.0"
    assert payload["$schema"].endswith("sarif-schema-2.1.0.json")
    run = payload["runs"][0]
    assert [rule["id"] for rule in run["tool"]["driver"]["rules"]] == [
        "ruff/F401",
        "vulture/unused-method",
    ]
    assert [result["ruleId"] for result in run["results"]] == [
        "ruff/F401",
        "vulture/unused-method",
    ]
    location = run["results"][0]["locations"][0]["physicalLocation"]
    assert location == {
        "artifactLocation": {"uri": "plex_renamer/alpha.py", "uriBaseId": "%SRCROOT%"},
        "region": {"startColumn": 1, "startLine": 3},
    }
    assert run["results"][1]["suppressions"] == [
        {
            "kind": "external",
            "justification": "framework-callback: Qt invokes this override.",
        }
    ]
    assert run["results"][1]["properties"]["qualifiedSymbol"].endswith("paintEvent#1")
