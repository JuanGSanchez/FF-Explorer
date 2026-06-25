---
name: tasks
description: >
  Derives an ordered, dependency-aware task list from a technical implementation
  plan — each task carrying an ID, title, dependency list, owner agent, and
  acceptance criterion. Produces tasks.md. Use this skill after `plan` produces
  plan.md, when the user says "break this into tasks", "task list", "what do we
  do first", or when the analyze stage reports missing task coverage.
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
      name: Dependency-Ordered Tasks
      requires: no task in tasks.md may reference an artifact or capability that
        is produced by a later task. The ordering must be a valid topological sort
        of the dependency graph. A dependency cycle is a planning error and is
        surfaced to the user before tasks.md is written.
      rationale: Out-of-order tasks cause implementation failures when an agent
        attempts work whose prerequisite has not yet been delivered.
---

# Tasks

Derives an ordered, dependency-aware task list from plan.md so each task can be executed sequentially by the owning agent.

## Workflow

### Step 1: Gate — plan.md must exist
Read `.claude/sdd/plan.md`. If it does not exist, STOP: "Run the `plan` skill first."

### Step 2: Decompose into atomic tasks
For each component change in plan.md, derive one or more atomic tasks. A task is atomic if: it produces a single verifiable artifact or change; it can be assigned to one agent; and its done/not-done state is unambiguous.

Assign each task:
- `id` — `T<NNN>` (zero-padded three digits, sequential).
- `title` — imperative verb phrase, 8 words or fewer.
- `depends_on` — list of T-IDs whose output this task requires; `—` if none.
- `owner` — one of: `core-dev`, `gui-dev`, `access-dev`, `test-author`, `docs-writer`.
- `acceptance` — one-line done criterion, matching the spec's acceptance criteria where applicable.
- `status` — `TODO` (all tasks start here; only the owning agent or user may update).

### Step 3: Validate ordering (C1)
Build the dependency graph and check for cycles. If a cycle is detected, STOP: list the cycle task IDs and ask the user to resolve the dependency conflict. Do not write tasks.md until the graph is acyclic.

Verify that test tasks (owner: `test-author`) always depend on the implementation tasks whose output they verify.

### Step 4: Write .claude/sdd/tasks.md
Create or overwrite `.claude/sdd/tasks.md` using the output format below. List tasks in valid execution order (all dependencies appear above their dependents).

## Output Format

`.claude/sdd/tasks.md`:

```
# Task List: <Feature Name>
Plan: .claude/sdd/plan.md
Date: <YYYY-MM-DD>

## Tasks
| ID   | Title         | Depends on | Owner       | Status | Acceptance       |
|------|---------------|------------|-------------|--------|------------------|
| T001 | …             | —          | core-dev    | TODO   | …                |
| T002 | …             | T001       | test-author | TODO   | …                |
...
```

Summary line emitted after write: `tasks.md written — <N> tasks, topological order validated.`

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format

External dependencies:
- `.claude/sdd/plan.md` — input artifact.
- `.claude/sdd/spec.md` — consulted for acceptance criteria wording. If missing: derive acceptance from the plan component descriptions.

## Sources
- User requirement: SDD pipeline stage-4 skill (tasks) for FF-Explorer Group E.
- SDD pipeline: asset-metaprompting `references/software-development.md §2`.
- `references/claude.md §SKILL`; `templates/claude_skill.md`.
- `D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md` CONVENTIONS (R17/R18).
