from __future__ import annotations

import json
from pathlib import Path

from audit import _artifacts, _diff


def _metrics(loc=100, cc=5, cov=80.0, dead=0, sha="aa", path="plex_renamer/alpha.py",
             dead_symbols=None, coverage=None, input_digest="a" * 64):
    metrics = {"input_digest": input_digest,
            "modules": {path: {"module": "plex_renamer.alpha", "loc": loc, "sha256": sha,
                               "max_complexity": cc, "avg_complexity": 2.0, "fan_in": 1,
                               "fan_out": 0, "coverage_percent": cov, "dead_candidates": dead,
                               "dead_high_confidence": dead, "public_symbols": 2, "flags": []}},
            "headline": {"files": 1, "total_loc": loc, "avg_coverage": cov,
                         "dead_high_confidence": dead, "dead_low_confidence": 0, "cycles": 0,
                         "modules_over_complexity": 0, "coverage_stale": False}}
    if dead_symbols is not None:
        metrics["modules"][path]["dead_symbols"] = dead_symbols
    metrics["coverage"] = (
        {"usable": True, "scope_id": "scope-default"}
        if coverage is None else coverage
    )
    return metrics


def _baseline_from(metrics: dict) -> dict:
    baseline = {
        "commit": "old1234", "generated_at": "2026-07-01T00:00:00+00:00",
        "modules": {p: {k: r[k] for k in
                        ("sha256", "loc", "max_complexity", "coverage_percent", "dead_candidates")}
                    for p, r in metrics["modules"].items()},
        "headline": metrics["headline"],
    }
    if "coverage" in metrics:
        baseline["coverage"] = metrics["coverage"]
    return baseline


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


def test_coverage_recovery_reported():
    base = _baseline_from(_metrics(cov=10.0))
    result = _diff.compare(base, _metrics(cov=75.0))
    assert "coverage 10.0 -> 75.0" in " ".join(result["movements"])


def test_unusable_coverage_on_either_side_suppresses_movement():
    base = _baseline_from(_metrics(cov=10.0))
    base["coverage"] = {"usable": False, "stale": True}
    current = _metrics(cov=75.0, coverage={"usable": True})
    assert "coverage" not in " ".join(_diff.compare(base, current)["movements"])

    base["coverage"] = {"usable": True}
    current["coverage"] = {"usable": False, "failed": True}
    assert "coverage" not in " ".join(_diff.compare(base, current)["movements"])


def test_changed_coverage_scope_suppresses_movements_and_emits_one_note():
    base = _baseline_from(_metrics(
        cov=10.0, coverage={"usable": True, "scope_id": "scope-old"}
    ))
    current = _metrics(
        cov=75.0, coverage={"usable": True, "scope_id": "scope-new"}
    )

    result = _diff.compare(base, current)

    notes = [item for item in result["movements"] if "coverage methodology changed" in item]
    assert len(notes) == 1
    assert "per-module coverage movements suppressed" in notes[0]
    assert not any("coverage 10.0 -> 75.0" in item for item in result["movements"])
    assert set(result) == {"added", "removed", "renamed", "movements", "first_run"}


def test_legacy_unknown_coverage_scope_suppresses_movements_with_note():
    base = _baseline_from(_metrics(cov=10.0))
    base.pop("coverage")
    current = _metrics(cov=75.0)

    result = _diff.compare(base, current)

    assert sum("coverage methodology changed" in item for item in result["movements"]) == 1
    assert not any("coverage 10.0 -> 75.0" in item for item in result["movements"])

def test_small_changes_ignored():
    base = _baseline_from(_metrics(loc=100, cc=5, cov=80.0))
    result = _diff.compare(base, _metrics(loc=110, cc=7, cov=75.0))
    assert result["movements"] == []


def test_unavailable_complexity_does_not_break_comparison():
    base = _baseline_from(_metrics(cc=5))
    current = _metrics(cc=None)
    assert _diff.compare(base, current)["movements"] == []


def test_unavailable_dead_evidence_does_not_compare_or_render_numeric_zero(
        synthetic_repo: Path):
    base = _baseline_from(_metrics(dead=2))
    current = _metrics(dead=0)
    record = current["modules"]["plex_renamer/alpha.py"]
    for key in ("dead_candidates", "dead_high_confidence"):
        record[key] = None
    record.update({
        "dead_symbols": None,
        "dead_tiers": None,
        "dead_evidence_usable": False,
    })
    current["headline"]["dead_high_confidence"] = None
    current["headline"]["dead_evidence_usable"] = False
    current["dead_code"] = {
        "usable": False, "source": "vulture", "reason": "crashed",
        "observed_findings": 0,
    }

    result = _diff.compare(base, current)
    section = _diff._section(synthetic_repo, result, base, current)

    assert set(result) == {"added", "removed", "renamed", "movements", "first_run"}
    assert "dead candidates" not in "\n".join(result["movements"])
    assert "dead-code analysis unavailable" in section
    assert "None high-confidence" not in section


