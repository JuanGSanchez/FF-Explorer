# Instruction: SDD Constitution (FF-Explorer)

## Principles Applied
Inherited: P1 (source grounding — phases read predecessor artifacts, not memory or prior context), P2 (determinism — gate conditions are explicit; no ambiguous phase transitions), P3 (systematicity — phase order and gate criteria are enumerated; each phase transition has a named decision point), P4 (consistency — same invariants and gates apply every pipeline run and every session), P6 (self-contained — all gates, invariants, and acceptance criteria stated here), P7 (reference hygiene — citations resolve to CLAUDE.md §Invariants and .claude/instructions/python-repo-conventions.md; hook names resolve to CLAUDE.md §Hooks), P8 (this block is the P8 expression for this asset), P9 Role Separation (this instruction governs the cross-phase pipeline contract; per-agent instructions govern individual agent execution; no agent owns the constitution), P10 Exit-Status Determinism (Rule 17 requires each agent to report PASS/FAIL for each gate criterion and return EXIT STATUS at phase completion, per CLAUDE.md Operating contract), P11 Programmatic Determinism (harness hooks enforce invariants 1, 2, 5, 6 deterministically at the tool-use level — plans must not propose workarounds; R18/P11 canonical definition: `repo-enhancer/orchestrator.md` CONVENTIONS, do not restate), P12 Maximal-Effort Completeness (all 7 CLAUDE.md invariants and all 6 pre-implement pipeline phase gates are covered; no invariant is partial), P13 Token Economy (rules cite invariant/rule IDs rather than restating them; terse). Engineering Disciplines (R17): canonical definition at `repo-enhancer/orchestrator.md` CONVENTIONS; prompt layer = numbered gated directives with positive/negative examples; context layer = each phase reads only its predecessor artifact, not the full pipeline history; harness layer = gate conditions block phase advancement until the predecessor artifact exists and is approved.

Custom:
- C1 — Pipeline Gate Integrity: every phase must verify its predecessor artifact exists on disk and is approved before proceeding; no phase runs without its input artifact; no phase skips its predecessor regardless of perceived urgency.

Scope: applies to every FF-Explorer coding agent (core-dev, gui-dev, access-dev, test-author, packaging-builder) and the active session/orchestrator when executing SDD pipeline phases (specify / clarify / plan / tasks / analyze / checklist / implement). The per-agent instructions own individual agent execution; this instruction owns the cross-phase contract that binds all of them.

