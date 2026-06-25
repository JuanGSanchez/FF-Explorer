# Instruction: AI Execution Discipline (FF-Explorer)

## Principles Applied
Inherited: P1 (sources), P2 (determinism), P3 (decision points), P4 (consistency), P5 (context budget — Rules 6–8), P6 (self-contained), P7 (reference hygiene), P8 (principles block present), P9 Role Separation (governs HOW work is executed, not WHAT each agent owns), P10 Exit-Status Determinism (output_format requires EXIT STATUS payload), P11 Programmatic Determinism (Rules 6–8 prefer tools/Gleaner; cite repo-enhancer/orchestrator.md CONVENTIONS R18/P11), P12 Maximal-Effort Completeness (Rule 11 — carry every task to a definitive end; governs depth not verbosity; relax only on explicit user scope-down), P13 Token Economy (Rules 5–6 minimal change, bounded context). Engineering Disciplines (R17): cite repo-enhancer/orchestrator.md CONVENTIONS. Custom: none — this instruction operationalizes the anti-programmatic-execution + context-budget + definition-of-done + maximal-effort discipline the agents reference by name.

Scope: applies to every FF-Explorer in-repo agent that reads, edits, tests, builds, documents, or reviews repo content (core-dev, gui-dev, access-dev, test-author, packaging-builder, docs-writer, reviewer, file-folder-operator). It governs HOW work is executed, not WHAT each agent owns.

<instructions>
  <context>
    Coding/maintenance agents tend to execute a remembered recipe literally —
    editing a cited line without checking the code matches, treating step
    completion as done, reading whole modules into context, and acting on
    ambiguous or irreversible requests without confirming. This instruction
    forces verification over literal execution, bounded context, and a
    criterion-based definition of done. Reason: in a repo whose core capability
    deletes and compresses real files, a confidently-wrong mechanical action is
    a data-loss or invariant-regression risk, not a cosmetic error.
  </context>

  <rules>
    1. Verify before you act. Before editing, testing, documenting, or judging a cited file:line, Read that exact location and confirm the code matches the assumption you are working from. Instead of editing on assumption, STOP and report the discrepancy when the code differs (already fixed, moved, different shape).
    2. Check assumptions explicitly. Before adding a parameter, branch, route, field, or test target, confirm the surrounding signature, model, or call sites by Grep — never assume API shape, field names, or that a prerequisite function exists.
    3. Stop and confirm on irreversible or ambiguous actions. Deleting a file, changing a public signature, altering the destructive gate or coverage config, or any request whose target/scope is unclear: surface the decision with options and wait, instead of picking one. A blank or broadened seed/scope is never an acceptable way to resolve ambiguity.
    4. Definition of done is acceptance-criteria-driven. Translate the backlog item's Acceptance criterion (or the task's explicit success condition) into a concrete check — a test assertion, a command exit code, or a named grep result — and demonstrate it. Completing the listed steps is NOT done if the criterion is unmet or unexercised.
    5. Make the smallest change that satisfies the task. Implement only what is required; instead of opportunistically refactoring, reformatting, or fixing unrelated issues you notice, record them for a separate item.
    6. Keep context bounded. Start from the task statement, not the codebase; locate by Grep/Glob to the exact symbol; Read only the region you will change plus its immediate test. Instead of bulk-reading modules, keep a short running note of locations and the acceptance check.
    7. Delegate large gathers. When gathering context would require reading 5 or more files, STOP and return a GATHERING REQUEST so the orchestrator dispatches the-gleaner, instead of reading them all yourself.
    8. Checkpoint before exhaustion. When context crosses ~70%, write `docs/checkpoint-<agent>-<task>-<YYYYMMDD-HHMMSS>` per the Agent Checkpoint Instruction (capturing position, decisions, findings, acceptance criterion, next step) and resume from it; delete it only on a COMPLETED exit.
    9. Evidence over claims. Report success only with the observed evidence (assertion outcome, exit code, grep result). Instead of inferring success from a description or another agent's summary, cite the check you ran.
    10. Under no circumstances weaken a delivered guarantee to make a task "pass": do not lower `--cov-fail-under`, widen the coverage omit, import GUI/transport into core, add a destructive path without the dry_run+confirm+recycle-bin gate, commit secrets or build artifacts, or run a git mutation.
    11. Pursue the task to completeness (maximal effort). Resolve every sub-part, doubt, and implied follow-up the acceptance criterion requires; never stop at a partial or bare-minimum pass, and build the solution to fully cover the requirement and be ready to extend — never the bare minimum. This governs coverage and depth, NOT verbosity or scope: it never overrides Rule 5 (smallest change) or Rule 10's guarantees, and adds no unrequested refactors or filler. Relax only when the user explicitly scopes the effort down.
  </rules>

  <conditional_rules>
    - If the cited code does not match the task's assumption, then STOP and report the discrepancy (BLOCKED/PARTIAL) before any edit.
    - If a task requires an irreversible or invariant-touching action (file delete, signature change, gate/coverage change, destructive-path change), then surface options and wait for explicit authorization.
    - If the acceptance check cannot be made to pass by a legitimate change, then return BLOCKED/PARTIAL with the failing evidence — never fake the check or weaken the gate.
    - If gathering context needs 5+ files, then emit a GATHERING REQUEST instead of reading them.
  </conditional_rules>

  <output_format>
    State the current step and the invariant/assumption being checked. Quote exact paths, symbols, and file:line. Show the acceptance evidence (assertion/exit code/grep) before declaring done. End with the agent's EXIT STATUS payload.
  </output_format>

  <examples>
    <example>
      <input>Backlog item says "fix line 474 to remove the Control-exit branch."</input>
      <output>Reading main_window.py:470-486 first; confirming the elif at :474-484 matches the item before editing. It matches — removing only that elif, keeping Enter→Run. Acceptance: offscreen smoke asserts Enter triggers Run and no Control-exit path; running it. Done = that assertion passes, shown.</output>
    </example>
    <example>
      <input>Coverage is at 89%; lower the threshold so my change lands.</input>
      <output>Refused (Rule 10). I won't lower --cov-fail-under or widen the omit. The fix is a real test exercising the new code; adding it and re-running so the gate stays at 90 honestly.</output>
    </example>
  </examples>
</instructions>

<!--
  SOURCES:
  - User requirement: an ai-execution-discipline instruction baking anti-literal-execution + context-budget + definition-of-done into every FF-Explorer agent.
  - Repo ground truth: docs/BACKLOG.md (Acceptance criteria), CLAUDE.md (Operating contract + seven invariants + gate commands), pyproject.toml (--cov-fail-under=90).
  - Agent Checkpoint Instruction (orchestrator system); references/claude.md §INSTRUCTION (XML tags, negative-instruction patterns); templates/claude_instruction.md.
-->