def test_rename_detected_by_hash():
    base = _baseline_from(_metrics(path="plex_renamer/old.py", sha="samehash"))
    result = _diff.compare(base, _metrics(path="plex_renamer/new.py", sha="samehash"))
    assert result["renamed"] == [{"from": "plex_renamer/old.py", "to": "plex_renamer/new.py"}]
    assert result["added"] == [] and result["removed"] == []


def test_run_is_byte_identical_for_the_same_input_digest(synthetic_repo: Path):
    _artifacts.write_artifact(synthetic_repo, "metrics", _metrics())

    assert _diff.run(synthetic_repo, None) == 0
    baseline_path = synthetic_repo / "docs" / "audit" / "baseline.json"
    changes_path = synthetic_repo / "docs" / "audit" / "CHANGES.md"
    first_baseline = baseline_path.read_bytes()
    first_changes = changes_path.read_bytes()

    assert _diff.run(synthetic_repo, None) == 0
    assert baseline_path.read_bytes() == first_baseline
    assert changes_path.read_bytes() == first_changes


def test_new_digest_rotates_current_snapshot_exactly_once(synthetic_repo: Path):
    first = _metrics(loc=100, input_digest="a" * 64)
    _artifacts.write_artifact(synthetic_repo, "metrics", first)
    assert _diff.run(synthetic_repo, None) == 0

    second = _metrics(loc=180, input_digest="b" * 64)
    _artifacts.write_artifact(synthetic_repo, "metrics", second)
    assert _diff.run(synthetic_repo, None) == 0
    baseline_path = synthetic_repo / "docs" / "audit" / "baseline.json"
    rotated = json.loads(baseline_path.read_text(encoding="utf-8"))

    assert rotated["input_digest"] == "b" * 64
    assert rotated["previous_baseline"]["input_digest"] == "a" * 64
    assert "previous_baseline" not in rotated["previous_baseline"]
    changes = (synthetic_repo / "docs" / "audit" / "CHANGES.md").read_text(
        encoding="utf-8"
    )
    assert "<!-- audit:input-digest: " + "b" * 64 + " -->" in changes
    assert "<!-- audit:baseline-input-digest: " + "a" * 64 + " -->" in changes
    assert "## Audit " + "b" * 12 + " vs baseline (" + "a" * 12 + ")" in changes

    assert _diff.run(synthetic_repo, None) == 0
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == rotated


def test_baseline_omits_transient_provenance(synthetic_repo: Path):
    metrics = _metrics(coverage={
        "usable": True,
        "input_digest": "a" * 64,
        "collected_at_commit": "old1234",
        "age_commits": 3,
    })
    metrics.update({"commit": "current123", "generated_at": "now"})
    _artifacts.write_artifact(synthetic_repo, "metrics", metrics)

    assert _diff.run(synthetic_repo, None) == 0
    baseline = json.loads(
        (synthetic_repo / "docs" / "audit" / "baseline.json").read_text(
            encoding="utf-8"
        )
    )
    encoded = json.dumps(baseline)
    assert "generated_at" not in encoded
    assert '"commit"' not in encoded
    assert "collected_at_commit" not in encoded
    assert "age_commits" not in encoded


def test_duplicate_sha_rename_consumed_once():
    base = _baseline_from(_metrics(path="plex_renamer/old.py", sha="samehash"))
    m = _metrics(path="plex_renamer/new1.py", sha="samehash")
    m["modules"]["plex_renamer/new2.py"] = dict(m["modules"]["plex_renamer/new1.py"])
    result = _diff.compare(base, m)
    assert result["renamed"] == [{"from": "plex_renamer/old.py", "to": "plex_renamer/new1.py"}]
    assert result["added"] == ["plex_renamer/new2.py"]
    assert result["removed"] == []


