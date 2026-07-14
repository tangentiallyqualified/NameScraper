"""Stage 7: diff current metrics against committed baseline; write CHANGES.md."""
from __future__ import annotations

import json
from pathlib import Path

from . import _artifacts, _docs_ledger

BASELINE_REL = Path("docs") / "audit" / "baseline.json"
CHANGES_REL = Path("docs") / "audit" / "CHANGES.md"
LOC_RATIO = 1.5
CC_DELTA = 5
COVERAGE_DELTA = 10.0
BASELINE_FIELDS = ("sha256", "loc", "max_complexity", "coverage_percent", "dead_candidates")
DEAD_COUNT_FIELDS = (
    "dead_high_confidence",
    "dead_low_confidence",
    "dead_medium_confidence",
    "dead_exact_low_confidence",
    "dead_test_referenced",
    "dead_protected_ambiguous",
    "dead_allowlisted",
)


def _coverage_usable(snapshot: dict) -> bool:
    """Legacy artifacts are comparable unless they explicitly report bad evidence."""
    coverage = snapshot.get("coverage")
    if isinstance(coverage, dict):
        if "usable" in coverage:
            return coverage["usable"] is True
        if coverage.get("available") is False:
            return False
        if any(coverage.get(key) is True for key in ("stale", "partial", "failed")):
            return False
    headline = snapshot.get("headline", {})
    if headline.get("coverage_usable") is False:
        return False
    return not any(
        headline.get(key) is True
        for key in ("coverage_stale", "coverage_partial", "coverage_failed")
    )


def _coverage_scope_id(snapshot: dict) -> str | None:
    coverage = snapshot.get("coverage")
    if not isinstance(coverage, dict):
        return None
    scope_id = coverage.get("scope_id")
    return scope_id.strip() if isinstance(scope_id, str) and scope_id.strip() else None


def _dead_snapshot(record: dict) -> list[dict] | None:
    symbols = record.get("dead_symbols")
    if not isinstance(symbols, list):
        return None
    snapshot = []
    for item in symbols:
        if not isinstance(item, dict) or not isinstance(item.get("symbol"), str):
            continue
        snapshot.append({
            "symbol": item["symbol"],
            "line": item.get("line"),
            "assessment": item.get("assessment"),
            "confidence": item.get("confidence"),
        })
    return sorted(snapshot, key=lambda item: (
        item["symbol"], item["line"] if isinstance(item["line"], int) else -1
    ))


def _dead_label(symbol: dict) -> str:
    assessment = symbol.get("assessment") or "unclassified"
    confidence = symbol.get("confidence")
    suffix = f", {confidence}%" if isinstance(confidence, (int, float)) else ""
    return f"{assessment}{suffix}"


def _dead_movements(path: str, was: dict, now: dict) -> list[str] | None:
    old_snapshot = _dead_snapshot(was)
    new_snapshot = _dead_snapshot(now)
    if old_snapshot is None or new_snapshot is None:
        return None
    duplicate_names = {
        name
        for name in {item["symbol"] for item in old_snapshot + new_snapshot}
        if sum(item["symbol"] == name for item in old_snapshot) > 1
        or sum(item["symbol"] == name for item in new_snapshot) > 1
    }

    def _key(item: dict) -> tuple[str, int | None]:
        return item["symbol"], item.get("line") if item["symbol"] in duplicate_names else None

    def _name(key: tuple[str, int | None]) -> str:
        symbol, line = key
        return f"{symbol}` at line {line}" if line is not None else f"{symbol}`"

    old = {_key(item): item for item in old_snapshot}
    new = {_key(item): item for item in new_snapshot}
    movements = [
        f"`{path}`: new dead symbol `{_name(key)} ({_dead_label(new[key])})"
        for key in sorted(set(new) - set(old), key=lambda value: (value[0], value[1] or -1))
    ]
    movements += [
        f"`{path}`: resolved dead symbol `{_name(key)} (was {_dead_label(old[key])})"
        for key in sorted(set(old) - set(new), key=lambda value: (value[0], value[1] or -1))
    ]
    for key in sorted(set(old) & set(new), key=lambda value: (value[0], value[1] or -1)):
        before, after = old[key], new[key]
        if ((before.get("assessment"), before.get("confidence"))
                != (after.get("assessment"), after.get("confidence"))):
            movements.append(
                f"`{path}`: dead symbol `{_name(key)} confidence "
                f"{_dead_label(before)} -> {_dead_label(after)}"
            )
    return movements


