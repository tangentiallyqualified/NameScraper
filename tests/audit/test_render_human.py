from __future__ import annotations

from pathlib import Path

from audit import _render_human


def test_replace_generated_preserves_curated_text():
    existing = (
        "# Map\n\nMy hand-written intro.\n\n"
        "<!-- audit:generated:start metrics -->\nold table\n<!-- audit:generated:end metrics -->\n\n"
        "My hand-written outro.\n"
    )
    merged = _render_human.replace_generated(existing, "metrics", "new table")
    assert "My hand-written intro." in merged
    assert "My hand-written outro." in merged
    assert "new table" in merged
    assert "old table" not in merged


def test_replace_generated_creates_section_when_missing():
    merged = _render_human.replace_generated(None, "metrics", "table v1")
    assert "audit:generated:start metrics" in merged
    assert "table v1" in merged


def _run_all_stages(repo: Path) -> None:
    from audit import _artifacts, _graph, _inventory, _metrics
    _inventory.run(repo, None)
    _graph.run(repo, None)
    _artifacts.write_artifact(repo, "analysis", {
        "findings": [{"source": "vulture", "path": "plex_renamer/alpha.py", "line": 9,
                      "symbol": "dead_function", "category": "dead-code",
                      "assessment": "high-confidence", "allowlisted": False,
                      "rule": "unused-function", "message": "unused function 'dead_function'",
                      "confidence": 60}],
        "per_file": {}, "tool_status": {}})
    _artifacts.write_artifact(repo, "coverage", {"available": False, "modules": {}})
    _metrics.run(repo, None)


def test_overview_contains_mermaid_and_dead_checklist(synthetic_repo: Path):
    _run_all_stages(synthetic_repo)
    assert _render_human.run(synthetic_repo, None) == 0
    overview = (synthetic_repo / "docs" / "audit" / "maps" / "overview.md").read_text(encoding="utf-8")
    assert "```mermaid" in overview
    assert "- [ ] `plex_renamer/alpha.py:9` dead_function (high-confidence)" in overview


def test_rerun_preserves_curated_prose(synthetic_repo: Path):
    _run_all_stages(synthetic_repo)
    _render_human.run(synthetic_repo, None)
    overview_path = synthetic_repo / "docs" / "audit" / "maps" / "overview.md"
    content = overview_path.read_text(encoding="utf-8")
    overview_path.write_text("CURATED NOTE\n\n" + content, encoding="utf-8")
    _render_human.run(synthetic_repo, None)
    assert overview_path.read_text(encoding="utf-8").startswith("CURATED NOTE")


def test_replace_generated_appends_when_markers_absent():
    merged = _render_human.replace_generated("Just prose, no markers.", "metrics", "new table")
    assert merged.startswith("Just prose, no markers.")
    assert "audit:generated:start metrics" in merged
    assert "new table" in merged
