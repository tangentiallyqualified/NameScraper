from __future__ import annotations

from pathlib import Path

from audit import _artifacts, _diff


def _metrics(loc=100, cc=5, cov=80.0, dead=0, sha="aa", path="plex_renamer/alpha.py"):
    return {"modules": {path: {"module": "plex_renamer.alpha", "loc": loc, "sha256": sha,
                               "max_complexity": cc, "avg_complexity": 2.0, "fan_in": 1,
                               "fan_out": 0, "coverage_percent": cov, "dead_candidates": dead,
                               "dead_high_confidence": dead, "public_symbols": 2, "flags": []}},
            "headline": {"files": 1, "total_loc": loc, "avg_coverage": cov,
                         "dead_high_confidence": dead, "dead_low_confidence": 0, "cycles": 0,
                         "modules_over_complexity": 0, "coverage_stale": False}}


def _baseline_from(metrics: dict) -> dict:
    return {"commit": "old1234", "generated_at": "2026-07-01T00:00:00+00:00",
            "modules": {p: {k: r[k] for k in
                            ("sha256", "loc", "max_complexity", "coverage_percent", "dead_candidates")}
                        for p, r in metrics["modules"].items()},
            "headline": metrics["headline"]}


def test_first_run_has_no_movements():
    result = _diff.compare(None, _metrics())
    assert result["first_run"] is True
    assert result["movements"] == []


def test_threshold_movements_reported():
    base = _baseline_from(_metrics(loc=100, cc=5, cov=80.0))
    result = _diff.compare(base, _metrics(loc=180, cc=12, cov=60.0))
    text = " ".join(result["movements"])
    assert "loc 100 -> 180" in text
    assert "max_complexity 5 -> 12" in text
    assert "coverage 80.0 -> 60.0" in text


def test_small_changes_ignored():
    base = _baseline_from(_metrics(loc=100, cc=5, cov=80.0))
    result = _diff.compare(base, _metrics(loc=110, cc=7, cov=75.0))
    assert result["movements"] == []


def test_rename_detected_by_hash():
    base = _baseline_from(_metrics(path="plex_renamer/old.py", sha="samehash"))
    result = _diff.compare(base, _metrics(path="plex_renamer/new.py", sha="samehash"))
    assert result["renamed"] == [{"from": "plex_renamer/old.py", "to": "plex_renamer/new.py"}]
    assert result["added"] == [] and result["removed"] == []


def test_run_writes_changes_and_baseline_capped(synthetic_repo: Path):
    _artifacts.write_artifact(synthetic_repo, "metrics", _metrics())
    for i in range(12):
        assert _diff.run(synthetic_repo, None) == 0
    changes = (synthetic_repo / "docs" / "audit" / "CHANGES.md").read_text(encoding="utf-8")
    assert changes.count("## Audit ") == 10  # capped
    baseline = (synthetic_repo / "docs" / "audit" / "baseline.json")
    assert baseline.exists()
