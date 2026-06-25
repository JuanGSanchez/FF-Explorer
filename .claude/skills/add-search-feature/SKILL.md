---
name: add-search-feature
description: >
  Guides extending FF-Explorer's headless query engine with a new search
  capability (match mode, filter predicate, flag) the right way — added in
  core.py, surfaced through service.py so REST+MCP inherit it, defaulting to
  current behavior, and covered by deterministic tests that keep the 90% gate.
  Use this skill when implementing a search/query backlog item (FFX-I01 regex,
  FFX-I02 size/date/type filters, FFX-I04 ignore globs, FFX-I09 content search)
  or when the user says "add a match mode", "add a query filter", "extend the
  search". For wiring an existing core op to REST+MCP, use expose-op instead.
version: 0.1.0
principles_applied:
  inherited:
    - P1 — Source-of-Truth Grounding
    - P2 — Full Determinism
    - P3 — Systematicity
    - P4 — Consistency
    - P5 — Context Budget Discipline
    - P6 — Self-Containment
    - P7 — Reference Hygiene
    - P8 — Principles Inheritance
    - P9 — Role Separation
    - P10 — Exit-Status Determinism
    - P11 — Programmatic Determinism
    - P12 — Maximal-Effort Completeness
    - P13 — Token Economy
  refs:
    - "R17 Engineering Disciplines; cite repo-enhancer/orchestrator.md CONVENTIONS."
  custom:
    - id: C1
      name: Core-First, Default-Safe, Tested
      requires: new search logic lives in core (stdlib-first), is surfaced via
        service so both transports inherit it, defaults to today's behavior when
        the new option is unset, and ships with deterministic tmp_path tests that
        keep --cov-fail-under=90 — never lowering the gate.
      rationale: A search feature added in a route, or one that changes default
        results, forks the transports or breaks callers.
---

# Add Search Feature

A repeatable path for adding a query capability to FF-Explorer without forking transports, breaking defaults, or weakening the gate.

## Workflow

### Step 1: Anchor on the item
Grep `docs/BACKLOG.md` for the ID; read only that block. Extract the new parameter/flag, its default, and the Acceptance criterion (including the default-unchanged and error-path clauses). Confirm this is core query work (not a route-only wiring task — that is `expose-op`).

### Step 2: Verify the current query shape
Grep to `list_entries`/the filter in `ff_explorer/core.py`; Read only that region. Confirm the current matching contract (the case-sensitive `in` test) before changing it (verify-before-edit).

### Step 3: Add the capability in core (stdlib-first)
Add a typed parameter with a default equal to current behavior. Use the stdlib: `re` for regex, `fnmatch.translate` for glob, `Path.stat()` for size/date/type predicates, `pathspec` only if the item authorizes an ignore-file dep. Compile patterns once. Apply the new predicate AFTER the name match so unset options reproduce today's results exactly.

### Step 4: Surface through service (not the route)
Thread the new parameter through `ff_explorer/api/service.py` so the shared wrapper carries it; the REST field + MCP tool come from the access layer (hand off to access-dev / the `expose-op` skill for the Pydantic field if the item spans transports). Never put query logic in `rest.py`/`mcp_server.py`.

### Step 5: Run the scaffold helper
Run `python .claude/skills/add-search-feature/scripts/scaffold_query_param.py --param <name> --kind <regex|glob|filter|flag>` for a checklist of the exact edit points (core signature, service signature, test names, default-regression test) tailored to the parameter kind. It writes nothing; it prints the checklist so you edit deliberately.

### Step 6: Test deterministically + gate
Add `tests/test_core.py` cases over a `tmp_path` fixture asserting: the new option returns exactly the right set; the error path (e.g. invalid regex) raises/maps clearly; and an unset option reproduces the baseline result. Run the `run-quality-gate` skill; confirm green and >=90% — never lower the threshold.

## Output Format
A core+service edit (typed param, stdlib, default-safe), `test_core.py` cases (positive, error, default-regression), and a green gate. Report the files changed, the test names, and the coverage figure.

## Examples

### Example 1
**Input:** Implement FFX-I01 regex match mode.
**Output:**
```
core.py: list_entries gains match_mode: Literal["substring","glob","regex"]="substring";
  regex compiled once via re.compile, glob via fnmatch.translate, substring keeps `in`.
service.py: match_mode threaded through.
test_core.py::test_regex_match, ::test_regex_invalid, ::test_default_substring_unchanged.
gate: PASS, coverage 93.1%.
```

## Scripts
- `scripts/scaffold_query_param.py` — prints the exact edit-point checklist for a new query parameter by kind (regex/glob/filter/flag). Run when: starting Step 5. Expected output: a numbered checklist (core signature, service signature, test names). Writes nothing. If missing: follow Steps 3-4 manually using the per-kind notes here.

## Self-Containment Index
This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format, example
- scripts/scaffold_query_param.py: edit-point checklist generator

External dependencies (must be in the environment): the repo `[dev,api]` extras; `pathspec` only if an ignore-file item authorizes it (declared in pyproject). Run from the repo root.

## Sources
- User requirement: an add-search-feature skill (extend core query + tests) for the FF-Explorer suite.
- Repo ground truth: ff_explorer/core.py (`list_entries`/filter), ff_explorer/api/service.py, tests/test_core.py, pyproject.toml; docs/BACKLOG.md FFX-I01/I02/I04/I09.
- references/claude.md §SKILL; templates/claude_skill.md.