def _dead_evidence_usable(snapshot: dict, record: dict | None = None) -> bool:
    provenance = snapshot.get("dead_code")
    if isinstance(provenance, dict) and provenance.get("usable") is False:
        return False
    if record is not None and record.get("dead_evidence_usable") is False:
        return False
    return True


def _doc_snapshot(repo_root: Path) -> dict[str, dict]:
    report = _docs_ledger.staleness(repo_root, _docs_ledger.load_ledger(repo_root))
    return {
        item["path"]: {
            "stale": bool(item["stale"]),
            "reviewed_commit": item.get("reviewed_commit"),
            "error": item.get("error"),
        }
        for item in report
    }


def _doc_transitions(old: object, new: dict[str, dict]) -> list[str]:
    if not isinstance(old, dict):
        return []
    transitions = []
    for path in sorted(set(old) & set(new)):
        was, now = old[path], new[path]
        if not isinstance(was, dict) or was.get("stale") == now.get("stale"):
            continue
        before = "stale" if was.get("stale") else "current"
        after = "stale" if now.get("stale") else "current"
        transitions.append(f"`{path}`: {before} -> {after}")
    return transitions


def _baseline_module(record: dict) -> dict:
    snapshot = {key: record[key] for key in BASELINE_FIELDS}
    snapshot.update({key: record[key] for key in DEAD_COUNT_FIELDS if key in record})
    if isinstance(record.get("dead_tiers"), dict):
        snapshot["dead_tiers"] = record["dead_tiers"]
    if "dead_evidence_usable" in record:
        snapshot["dead_evidence_usable"] = record["dead_evidence_usable"]
    dead_symbols = _dead_snapshot(record)
    if dead_symbols is not None:
        snapshot["dead_symbols"] = dead_symbols
    return snapshot


_TRANSIENT_KEYS = {
    "commit",
    "generated_at",
    "age_commits",
    "collected_at_commit",
}


def _without_transient(value):
    if isinstance(value, dict):
        return {
            key: _without_transient(item)
            for key, item in value.items()
            if key not in _TRANSIENT_KEYS and key != "previous_baseline"
        }
    if isinstance(value, list):
        return [_without_transient(item) for item in value]
    return value


def _baseline_snapshot(metrics: dict, docs: dict[str, dict]) -> dict:
    snapshot = {
        "input_digest": metrics["input_digest"],
        "modules": {p: _baseline_module(r) for p, r in metrics["modules"].items()},
        "headline": metrics["headline"],
        "docs": docs,
    }
    for key in ("coverage", "dead_code", "tool_status"):
        if key in metrics:
            snapshot[key] = metrics[key]
    return _without_transient(snapshot)


def compare(baseline: dict | None, metrics: dict) -> dict:
    current = metrics["modules"]
    if baseline is None:
        return {"added": sorted(current), "removed": [], "renamed": [],
                "movements": [], "first_run": True}
    old = baseline["modules"]
    added = sorted(set(current) - set(old))
    removed = sorted(set(old) - set(current))

    renamed = []
    removed_by_sha = {old[p]["sha256"]: p for p in removed}
    still_added = []
    for p in added:
        match = removed_by_sha.pop(current[p]["sha256"], None)
        if match:
            renamed.append({"from": match, "to": p})
            removed.remove(match)
        else:
            still_added.append(p)
    added = still_added

    movements: list[str] = []
    coverage_evidence_usable = _coverage_usable(baseline) and _coverage_usable(metrics)
    old_scope_id = _coverage_scope_id(baseline)
    new_scope_id = _coverage_scope_id(metrics)
    coverage_comparable = (
        coverage_evidence_usable
        and old_scope_id is not None
        and old_scope_id == new_scope_id
    )
    if coverage_evidence_usable and not coverage_comparable:
        movements.append(
            "coverage methodology changed or is unknown; "
            "per-module coverage movements suppressed"
        )
    for path in sorted(set(current) & set(old)):
        now, was = current[path], old[path]
        if was["loc"] and now["loc"] / was["loc"] >= LOC_RATIO:
            movements.append(f"`{path}`: loc {was['loc']} -> {now['loc']}")
        if (now.get("max_complexity") is not None and was.get("max_complexity") is not None
                and now["max_complexity"] - was["max_complexity"] >= CC_DELTA):
            movements.append(f"`{path}`: max_complexity {was['max_complexity']} -> {now['max_complexity']}")
        if (coverage_comparable
                and was.get("coverage_percent") is not None and now.get("coverage_percent") is not None
                and abs(now["coverage_percent"] - was["coverage_percent"]) >= COVERAGE_DELTA):
            movements.append(f"`{path}`: coverage {was['coverage_percent']} -> {now['coverage_percent']}")
        if (_dead_evidence_usable(baseline, was)
                and _dead_evidence_usable(metrics, now)):
            dead_movements = _dead_movements(path, was, now)
            if dead_movements is not None:
                movements.extend(dead_movements)
            elif (isinstance(now.get("dead_candidates"), (int, float))
                  and isinstance(was.get("dead_candidates"), (int, float))
                  and now["dead_candidates"] > was["dead_candidates"]):
                movements.append(
                    f"`{path}`: dead candidates "
                    f"{was['dead_candidates']} -> {now['dead_candidates']}"
                )
    return {"added": added, "removed": removed, "renamed": renamed,
            "movements": movements, "first_run": False}