<instructions>
  <context>
    FF-Explorer uses the SDD pipeline: specify → clarify → plan → tasks →
    analyze → checklist → implement. This instruction is the project constitution
    — the non-negotiable contract every phase, artifact, and agent must satisfy.
    Its purpose is to keep each pipeline artifact a trustworthy handoff to the
    next phase across sessions, agents, and context windows.

    Existing reality this constitution reflects:
    - Architecture: "one core, many faces" (CLAUDE.md §Architecture). One
      headless core (ff_explorer/core.py) powers a PySide6 GUI, a dual
      FastAPI+FastMCP access layer over one shared service, and a PyInstaller
      build. Every new capability must propagate through this architecture.
    - 7 invariants (CLAUDE.md §Invariants 1–7) and 10 coding rules
      (.claude/instructions/python-repo-conventions.md Rules 1–10) are in
      force throughout every phase.
    - Hooks enforce invariants mechanically (headless_core_guard.py,
      no_secrets_or_artifacts.py, destructive_op_safety_guard.py,
      tkinter_regression_guard.py). Plans must not propose workarounds.
  </context>

  <rules>
    <!-- Phase gate rules (C1: predecessor artifact must exist before each phase begins) -->

    1. Mandatory phase order. Execute phases in this order only:
       specify → clarify → plan → tasks → analyze → checklist → implement.
       No phase begins until its predecessor artifact exists on disk and is
       approved. Under no circumstances write code before spec.md, plan.md,
       and tasks.md exist and are cross-artifact-consistent.

    2. Specify gate. spec.md must state user-facing requirements (what and why)
       with explicit acceptance criteria per requirement. All requirements must
       be unambiguous when the clarify phase closes; none may remain open.

    3. Clarify gate. Every underspecified area in spec.md must be resolved
       through structured questioning before plan begins. Record every
       resolution in spec.md. A plan must not proceed while any requirement
       reads as ambiguous.

    4. Plan gate. plan.md must: (a) assign every new or modified module to its
       subsystem owner (core-dev / gui-dev / access-dev / test-author /
       packaging-builder); (b) state all data-model changes; (c) explicitly
       confirm that each of the 7 CLAUDE.md invariants holds under the plan.
       A plan that proposes importing a surface dependency into core.py
       (violates Invariant 1), weakening the destructive gate (Invariant 2),
       or lowering the coverage threshold (Invariant 3) is rejected without
       modification. Instead, redesign to preserve the invariant.

    5. Tasks gate. tasks.md must list dependency-ordered, single-owner work
       items. Each item must name: its owning agent, a done criterion
       (feature-level and verifiable), and a test criterion (the specific
       test(s) that must pass before the item is marked done).

    6. Analyze gate. Before implement begins, a cross-artifact consistency
       check must verify: (a) every spec requirement is covered by at least
       one plan component; (b) every plan component appears in at least one
       task; (c) no task introduces a latent invariant violation. All
       conflicts identified here must be resolved before implement begins;
       implement does not begin with open conflicts.

    7. Checklist gate. A project-specific quality checklist covering CLAUDE.md
       Invariants 1–7 and python-repo-conventions.md Rules 1–10 must be
       generated and run against the implementation. All items must pass, or
       be documented exceptions with a risk assessment, before the feature is
       declared done.

    <!-- Non-negotiable architecture invariants (carry through every phase) -->

    8. Headless core purity (CLAUDE.md Invariant 1; python-repo-conventions.md
       Rule 3). ff_explorer/core.py and all sibling headless modules
       (content_search.py, presets.py, dedupe.py, rename.py, index.py) must
       import no tkinter, PySide6, Qt*, fastapi, or fastmcp. Every plan and
       task that touches core.py must explicitly confirm this invariant holds
       after the change. The headless_core_guard.py hook (PreToolUse)
       enforces this mechanically; plans must not propose workarounds.

    9. Destructive-op gate (CLAUDE.md Invariant 2; python-repo-conventions.md
       Rule 5). Any remove/compress path requires dry_run=false AND
       confirm=true to mutate; rejects empty/whitespace name_seed
       (EmptySeedError); routes removes to the OS recycle bin via send2trash.
       Under no circumstances may a plan, task, or checklist item weaken this
       gate (flip defaults, bypass EmptySeedError, route to direct delete).
       The destructive_op_safety_guard.py hook (PreToolUse) enforces this.

    10. Coverage gate (CLAUDE.md Invariant 3). The gate is
        --cov-fail-under=90 over ff_explorer (gui/*, __init__.py, api/main.py
        omitted as configured in pyproject.toml). No plan or task may lower
        the threshold, widen the omit, or defer tests to a later task.
        Every implement task ships its tests in the same work item.

    11. One shared core (CLAUDE.md Invariant 5; python-repo-conventions.md
        Rule 4). New capabilities land in core.py + service.py so both REST
        and MCP inherit them. Under no circumstances may a plan fork logic
        between rest.py and mcp_server.py. Instead: add the capability in
        core, surface via service.py, let both transports inherit.

    12. No secrets / no build artifacts (CLAUDE.md Invariant 6;
        python-repo-conventions.md Rules 8–9). Under no circumstances do
        commits include credentials, tokens, keys, .env content, or build
        output (packaging/bin/, packaging/work/, dist/, *.egg-info,
        __pycache__). The no_secrets_or_artifacts.py hook (PreToolUse)
        enforces this.

    13. Branch policy (CLAUDE.md Invariant 7). All commits land on the
        enhancement branch (enhancement/*), never main or master.

    <!-- Cross-cutting standards (apply throughout the pipeline) -->

    14. Stdlib/pathlib first (python-repo-conventions.md Rule 1). Plans must
        not propose adding a dependency for something stdlib covers. Any new
        dependency must appear in pyproject.toml in the correct group/extra
        with a pinned range and a one-line rationale.

    15. Type all public APIs (python-repo-conventions.md Rule 2). Every new
        public function/method must carry parameter and return type hints.
        A task is not done if its public surface is untyped.

    16. PySide6 only for the GUI (python-repo-conventions.md Rule 10). No
        Tkinter reintroduction or .pyw revival. The tkinter_regression_guard.py
        hook (PreToolUse) enforces this.

    <!-- Acceptance gates: what "done" means -->

    17. A feature is "done" only when all of the following hold, reported as
        explicit PASS/FAIL per criterion in the agent's phase completion
        output, followed by an EXIT STATUS payload:
        (a) cross-artifact analysis (Phase 5) is complete and all conflicts
            resolved (analyze gate — PASS);
        (b) project checklist (Phase 6) is run and all items pass
            (checklist gate — PASS);
        (c) pytest --cov=ff_explorer --cov-fail-under=90 passes with
            QT_QPA_PLATFORM=offscreen set (coverage gate — PASS);
        (d) all 7 CLAUDE.md invariants hold — hooks verify invariants 1, 2,
            and 6 mechanically; agents verify 3–5 and 7 before reporting PASS;
        (e) all changes committed on the enhancement branch, never main/master
            (branch gate — PASS).
  </rules>

  <conditional_rules>
    - If a plan touches core.py, then tasks.md must include an explicit
      "headless purity re-check" task that verifies no surface import was
      added (Rule 8). This task is a prerequisite for every other task that
      modifies core.py.
    - If a feature introduces any new destructive operation, then tasks.md
      must include a "destructive gate contract test" task that verifies
      dry_run=false+confirm=true and EmptySeedError behavior before any
      other destructive-path task is marked done (Rule 9).
    - If the coverage gate drops below 90% at any point during implement,
      then halt the phase, report the gap, and escalate to the user; do not
      advance or merge (Rule 10).
    - If a task requires a new dependency, then the pyproject.toml entry
      (and packaging hidden-imports update, if needed) is part of the same
      task, not a follow-up task (Rule 14).
  </conditional_rules>

  <output_format>
    At each phase gate: report PASS or FAIL for each gate criterion (Rules
    2–7). At implement completion: report PASS or FAIL for each acceptance
    gate criterion (Rule 17a–e). End with the agent's EXIT STATUS payload.
  </output_format>

  <examples>
    <example>
      <input>Plan: add regex match mode to list_entries query.</input>
      <output>
        Accepted. plan.md assigns the change to core-dev (core.py, service.py)
        and test-author (test_core.py). Data model: match_mode:
        Literal["substring","glob","regex"] typed param on list_entries.
        Invariant check: (1) core.py gains no surface import — PASS; (2) no
        destructive gate touched — PASS; (3) coverage stays ≥90% with new
        tests — PASS; (5) threaded through service.py so both transports
        inherit, no fork — PASS; others unaffected — PASS. tasks.md entry:
        owner=core-dev, done="list_entries returns regex-filtered results,"
        test="test_core.py passes for valid-regex, glob, substring, and
        invalid-regex inputs." Headless purity re-check task included
        (conditional rule 1).
      </output>
    </example>
    <example>
      <input>Plan: add regex by putting re.compile in the rest.py route handler
      to keep it isolated from core.</input>
      <output>
        Rejected (Rule 11 — one shared core). Logic that belongs in core must
        not live in a transport route. Instead: add re.compile to
        list_entries in core.py, thread match_mode through service.py, and
        let rest.py and mcp_server.py inherit it with no duplication.
      </output>
    </example>
  </examples>
</instructions>

<!--
  SOURCES:
  - User requirement: SDD constitution instruction grounding pipeline gates and
    invariants for FF-Explorer (Group E, item 15).
  - CLAUDE.md §Invariants 1–7, §Architecture, §Gate & build commands,
    §Hooks: existing repo reality (invariants, one-core/many-faces
    architecture, coverage gate, branch policy, hook roster).
  - .claude/instructions/python-repo-conventions.md Rules 1–10: coding
    standards carried through every pipeline phase.
  - references/software-development.md §2: SDD phase definitions
    (specify/clarify/plan/tasks/analyze/checklist/implement) and the
    gate-before-proceed property.
  - templates/claude_instruction.md v2026-05-10: structural template.
  - repo-enhancer/orchestrator.md CONVENTIONS R17 (Engineering Disciplines)
    and R18/P11 (Programmatic Determinism): canonical definitions (cited,
    not restated).
-->