def test_dead_symbol_deltas_and_confidence_changes():
    before = [
        {"symbol": "resolved", "line": 4, "assessment": "medium-confidence", "confidence": 60},
        {"symbol": "changed", "line": 8, "assessment": "medium-confidence", "confidence": 60},
    ]
    after = [
        {"symbol": "changed", "line": 9, "assessment": "high-confidence", "confidence": 90},
        {"symbol": "new_one", "line": 12, "assessment": "medium-confidence", "confidence": 60},
    ]
    base = _baseline_from(_metrics(dead=2, dead_symbols=before))
    base["modules"]["plex_renamer/alpha.py"]["dead_symbols"] = before
    result = _diff.compare(base, _metrics(dead=2, dead_symbols=after))
    text = "\n".join(result["movements"])
    assert "new dead symbol `new_one` (medium-confidence, 60%)" in text
    assert "resolved dead symbol `resolved` (was medium-confidence, 60%)" in text
    assert "dead symbol `changed` confidence medium-confidence, 60% -> high-confidence, 90%" in text


def test_duplicate_dead_symbol_names_keep_line_identity():
    before = [
        {"symbol": "duplicate", "line": 4, "assessment": "medium-confidence", "confidence": 60},
        {"symbol": "duplicate", "line": 20, "assessment": "medium-confidence", "confidence": 60},
    ]
    after = [
        {"symbol": "duplicate", "line": 20, "assessment": "high-confidence", "confidence": 90},
    ]
    base = _baseline_from(_metrics(dead=2, dead_symbols=before))
    base["modules"]["plex_renamer/alpha.py"]["dead_symbols"] = before
    text = "\n".join(_diff.compare(base, _metrics(dead=1, dead_symbols=after))["movements"])
    assert "resolved dead symbol `duplicate` at line 4" in text
    assert "dead symbol `duplicate` at line 20 confidence" in text


def test_legacy_baseline_has_no_symbol_level_deltas():
    base = _baseline_from(_metrics(dead=1))
    current = _metrics(dead=2, dead_symbols=[
        {"symbol": "new_one", "line": 12, "assessment": "medium-confidence", "confidence": 60},
    ])
    result = _diff.compare(base, current)
    assert result["movements"] == ["`plex_renamer/alpha.py`: dead candidates 1 -> 2"]


def test_input_digest_controls_section_header(synthetic_repo: Path):
    metrics = _metrics()
    section = _diff._section(synthetic_repo, _diff.compare(None, metrics), None, metrics)
    assert "## Audit " + "a" * 12 + " vs baseline (none (first run))" in section


def test_run_snapshots_and_reports_doc_status_transitions(synthetic_repo: Path, monkeypatch):
    metrics = _metrics()
    _artifacts.write_artifact(synthetic_repo, "metrics", metrics)
    baseline = _baseline_from(metrics)
    baseline["docs"] = {"docs/guide.md": {"stale": False, "reviewed_commit": "old"}}
    baseline_path = synthetic_repo / "docs" / "audit" / "baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    monkeypatch.setattr(_diff, "_doc_snapshot", lambda repo: {
        "docs/guide.md": {"stale": True, "reviewed_commit": "old", "error": None}
    })

    assert _diff.run(synthetic_repo, None) == 0
    changes = (synthetic_repo / "docs" / "audit" / "CHANGES.md").read_text(encoding="utf-8")
    assert "Documentation status changes:" in changes
    assert "`docs/guide.md`: current -> stale" in changes
    saved = json.loads(baseline_path.read_text(encoding="utf-8"))
    assert saved["docs"]["docs/guide.md"]["stale"] is True


def test_baseline_keeps_dead_snapshots_and_confidence_counts(synthetic_repo: Path):
    symbols = [
        {"symbol": "dead", "line": 7, "assessment": "medium-confidence", "confidence": 60}
    ]
    metrics = _metrics(dead=1, dead_symbols=symbols, coverage={"usable": True})
    record = metrics["modules"]["plex_renamer/alpha.py"]
    record["dead_medium_confidence"] = 1
    record["dead_tiers"] = {"medium-confidence": 1}
    _artifacts.write_artifact(synthetic_repo, "metrics", metrics)

    assert _diff.run(synthetic_repo, None) == 0
    baseline = json.loads(
        (synthetic_repo / "docs" / "audit" / "baseline.json").read_text(encoding="utf-8")
    )
    saved = baseline["modules"]["plex_renamer/alpha.py"]
    assert saved["dead_medium_confidence"] == 1
    assert saved["dead_tiers"] == {"medium-confidence": 1}
    assert saved["dead_symbols"] == symbols
    assert baseline["coverage"] == {"usable": True}