def _section(repo_root: Path, result: dict, baseline: dict | None, metrics: dict) -> str:
    digest = metrics.get("input_digest") or "unknown"
    base_digest = (
        (baseline.get("input_digest") or "unknown")[:12]
        if baseline else "none (first run)"
    )
    h = metrics["headline"]
    lines = [f"## Audit {digest[:12]} vs baseline ({base_digest})", ""]
    dead_summary = (
        f"{h['dead_high_confidence']} high-confidence dead symbols"
        if _dead_evidence_usable(metrics, h) else "dead-code analysis unavailable"
    )
    lines.append(
        f"- Headline: {h['files']} modules, {h['total_loc']} LOC, "
        f"{dead_summary}, {h['cycles']} cycles"
    )
    if result["first_run"]:
        lines.append("- First audit run: baseline established.")
    else:
        if result["added"]:
            lines.append("- Added: " + ", ".join(f"`{p}`" for p in result["added"]))
        if result["removed"]:
            lines.append("- Removed: " + ", ".join(f"`{p}`" for p in result["removed"]))
        for r in result["renamed"]:
            lines.append(f"- Renamed: `{r['from']}` -> `{r['to']}`")
        if result["movements"]:
            lines.append("- Notable movements:")
            lines += [f"  - {m}" for m in result["movements"]]
        if result.get("doc_transitions"):
            lines.append("- Documentation status changes:")
            lines += [f"  - {transition}" for transition in result["doc_transitions"]]
        if not any((result["added"], result["removed"], result["renamed"], result["movements"],
                    result.get("doc_transitions"))):
            lines.append("- No notable changes since baseline.")
    return "\n".join(lines)


def run(repo_root: Path, options) -> int:
    metrics = _artifacts.read_artifact(repo_root, "metrics")
    baseline_path = repo_root / BASELINE_REL
    existing = (
        json.loads(baseline_path.read_text(encoding="utf-8"))
        if baseline_path.exists() else None
    )
    same_input = (
        isinstance(existing, dict)
        and existing.get("input_digest") == metrics.get("input_digest")
    )
    if same_input:
        previous = _without_transient(existing.get("previous_baseline"))
    else:
        previous = _without_transient(existing) if isinstance(existing, dict) else None

    result = compare(previous, metrics)
    docs = _doc_snapshot(repo_root)
    result["doc_transitions"] = _doc_transitions(
        previous.get("docs") if isinstance(previous, dict) else None, docs
    )

    changes_path = repo_root / CHANGES_REL
    current_digest = metrics.get("input_digest") or "unknown"
    previous_digest = (
        previous.get("input_digest") or "unknown"
        if isinstance(previous, dict) else "none"
    )
    body = "\n".join([
        "# Audit Change Log",
        "",
        f"<!-- audit:input-digest: {current_digest} -->",
        f"<!-- audit:baseline-input-digest: {previous_digest} -->",
        "",
        _section(repo_root, result, previous, metrics).strip(),
        "",
    ])
    changes_path.parent.mkdir(parents=True, exist_ok=True)
    changes_path.write_text(body, encoding="utf-8")

    new_baseline = _baseline_snapshot(metrics, docs)
    new_baseline["previous_baseline"] = previous
    baseline_path.write_text(json.dumps(new_baseline, indent=1, sort_keys=True), encoding="utf-8")
    n = len(result["movements"])
    print(f"diff: {len(result['added'])} added, {len(result['removed'])} removed, {n} movements; baseline refreshed")
    return 0
