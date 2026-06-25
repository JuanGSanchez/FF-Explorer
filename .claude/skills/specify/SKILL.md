---
name: specify
description: >
  Turns a feature request (backlog item or user-stated goal) into a structured
  feature specification — the what and why: user story, functional requirements,
  acceptance criteria, and explicit out-of-scope boundaries. No implementation
  detail. Use this skill when starting work on a new feature, when the user says
  "write a spec", "spec out this feature", "what are the requirements for", or
  when the plan stage reports a missing or incomplete spec.
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
      name: Spec-Only Boundary
      requires: spec.md must contain no architecture decisions, no stack choices,
        and no implementation detail — only user-visible behaviour and acceptance
        criteria. Any implementation mention is removed or rephrased before the
        artifact is written.
      rationale: Mixing what/why with how contaminates the spec and causes the plan
        stage to inherit assumptions that belong to the author, not the feature.
---

# Specify

Produces a structured feature specification (what + why) from a feature request, with no implementation detail.

## Workflow

### Step 1: Gate — confirm input
A feature request must be present: a backlog item ID (grep `docs/BACKLOG.md` for the ID), a user-stated requirement, or an explicit feature description. If none is present, STOP and ask: "Provide the feature request or backlog item ID to specify."

### Step 2: Extract what and why
From the input derive:
- **Feature name** — a short noun phrase (6 words or fewer).
- **User story** — "As a [role], I want [capability] so that [value]."
- **Functional requirements** — numbered list (FR-1, FR-2, …). Each requirement is one verifiable user-visible behaviour. No stack words (no "Python", "PySide6", "FastAPI"), no method names.
- **Acceptance criteria** — each requirement maps to one or more testable pass/fail statements (Given/When/Then or equivalent).
- **Out of scope** — explicit list of related capabilities this spec does not cover.

### Step 3: Validate spec-only boundary (C1)
Scan the draft for architecture choices, class names, library names, database schemas, or API shapes. If found, rephrase in behaviour terms or move to a non-binding "Implementation Notes" section clearly marked as non-normative. Do not remove rationale; rephrase.

### Step 4: Write .claude/sdd/spec.md
Create or overwrite `.claude/sdd/spec.md` with the structured artifact using the output format below. Do not commit — the user reviews before advancing to `clarify`.

## Output Format

`.claude/sdd/spec.md`:

```
# Feature Spec: <Feature Name>
Status: DRAFT
Date: <YYYY-MM-DD>

## User Story
As a <role>, I want <capability> so that <value>.

## Functional Requirements
1. (FR-1) <requirement>
2. (FR-2) <requirement>
...

## Acceptance Criteria
| Req  | Criterion                          |
|------|------------------------------------|
| FR-1 | Given … When … Then …             |
...

## Out of Scope
- <item>
```

Summary line emitted after write: `spec.md written — Status: DRAFT; <N> requirements, <M> acceptance criteria.`

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format

External dependencies:
- `docs/BACKLOG.md` — feature backlog; source for backlog-item inputs. If missing: accept user-stated feature description directly.
- `.claude/instructions/sdd-constitution.md` — governing project principles; consult for scope guidance. If missing: apply C1 boundary only and note the gap in spec.md.

## Sources
- User requirement: SDD pipeline stage-1 skill (specify) for FF-Explorer Group E.
- SDD pipeline: asset-metaprompting `references/software-development.md §2`.
- `references/claude.md §SKILL`; `templates/claude_skill.md`.
- `D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md` CONVENTIONS (R17/R18).
