---
name: checklist
description: >
  Emits the quality/acceptance checklist gate for a completed feature — deriving
  checklist items from the spec's acceptance criteria, verifying task completion,
  and delegating all gate execution to the existing `run-quality-gate` skill.
  Use this skill after implementation is complete, when the user says "run the
  checklist", "final check", "acceptance gate", or "is this feature done". Never
  reimplements the pytest/coverage/invariant logic owned by `run-quality-gate`.
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
    - "R17 Engineering Disciplines; R18=P11 Programmatic Determinism: D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md CONVENTIONS"
  custom:
    - id: C1
      name: Gate Delegation
      requires: this skill must not run pytest, grep invariants, or measure
        coverage directly. All gate execution is delegated to the `run-quality-gate`
        skill. A checklist verdict of PASS requires `run-quality-gate` to report
        GATE: PASS. A PASS verdict is not emitted if the gate was skipped or
        returned GATE: FAIL.
      rationale: Single-point gate ownership (P4) — `run-quality-gate` is
        FF-Explorer's authoritative gate; a parallel gate risks drift and
        undermines the invariant guarantee.
---

# Checklist

Emits the acceptance checklist for a completed feature and delegates quality-gate execution to `run-quality-gate`.

## Workflow

### Step 1: Gate — artifacts and analyze output must exist
Verify `.claude/sdd/spec.md` (Status: CLARIFIED) and `.claude/sdd/tasks.md` exist, and that an `analyze` report has been produced (in context or as a file). If any is missing, STOP: "Run `analyze` first."

### Step 2: Derive acceptance checklist items
From `.claude/sdd/spec.md` Acceptance Criteria section, generate one checklist item per criterion:

```
[ ] (FR-N/AC-M) <criterion text>
```

If `.claude/instructions/sdd-constitution.md` is available (load it), also emit one item per constitution-defined gate. If the file is missing, include the default item:

```
[ ] Quality gate: run-quality-gate reports GATE: PASS
```

### Step 3: Verify task completion
Read `.claude/sdd/tasks.md`. For each task, check its Status field:
- `DONE` — satisfied.
- `TODO` or `IN PROGRESS` — checklist item flagged as incomplete.

Add one checklist item per task:
```
[ ] T001: <title> — <DONE|TODO|IN PROGRESS>
```

A checklist with any non-DONE task cannot yield a PASS verdict.

### Step 4: Delegate gate execution (C1)
Invoke the `run-quality-gate` skill. Record its full output verbatim under the "Quality Gate" heading. Do not filter, reinterpret, or re-run it.

If `run-quality-gate` is unavailable, record:
```
Quality Gate: BLOCKED — run-quality-gate skill not found; verdict cannot be determined.
```
and halt with BLOCKED status.

### Step 5: Emit checklist verdict
- `CHECKLIST: PASS` — all acceptance criteria items checked, all tasks DONE, run-quality-gate reports `GATE: PASS`.
- `CHECKLIST: FAIL` — otherwise; list each failing item.

## Output Format

```
CHECKLIST: <Feature Name>
Verdict: PASS | FAIL | BLOCKED
Date: <YYYY-MM-DD>

## Acceptance Criteria
- [x/ ] (FR-1/AC-1) <criterion text>
- [x/ ] (FR-1/AC-2) <criterion text>
...

## Task Completion
- [x/ ] T001: <title> — DONE | TODO | IN PROGRESS
...

## Quality Gate
<run-quality-gate output verbatim>

## Constitution Gates
- [x/ ] <gate item from sdd-constitution.md, or default gate item>

Verdict: CHECKLIST: PASS | FAIL | BLOCKED
Failing items: <list or "none">
```

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format

External dependencies:
- `.claude/sdd/spec.md` — acceptance criteria source; must exist.
- `.claude/sdd/tasks.md` — task completion status; must exist.
- `run-quality-gate` skill (`.claude/skills/run-quality-gate/SKILL.md`) — invoked in Step 4; must be present for a PASS verdict. If missing: halt with BLOCKED.
- `.claude/instructions/sdd-constitution.md` — constitution-level gate items; loaded in Step 2 if available. If missing: use the default quality-gate item only; note gap.

## Sources
- User requirement: SDD pipeline stage-6 skill (checklist) for FF-Explorer Group E.
- SDD pipeline: asset-metaprompting `references/software-development.md §2`.
- `references/claude.md §SKILL`; `templates/claude_skill.md`.
- `D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md` CONVENTIONS (R17/R18).
