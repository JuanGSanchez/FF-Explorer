---
name: clarify
description: >
  Surfaces and resolves ambiguities, unknowns, and under-specified areas in an
  existing feature spec before planning begins — structured question-and-answer
  de-risking. Records all answers into spec.md and sets its status to CLARIFIED.
  Use this skill after `specify` produces a DRAFT spec, when the user says
  "clarify the spec", "resolve unknowns", "answer the open questions", or when
  the plan stage reports ambiguities it cannot resolve.
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
      name: Clarify-Before-Plan Gate
      requires: spec.md status must be CLARIFIED before the plan stage may begin.
        This skill is the only actor that sets that status. If any question remains
        unanswered, status stays DRAFT and plan is blocked.
      rationale: An ambiguous spec produces an unconstrained plan; resolving all
        unknowns before planning prevents rework that spans multiple artifacts.
---

# Clarify

De-risks a feature spec by surfacing and answering all ambiguities before the plan stage begins.

## Workflow

### Step 1: Gate — spec.md must exist and be DRAFT
Read `.claude/sdd/spec.md`. If it does not exist, STOP: "Run the `specify` skill first." If Status is already CLARIFIED, report: "Spec is already CLARIFIED — no action needed unless you want to add further clarifications."

### Step 2: Identify unknowns
For each functional requirement and acceptance criterion in spec.md, ask: Is the behaviour fully defined? Are edge cases named? Are there conflicting interpretations? Are dependencies on external state undeclared? Produce a numbered list of questions (Q1, Q2, …).

Consult these read-only sources before asking the user (do not modify them):
- `docs/BACKLOG.md` — may answer constraints or acceptance wording.
- `.claude/instructions/sdd-constitution.md` — may resolve scope questions.
If a question is answerable from docs, record the answer directly without escalating to the user.

### Step 3: Ask and record remaining questions
Present all unanswered questions to the user in one batch. Wait for all answers. Do not proceed if any answer is missing — ask again for the remainder.

Record each pair: `Q<n>: <question>` / `A<n>: <answer>`.

### Step 4: Update spec.md
Append a `## Clarifications` section to `.claude/sdd/spec.md`:

```
## Clarifications
| #  | Question | Answer |
|----|----------|--------|
| Q1 | …        | …      |
```

Update the Status field from DRAFT to CLARIFIED. Do not alter Functional Requirements or Acceptance Criteria text — only append the Clarifications section.

Summary line emitted after update: `spec.md updated — Status: CLARIFIED; <N> questions resolved.`

## Output Format

Updated `.claude/sdd/spec.md` with:
- `Status: CLARIFIED`
- `## Clarifications` table populated with all Q/A pairs

Plus one summary line (inline): `N questions resolved; spec status → CLARIFIED.`

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format

External dependencies:
- `.claude/sdd/spec.md` — input artifact (must exist; produced by `specify`).
- `docs/BACKLOG.md` — consulted for constraint/acceptance detail. If missing: answer from user only.
- `.claude/instructions/sdd-constitution.md` — consulted for scope resolution. If missing: note the dependency gap in the Clarifications table and ask the user for the relevant rule.

## Sources
- User requirement: SDD pipeline stage-2 skill (clarify) for FF-Explorer Group E.
- SDD pipeline: asset-metaprompting `references/software-development.md §2`.
- `references/claude.md §SKILL`; `templates/claude_skill.md`.
- `D:/Documentos/Recursos/Recursos IA/Repo Enhancer/repo-enhancer/orchestrator.md` CONVENTIONS (R17/R18).
