---
name: plan
description: >
  Produces the technical implementation plan (the how) from a clarified feature
  spec — identifying affected components, defining the implementation strategy,
  and enforcing the UI-independent-core architecture and sdd-constitution.md
  gates. Use this skill after `clarify` sets the spec to CLARIFIED, when the
  user says "write the plan", "plan this feature", "how do we implement this".
  Delegates all coding to core-dev / gui-dev / access-dev agents; writes no code.
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
      name: UI-Independent Core
      requires: the plan must not introduce GUI or transport logic into
        ff_explorer/core.py or ff_explorer/api/service.py. Any GUI change is
        scoped to ff_explorer/ui/; any transport wiring to ff_explorer/api/.
        A plan component that violates layer separation is flagged and must be
        redesigned before tasks are derived.
      rationale: Layer coupling in FF-Explorer has historically fragmented the
        test surface and blocked headless use; strict separation is non-negotiable.
---

# Plan

Derives the technical implementation plan (the how) from a clarified spec, enforcing UI-independent-core architecture.

## Workflow

### Step 1: Gate — spec.md must be CLARIFIED
Read `.claude/sdd/spec.md`. If it does not exist or Status is not CLARIFIED, STOP: "Run `specify` then `clarify` first."

### Step 2: Load governing instructions (just-in-time)
Read `.claude/instructions/sdd-constitution.md` for project-wide gates (coverage threshold, layer rules, destructive-op safety model). If the feature touches the GUI layer, also read `.claude/instructions/pyside6-best-practices.md`. Load only these two; do not load other instructions.

If either file is missing, note the gap in plan.md and apply C1 and the default coverage gate (>=90%) as fallback.

### Step 3: Identify affected components
For each functional requirement in spec.md, determine which layer(s) change:
- **core** (`ff_explorer/core.py`) — query engine, destructive ops, file I/O.
- **service** (`ff_explorer/api/service.py`) — shared transport-independent wrapper.
- **api** (`ff_explorer/api/rest.py`, `ff_explorer/api/mcp_server.py`) — transport wiring.
- **gui** (`ff_explorer/ui/`) — PySide6 GUI components.
- **tests** (`tests/`) — always affected.

Verify C1: no core or service component change introduces a GUI or transport import.

### Step 4: Define implementation strategy
For each affected component describe:
- What changes (function/class/field additions or modifications).
- New data contracts (typed parameters, Pydantic models) if any.
- How default behaviour is preserved for callers that do not pass the new option.
- Owner agent: `core-dev`, `gui-dev`, `access-dev`, `test-author`, or `docs-writer`.

Keep descriptions at "what changes and why" — no code. Cite existing identifiers (e.g. `list_entries`) only if they exist in the repo (R15).

### Step 5: Write .claude/sdd/plan.md
Create or overwrite `.claude/sdd/plan.md` using the output format below.

## Output Format

`.claude/sdd/plan.md`:

```
# Implementation Plan: <Feature Name>
Spec: .claude/sdd/spec.md (CLARIFIED)
Date: <YYYY-MM-DD>

## Affected Components
| Component | Change summary | Owner agent |
|-----------|---------------|-------------|
| core.py   | …             | core-dev    |
...

## Implementation Strategy
### <Component>
<What changes, data contracts, default-preservation approach>

## Architecture Gate Checks
- UI-independent core (C1): PASS | FAIL — <reason if FAIL>
- Destructive-op safety: PASS | FAIL — <reason> (only if destructive ops touched)
- Coverage gate feasibility: <expected coverage delta>

## Component Sequencing
<Which component must be complete before which>
```

Summary line emitted after write: `plan.md written — <N> components, all gate checks: PASS|FAIL.`

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format

External dependencies:
- `.claude/sdd/spec.md` — input artifact (Status: CLARIFIED).
- `.claude/instructions/sdd-constitution.md` — project-wide gates and layer rules; loaded in Step 2. If missing: apply C1 and default coverage gate; note gap.
- `.claude/instructions/pyside6-best-practices.md` — GUI-layer guidance; load only if a requirement touches ff_explorer/ui/. If missing: apply conservative PySide6 discipline (no logic in view classes; signals only); note gap.
- `.claude/agents/core-dev.md`, `gui-dev.md`, `access-dev.md` — referenced for owner assignment. If any is missing: assign by layer convention (core-dev for core/service; gui-dev for ui/; access-dev for api/).

## Sources
- User requirement: SDD pipeline stage-3 skill (plan) for FF-Explorer Group E.
- SDD pipeline: asset-metaprompting `references/software-development.md §2`.
- FF-Explorer layer conventions: `ff_explorer/` directory structure, CLAUDE.md.
- `references/claude.md §SKILL`; `templates/claude_skill.md`.
- `D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md` CONVENTIONS (R17/R18).
