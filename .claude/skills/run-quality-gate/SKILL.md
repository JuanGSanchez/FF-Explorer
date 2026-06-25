---
name: run-quality-gate
description: >
  Runs FF-Explorer's quality gate — pytest with coverage (>=90% core) plus a
  grep-based invariant scan (core has no GUI/transport imports; destructive gate
  intact; no lowered threshold/widened omit; no Tkinter; no committed build
  artifacts) — and reports a single PASS/FAIL. Use this skill when an agent needs
  to verify a change before declaring done or before review, when the user says
  "run the gate", "check coverage", "verify the invariants hold", or after any
  core/service/api edit. Never weakens the gate to pass.
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
    - "Execution backend: this skill is invoked by .claude/skills/analyze (cross-artifact consistency) and .claude/skills/checklist (acceptance gate)."
  custom:
    - id: C1
      name: Gate Integrity
      requires: the gate is run as configured (--cov-fail-under=90); the skill
        never edits pyproject.toml, lowers the threshold, or widens the omit to
        produce a PASS.
      rationale: A gate that can be softened to pass is not a gate.
---

# Run Quality Gate

Runs the pytest+coverage gate and an invariant grep scan for FF-Explorer, returning one PASS/FAIL verdict with the failing details.

## Workflow

### Step 1: Confirm environment
Ensure dev+api extras are installed: `pip install -e ".[dev,api]"` (idempotent). If install fails, STOP and report BLOCKED with the error — do not skip the gate.

### Step 2: Run pytest + coverage
Run `python .claude/skills/run-quality-gate/scripts/run_gate.py` from the repo root. The script runs `pytest` (addopts inject `--cov=ff_explorer --cov-fail-under=90 --cov-report=term-missing`) and parses the result. Do NOT pass `--cov-fail-under` overrides or `-k` filters that would skip the full gate.

### Step 3: Run the invariant grep scan
The same script runs the invariant scan: (a) `core.py` imports no `tkinter`/`PySide6`/`fastapi`/`fastmcp`; (b) `pyproject.toml` still has `--cov-fail-under=90` and the omit list is unchanged in shape (no new entries beyond the three known); (c) no `FF_UI.pyw` reference reintroduced; (d) no build artifacts staged (`packaging/work/`, `packaging/bin/`, `dist/`). It does a best-effort static check that destructive request models keep `name_seed` min_length and the dry_run/confirm fields.

### Step 4: Report the verdict
Emit `GATE: PASS` only when pytest passes AND coverage >=90% AND every invariant check passes. Otherwise `GATE: FAIL` with each failing item (test failures, coverage figure, or the invariant + file:line). Never edit config to flip a FAIL to PASS — report it for the owning dev agent.

## Output Format
First line `GATE: PASS` or `GATE: FAIL`. Then: coverage percentage; failed tests (if any); invariant findings (each: check · PASS/FAIL · evidence). No prose beyond this.

## Examples

### Example 1
**Input:** Agent finished a core edit and runs the gate.
**Output:**
```
GATE: FAIL
coverage: 89.2% (<90)
failed_tests: none
invariants: core-purity PASS; cov-threshold PASS (=90); tkinter-absent PASS; artifacts-clean PASS
note: coverage below 90 — add tests for the new branch (test-author); do not lower the threshold.
```

### Example 2
**Input:** "Verify the invariants before review."
**Output:**
```
GATE: PASS
coverage: 93.5%
failed_tests: none
invariants: core-purity PASS; cov-threshold PASS; tkinter-absent PASS; artifacts-clean PASS; destructive-gate PASS
```

## Scripts
- `scripts/run_gate.py` — runs pytest+coverage and the invariant grep scan; prints the PASS/FAIL block. Run when: verifying a change. Expected output: the verdict block above; exit 0 on PASS, non-zero on FAIL. If missing: run `pytest` manually and perform the Step-3 greps by hand, reporting the same block.

## Self-Containment Index
This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format, examples
- scripts/run_gate.py: pytest+coverage + invariant scan runner

External dependencies (must be in the environment): the repo's `[dev,api]` extras (pytest, pytest-cov) installed; run from the FF-Explorer repo root.

## Sources
- User requirement: a deterministic run-quality-gate skill (pytest+coverage+invariant grep) for the FF-Explorer self-maintenance suite.
- Repo ground truth: pyproject.toml (`--cov-fail-under=90`, omit list), ff_explorer/core.py (purity + destructive gate), `CLAUDE.md` (invariants).
- references/claude.md §SKILL; templates/claude_skill.md; the `testing` skill (coverage runner pattern).
