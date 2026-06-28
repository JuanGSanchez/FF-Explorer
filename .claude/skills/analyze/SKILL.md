---
name: analyze
description: >
  Performs a cross-artifact consistency and coverage check — verifying that spec
  requirements are addressed in the plan, that every plan component has tasks,
  and that no acceptance criterion is left unverifiable. Where the check overlaps
  quality-gate execution, delegates to the existing `run-quality-gate` skill and
  does not reimplement gate logic. Use this skill after tasks.md exists, when the
  user says "analyze the artifacts", "cross-check", "consistency check", or before
  moving to the checklist stage.
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
      name: No Gate Reimplementation
      requires: this skill must not reimplement the pytest/coverage/invariant logic
        owned by `run-quality-gate`. When gate execution is needed, invoke the
        `run-quality-gate` skill and consume its PASS/FAIL output verbatim. Any
        gate failure is reported as a finding; it is never silently rerun or
        reinterpreted.
      rationale: Duplicating gate logic creates divergence (P4); `run-quality-gate`
        is the single authoritative gate for FF-Explorer.
---

# Analyze

Cross-checks spec ↔ plan ↔ tasks for consistency and coverage, then delegates gate execution to `run-quality-gate`.

## Workflow

### Step 1: Gate — all three artifacts must exist
Read `.claude/sdd/spec.md` (must be CLARIFIED), `.claude/sdd/plan.md`, and `.claude/sdd/tasks.md`. If any is missing, STOP and name the missing artifact: "Run `<specify|clarify|plan|tasks>` first."

### Step 2: Spec → Plan coverage check
For each functional requirement (FR-N) in spec.md: verify at least one component in plan.md addresses it. Record:
- `COVERED` — requirement maps to a named plan component.
- `GAP` — no plan component covers this requirement.

### Step 3: Plan → Tasks coverage check
For each component in plan.md: verify at least one task in tasks.md targets it. Record:
- `COVERED` — component has at least one task.
- `GAP` — component has no task.

### Step 4: Acceptance criteria traceability
For each acceptance criterion in spec.md: verify a task with a matching acceptance statement exists and its owner is `test-author` or an agent whose work triggers verification. Flag uncovered criteria as GAP.

### Step 5: Delegate gate execution (C1)
If implementation artifacts exist (any task with Status DONE and corresponding source files present), invoke the `run-quality-gate` skill. Record its output verbatim under the "Gate" heading of the analysis report. Do not run pytest or grep independently.

If no implementation artifacts exist yet: record `Gate execution: DEFERRED — no implementation artifacts yet.`

### Step 6: Emit analysis report
Produce the analysis report in the output format below. Status is `GAPS FOUND` if any GAP is recorded or the gate returned FAIL; otherwise `CLEAN`.

## Output Format

Analysis report (inline unless user requests a file):

```
ANALYSIS: <Feature Name>
Status: CLEAN | GAPS FOUND
Date: <YYYY-MM-DD>

Spec→Plan coverage:
  FR-1: COVERED (plan component: <name>)
  FR-2: GAP — no plan component addresses this requirement

Plan→Tasks coverage:
  <component>: COVERED (T001, T002)
  <component>: GAP — no tasks

Acceptance traceability:
  FR-1/AC-1: COVERED (T002, test-author)
  FR-2/AC-1: GAP — no task with matching acceptance statement

Gate:
  <run-quality-gate output verbatim, or DEFERRED>

Summary: <n> gaps; gate: PASS | FAIL | DEFERRED
```

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format

External dependencies:
- `.claude/sdd/spec.md`, `.claude/sdd/plan.md`, `.claude/sdd/tasks.md` — input artifacts; all must exist.
- `run-quality-gate` skill (`.claude/skills/run-quality-gate/SKILL.md`) — invoked in Step 5 for gate execution. If missing: record `Gate: BLOCKED — run-quality-gate skill not found`; report artifact gaps only.
- `.claude/instructions/sdd-constitution.md` — consulted for constitution-level compliance gaps if available. If missing: skip constitution audit and note the gap in the report.

## Sources
- User requirement: SDD pipeline stage-5 skill (analyze) for FF-Explorer Group E.
- SDD pipeline: asset-metaprompting `references/software-development.md §2`.
- `references/claude.md §SKILL`; `templates/claude_skill.md`.
- `D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md` CONVENTIONS (R17/R18).
