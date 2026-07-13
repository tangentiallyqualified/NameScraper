from __future__ import annotations

from audit import _metrics


def _fixtures():
    inventory = {"python_files": [
        {"path": "plex_renamer/alpha.py", "package": "plex_renamer", "loc": 100, "sha256": "aa"},
        {"path": "plex_renamer/beta.py", "package": "plex_renamer", "loc": 50, "sha256": "bb"},
    ]}
    graph = {"modules": {
        "plex_renamer.alpha": {"path": "plex_renamer/alpha.py", "doc": "Alpha.", "imports": [],
                               "fan_in": 1, "fan_out": 0,
                               "symbols": [{"name": "used_function", "public": True, "imported_by": ["plex_renamer.beta"]},
                                            {"name": "dead_function", "public": True, "imported_by": []}]},
        "plex_renamer.beta": {"path": "plex_renamer/beta.py", "doc": "Beta.", "imports": ["plex_renamer.alpha"],
                              "fan_in": 0, "fan_out": 1,
                              "symbols": [{"name": "run", "public": True, "imported_by": []}]},
    }, "cycles": []}
    analysis = {
        "findings": [
            {"source": "vulture", "path": "plex_renamer/alpha.py", "line": 9, "symbol": "dead_function",
             "category": "dead-code", "assessment": "high-confidence", "allowlisted": False,
             "rule": "unused-function", "message": "m", "confidence": 60},
            {"source": "radon", "path": "plex_renamer/beta.py", "line": 4, "symbol": "run",
             "category": "complexity", "allowlisted": False, "rule": "CC", "message": "m", "confidence": 100},
        ],
        "per_file": {"plex_renamer/alpha.py": {"max_complexity": 3, "avg_complexity": 2.0, "maintainability": 80.0},
                     "plex_renamer/beta.py": {"max_complexity": 14, "avg_complexity": 14.0, "maintainability": 60.0}},
        "tool_status": {"ruff": {"ok": True}, "vulture": {"ok": True}, "radon": {"ok": True}},
    }
    coverage = {"available": True, "stale": False, "partial": False,
                "modules": {"plex_renamer/alpha.py": {"statements": 10, "covered": 4, "percent": 40.0}}}
    return inventory, graph, analysis, coverage


def test_module_records_merge_all_stages():
    m = _metrics.build_metrics(*_fixtures())
    alpha = m["modules"]["plex_renamer/alpha.py"]
    assert alpha["module"] == "plex_renamer.alpha"
    assert alpha["loc"] == 100 and alpha["sha256"] == "aa"
    assert alpha["fan_in"] == 1 and alpha["max_complexity"] == 3
    assert alpha["coverage_percent"] == 40.0
    assert alpha["dead_high_confidence"] == 1
    assert set(alpha["flags"]) == {"low-coverage", "dead-code"}
    beta = m["modules"]["plex_renamer/beta.py"]
    assert beta["flags"] == ["complexity"]
    assert beta["coverage_percent"] is None


def test_headline():
    m = _metrics.build_metrics(*_fixtures())
    h = m["headline"]
    assert h["files"] == 2 and h["total_loc"] == 150
    assert h["dead_high_confidence"] == 1
    assert h["modules_over_complexity"] == 1
    assert h["avg_coverage"] == 40.0


def test_allowlisted_dead_code_not_counted():
    inventory, graph, analysis, coverage = _fixtures()
    analysis["findings"][0]["allowlisted"] = True
    m = _metrics.build_metrics(inventory, graph, analysis, coverage)
    assert m["modules"]["plex_renamer/alpha.py"]["dead_candidates"] == 0
    assert "dead-code" not in m["modules"]["plex_renamer/alpha.py"]["flags"]


def test_partial_coverage_ignored_for_module_and_headline():
    inventory, graph, analysis, coverage = _fixtures()
    coverage = {"available": True, "partial": True, "stale": True,
                "modules": {"plex_renamer/alpha.py": {"statements": 10, "covered": 0, "percent": 0.0}}}
    m = _metrics.build_metrics(inventory, graph, analysis, coverage)
    alpha = m["modules"]["plex_renamer/alpha.py"]
    assert alpha["coverage_percent"] is None
    assert "low-coverage" not in alpha["flags"]
    assert m["headline"]["avg_coverage"] is None
    assert m["headline"]["coverage_partial"] is True


def test_coverage_partial_false_when_not_partial():
    m = _metrics.build_metrics(*_fixtures())
    assert m["headline"]["coverage_partial"] is False
