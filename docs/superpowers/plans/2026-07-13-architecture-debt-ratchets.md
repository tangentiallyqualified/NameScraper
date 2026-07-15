# Architecture Debt Ratchets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dependency direction and cycle growth blocking, then remove the settings cycle and safely decompose the large engine/application strongly connected component.

**Architecture:** The graph analyzer records exact strongly connected components and contract edges in a machine-readable baseline. New/enlarged SCCs fail immediately. Existing cycles are removed through characterization tests, leaf-first import changes, explicit ports, and package facades that never import implementation modules back into their dependencies.

**Tech Stack:** Existing AST dependency graph, pytest, TOML contracts, generated Mermaid maps.

## Global Constraints

- No architecture refactor is justified by a metric alone.
- Every removed cycle edge has a characterization test for the behavior crossing it.
- `engine` remains headless and cannot import `app` or `gui_qt`.
- `app` may depend on `engine` ports/models; `gui_qt` may depend on `app` and public engine types.
- New or enlarged strongly connected components fail CI.
- Public package facades cannot be imported internally when doing so creates a back edge.

---

### Task 1: Baseline and gate exact dependency cycles

**Files:** modify `scripts/audit/_graph.py`, `scripts/audit/contracts.toml`,
`tests/audit/test_graph.py`, and `tests/audit/test_repository_contracts.py`;
create `scripts/audit/cycle-baseline.json`.

**Interfaces:** each SCC is a sorted module list with sorted internal edges;
contract evaluation reports `new-cycle`, `enlarged-cycle`, and
`forbidden-import` findings.

- [ ] Write RED synthetic-repository tests for stable SCC ordering, unchanged legacy cycles, new cycles, and one-module shrinkage.
- [ ] Implement exact SCC baseline comparison and blocking repository test.
- [ ] Generate the two-cycle baseline and commit with `feat(architecture): ratchet dependency cycles`.

### Task 2: Remove the settings-page cycle

**Files:** inspect and modify
`_settings_automux_page.py`, `_settings_metadata_page.py`, and
`_settings_tab_sections.py`; add focused settings tests.

**Interfaces:** shared page-building types/constants move to a leaf module that
imports no concrete settings page; the section composer imports concrete pages
one-way.

- [ ] Capture the three exact internal edges and write RED import-graph assertion.
- [ ] Add behavioral characterization for page construction and persistence.
- [ ] Move only shared declarations needed to reverse the edges.
- [ ] Run settings tests, graph tests, and audit verification.
- [ ] Lower the cycle baseline and commit with `refactor(settings): remove page import cycle`.

### Task 3: Characterize the nineteen-module SCC and classify its edges

**Files:** create `docs/audit/engine-cycle-edges.toml`; modify graph renderer and
tests.

**Interfaces:** each internal edge has owner, import purpose, and disposition:
`facade-backedge`, `shared-model`, `runtime-construction`, or `algorithm-call`.

- [ ] Generate the exact edge inventory programmatically.
- [ ] Fail tests when an SCC edge lacks a classification.
- [ ] Render the classified cycle map without hand-written graph prose.
- [ ] Commit with `docs(architecture): classify engine cycle edges`.

### Task 4: Remove package-facade back edges

**Files:** modify only modules classified `facade-backedge`, corresponding
`engine/__init__.py` exports, and focused tests.

**Interfaces:** internal engine modules import leaf modules directly; external
callers retain supported facade exports.

- [ ] Write RED graph assertions for each planned edge and import-compatibility tests for public exports.
- [ ] Replace facade imports leaf-first without moving behavior.
- [ ] Run affected engine tests and reduce the SCC baseline after every edge batch.
- [ ] Commit each independent batch as `refactor(engine): remove facade back edges`.

### Task 5: Invert runtime-construction edges through ports

**Files:** extend `engine/_discovery_ports.py` or create focused sibling port
modules; modify app composition roots and the exact engine consumers; add
contract and behavior tests.

**Interfaces:** ports use `Protocol`; concrete application services are created
only in application/GUI composition roots and injected into engine workflows.

- [ ] Write RED contract tests proving the forbidden concrete import.
- [ ] Write characterization tests using small fake port implementations.
- [ ] Introduce the minimal protocol and inject it through existing constructors.
- [ ] Run focused and full tests; lower the cycle baseline and commit each port separately.

### Task 6: Refactor complexity hotspots only along proven seams

**Files:** candidates are `_episode_resolution.py`, `_parsing_episodes.py`,
`job_executor.py`, and `_media_workspace_actions.py`; exact files are selected
one at a time from the edge/behavior evidence.

**Interfaces:** extracted units have one responsibility, explicit inputs/outputs,
and no import back to their former coordinator.

- [ ] Select one unstable or actively modified hotspot; do not batch all four.
- [ ] Add characterization and property-oriented tests for its decision table.
- [ ] Extract one cohesive unit and prove the old public behavior unchanged.
- [ ] Run quality ratchets and commit; repeat only when a second seam is justified.

### Task 7: Final architecture verification

- [ ] Run repository contract, graph, affected GUI, and full pytest suites.
- [ ] Run `scripts\audit.cmd`, then `scripts\audit.cmd --verify`.
- [ ] Confirm zero settings SCC and a strictly smaller engine SCC.
- [ ] Commit deterministic graph/baseline updates with `chore(architecture): refresh cycle baseline`.
