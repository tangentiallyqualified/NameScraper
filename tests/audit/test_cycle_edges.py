"""Characterizations for classified engine cycle-edge audit output."""

from pathlib import Path

import pytest

from scripts.audit import _cycle_edges


def _engine_cycle_graph() -> dict[str, object]:
    return {
        "modules": {},
        "cycles": [
            {
                "modules": [
                    "plex_renamer.engine.alpha",
                    "plex_renamer.engine.beta",
                ],
                "edges": [
                    ["plex_renamer.engine.alpha", "plex_renamer.engine.beta"],
                    ["plex_renamer.engine.beta", "plex_renamer.engine.alpha"],
                ],
            }
        ],
    }


def _write_cycle_classifications(repo: Path, records: str) -> None:
    path = repo / "docs" / "audit" / "engine-cycle-edges.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("version = 1\n\n" + records, encoding="utf-8")


def test_cycle_edge_classifications_require_exact_graph_coverage(synthetic_repo: Path):
    _write_cycle_classifications(
        synthetic_repo,
        """
[[edges]]
source = "plex_renamer.engine.alpha"
target = "plex_renamer.engine.beta"
owner = "engine-alpha"
purpose = "Call beta's algorithm."
disposition = "algorithm-call"

[[edges]]
source = "plex_renamer.engine.gamma"
target = "plex_renamer.engine.alpha"
owner = "engine-gamma"
purpose = "Invented edge."
disposition = "algorithm-call"
""",
    )

    with pytest.raises(ValueError) as exc_info:
        _cycle_edges.load_cycle_edge_classifications(synthetic_repo, _engine_cycle_graph())

    message = str(exc_info.value)
    assert "missing" in message
    assert "plex_renamer.engine.beta -> plex_renamer.engine.alpha" in message
    assert "unexpected" in message
    assert "plex_renamer.engine.gamma -> plex_renamer.engine.alpha" in message


@pytest.mark.parametrize(
    ("field_line", "message"),
    [
        ('owner = ""', "owner must be a non-empty string"),
        ('purpose = ""', "purpose must be a non-empty string"),
        ('disposition = "unknown"', "unsupported disposition"),
    ],
)
def test_cycle_edge_classifications_validate_schema(
    synthetic_repo: Path,
    field_line: str,
    message: str,
):
    first = {
        "owner": 'owner = "engine-alpha"',
        "purpose": 'purpose = "Call beta."',
        "disposition": 'disposition = "algorithm-call"',
    }
    first[field_line.split(" =", 1)[0]] = field_line
    _write_cycle_classifications(
        synthetic_repo,
        f"""
[[edges]]
source = "plex_renamer.engine.alpha"
target = "plex_renamer.engine.beta"
{first["owner"]}
{first["purpose"]}
{first["disposition"]}

[[edges]]
source = "plex_renamer.engine.beta"
target = "plex_renamer.engine.alpha"
owner = "engine-beta"
purpose = "Call alpha."
disposition = "algorithm-call"
""",
    )

    with pytest.raises(ValueError, match=message):
        _cycle_edges.load_cycle_edge_classifications(synthetic_repo, _engine_cycle_graph())


def test_cycle_edge_classifications_require_every_schema_field(synthetic_repo: Path):
    _write_cycle_classifications(
        synthetic_repo,
        """
[[edges]]
source = "plex_renamer.engine.alpha"
target = "plex_renamer.engine.beta"
purpose = "Call beta."
disposition = "algorithm-call"

[[edges]]
source = "plex_renamer.engine.beta"
target = "plex_renamer.engine.alpha"
owner = "engine-beta"
purpose = "Call alpha."
disposition = "algorithm-call"
""",
    )

    with pytest.raises(ValueError, match="missing fields: owner"):
        _cycle_edges.load_cycle_edge_classifications(synthetic_repo, _engine_cycle_graph())


def test_cycle_edge_classifications_reject_duplicate_edges(synthetic_repo: Path):
    duplicate = """
[[edges]]
source = "plex_renamer.engine.alpha"
target = "plex_renamer.engine.beta"
owner = "engine-alpha"
purpose = "Call beta."
disposition = "algorithm-call"
"""
    _write_cycle_classifications(synthetic_repo, duplicate + duplicate)

    with pytest.raises(ValueError, match="duplicate classification"):
        _cycle_edges.load_cycle_edge_classifications(synthetic_repo, _engine_cycle_graph())


def test_classified_cycle_map_is_rendered_from_sorted_toml_records(synthetic_repo: Path):
    _write_cycle_classifications(
        synthetic_repo,
        """
[[edges]]
source = "plex_renamer.engine.beta"
target = "plex_renamer.engine.alpha"
owner = "engine-beta"
purpose = "Consume shared data."
disposition = "runtime-construction"

[[edges]]
source = "plex_renamer.engine.alpha"
target = "plex_renamer.engine.beta"
owner = "engine-alpha"
purpose = "Call beta's algorithm."
disposition = "algorithm-call"
""",
    )
    classifications = _cycle_edges.load_cycle_edge_classifications(
        synthetic_repo,
        _engine_cycle_graph(),
    )

    rendered = _cycle_edges.render_classified_cycle_map(classifications)

    assert rendered.index("alpha -->|algorithm-call| beta") < rendered.index(
        "beta -->|runtime-construction| alpha"
    )
    assert "| `plex_renamer.engine.alpha` | `plex_renamer.engine.beta` | engine-alpha |" in rendered
    assert "Call beta's algorithm." in rendered
