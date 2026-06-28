# FF-Explorer — repository guide for Claude

Recursive file/folder explorer: lists folders/files whose name contains a substring "name seed"
under a root, and can Save a listing, Remove (recycle-bin), or Compress (zip then delete) the
matches. One pure headless core powers a PySide6 GUI, a dual FastAPI (REST) + FastMCP access layer,
and a PyInstaller build. This file is auto-loaded into every Claude Code session here, so it is the
always-loaded ground truth and the **Operating contract** below is in force from the first turn — the
active session acts as the canonical orchestrator and routes work to the in-repo agent suite. It also
carries the full architecture/file-map orientation, so you do not need to read the whole tree to learn
the layout; search to the named location for exact code.

## Operating contract (canonical orchestration — active every session)
This file is auto-loaded into every Claude Code session here, so this contract governs from the first
turn — the **active session is the canonical orchestrator**; no agent has to be invoked to "switch it
on." Apply it by default to every request:
- **Scope first.** Read the relevant invariants below and verify real current state (the backlog is
  stale by policy) before acting.
- **Multi-subsystem or multi-step work** → act as orchestrator: decompose into bounded, single-owner
  tasks; dispatch each to its owning specialist subagent (Task tool) per the AI-asset roster below;
  sequence by dependency; parallelize only genuinely independent tasks; then gate every applied change
  through `reviewer` (PASS/FAIL) before reporting done. Do not edit across subsystem boundaries ad hoc
  — keep the role split.
- **Single-subsystem work** → dispatch to that one owner (a trivial in-boundary change may be made
  directly), then gate through `reviewer`.
- **Runtime/behavior evidence** → drive the live service through `file-folder-operator` under its hard
  preview-then-confirm contract; never present a self-run filesystem op as proof a change works.
- **Always** honor the 7 invariants, the coverage gate, and the branch policy (enhancement branch,
  never `main`/`master`); never commit unless asked.
- **Default to maximal-effort completeness.** Carry every request, task, doubt, and investigation
  through to a definitive end, and build solutions that fully cover the requirement and are ready to
  grow — never the bare minimum — unless the user explicitly relaxes the scope. This governs coverage
  and depth, not verbosity: it never overrides minimal-diff or economical prose, and adds no
  unrequested refactors. See `.claude/instructions/ai-execution-discipline.md` Rule 11; a standing
  user-level SessionStart hook (`$HOME/.claude/hooks/claude-orchestration-contract.py`) reinforces it
  across sessions (external dependency; no per-project copy is created or required).
- **The `.claude/agents/orchestrator.md` subagent is the dispatchable embodiment of this same
  contract** — invoke it (`@agent-orchestrator`, or via the Task tool) when you want a dedicated Opus
  4.8 coordinator or nested delegation (requires Claude Code ≥ v2.1.172). The authority is THIS
  contract, always active regardless of build; the subagent is one way to run it, not a precondition
  for it. It replaces the decommissioned generalist `ffe-maintainer`: it coordinates and gates, it
  does not implement.
- **Meta-work on the asset system itself** (authoring or redesigning agents, skills, hooks, or this
  contract) is handled by the top-level session with the asset-metaprompting / orchestrator-design
  skills — not delegated to the orchestrator subagent, which declares asset design out of scope.

## Principles Applied
- P1 Source-of-Truth Grounding — architecture/commands below are verified against the real code
  (`ff_explorer/core.py`, `pyproject.toml`), not assumed; read the named file before acting on it.
- P2 Full Determinism — Operating contract decision points and invariants are explicit; no
  ambiguous branches.
- P3 Systematicity — work decomposes into bounded, sequenced, single-owner tasks per the role split.
- P4 Consistency — same invariants and role boundaries apply to every session and every agent.
- P5 Context Budget Discipline — target files by search (Grep/Glob), read only the region you need.
- P6 Self-Containment — invariants, gate/build commands, and agent roles are stated here with
  explicit paths; no implicit cross-references.
- P7 Reference Hygiene — every path named here resolves in the tree.
- P8 Principles Inheritance — this block is the inheritance root; agents and skills carry their
  own Principles Applied blocks derived from it.
- P9 Role Separation — role split (orchestrate/operate/dev/review) enforced by the agent roster;
  no agent crosses its boundary.
- P10 Exit-Status Determinism — agents return typed EXIT STATUS; the contract reacts per status.
- P11 Programmatic Determinism — hooks enforce invariants 1–6 deterministically (harness layer);
  cite: `repo-enhancer/orchestrator.md` CONVENTIONS R18/P11.
- P12 Maximal-Effort Completeness — the Operating contract's default: full coverage and definitive
  follow-through over bare-minimum passes, governing depth not verbosity.
- P13 Token Economy — minimal context loading; search-first, read-only-the-region.
Engineering Disciplines (R17) and Programmatic Determinism (R18/P11): canonical definitions at
`repo-enhancer/orchestrator.md` CONVENTIONS; applied to all LLM-facing assets and hooks in this tree.
Deployment: `deployment_target: claude_code` — real deployed `.claude/` tree (agents, skills,
hooks, settings.json); not a design-only specification.

## Architecture (one core, many faces) — search to these, don't bulk-read
- **Headless core** — `ff_explorer/core.py`: query (`list_entries`, `entry_metadata`,
  `save_listing`, `largest_entries`) split from destructive actions (`remove_entries` incl.
  `versioning` mode, `compress_entries`). list_entries carries match_mode/case_sensitive,
  size/date/extension filters, ignore-file awareness, archive transparency, and gated
  `content_query`. Sibling headless modules: `content_search.py`, `presets.py`, `dedupe.py`,
  `rename.py`, `index.py` (opt-in watchdog name index). No tkinter/Qt/PySide6/fastapi/fastmcp
  imports, ever.
- **Access layer (one shared core, two transports)** — `ff_explorer/api/service.py` (shared
  wrapper both transports call), `rest.py` (FastAPI routes + Pydantic models; `name_seed` min_length=1;
  EmptySeedError/ValueError→422, FileNotFound→404), `mcp_server.py` (`FastMCP.from_fastapi` derives
  the MCP tools from the REST routes — exactly 15 tools, asserted by `tests/test_main.py`),
  `main.py` (combined ASGI app + `run_server` console entry; coverage-omitted — cover it with an
  integration test).
- **GUI** — `ff_explorer/gui/` (`main_window.py` ~1500 lines, `app.py`, `_resources.py`,
  `theme.py` + `settings_dialog.py` (centralized Light/Dark theming), `treemap_view.py` (disk
  usage); PySide6) with a UI-side preview-then-confirm dialog (defaults to No). Separate from
  core; not agent-driven.
- **Packaging** — `packaging/FFExplorer.spec`, `packaging/build.py`, `packaging/scripts/png_to_ico.py`
  (PyInstaller).
- **Tests** — `tests/test_core.py`, `test_core_extra.py`, `test_service.py`, `test_rest.py`,
  `test_main.py`, `test_gui_smoke.py`, `test_theme.py`, `test_presets.py`, `test_dedupe.py`,
  `test_rename.py`, `test_versioning.py`, `test_archives.py`, `test_index.py`, `conftest.py`.
- **Config & work list** — `pyproject.toml` (deps, console scripts, `[tool.pytest.ini_options]`,
  `[tool.coverage.run]`); `docs/BACKLOG.md` (items `FFX-B01`…`FFX-B11`, `FFX-I01`…`FFX-I11`).

## Invariants (do not break these)
1. Headless core: `ff_explorer/core.py` imports no tkinter/PySide6/fastapi/fastmcp.
2. Destructive gate: remove/compress mutate only with `dry_run=false` AND `confirm=true`;
   empty/whitespace `name_seed` is rejected (EmptySeedError); removes go to the OS recycle bin via
   `send2trash` (compress permanently deletes originals — the zip is the recovery).
3. Coverage gate: `--cov-fail-under=90` over `ff_explorer` (`gui/*`, `__init__.py`, `api/main.py`
   omitted). Stays green; never lower the threshold or widen the omit to pass.
4. Packaging keeps building (FFX-B01: guard the `.ico` reference so a missing icon does not abort).
5. One shared core: add a capability in core+service so REST and MCP both inherit it; never fork
   logic between the two transports.
6. Never commit secrets or build artifacts (`packaging/bin/`, `packaging/work/`, `dist/`, `build/`).
7. Commits land on the enhancement branch, never `main`/`master` (committing is the orchestrator's job).

## Gate & build commands (run, then read the output)
- Install: `pip install -e ".[dev,api]"`
- Coverage gate (the real gate): `pytest` (addopts inject `--cov=ff_explorer --cov-fail-under=90 --cov-report=term-missing`)
- Headless GUI test: set `QT_QPA_PLATFORM=offscreen` before `pytest`
- Build the executable: `python packaging/build.py` (Python 3.13; or `py -3.13 packaging/build.py`)
- Run the GUI: `ff-explorer-gui`; run the access layer: `ff-explorer-api` (HTTP, loopback by default) or `ff-explorer-mcp` (stdio)
- Find dangling refs after a deletion: `rg "<symbol>" -n`

## AI asset suite (single source of truth — use these; don't do their jobs ad hoc)

### Agents (`.claude/agents/`)
- **orchestrator** — the dispatchable embodiment of the **Operating contract** above (the canonical
  orchestration always runs in the active session; this subagent is its invokable form). Plans
  multi-subsystem work, decomposes it into bounded single-owner tasks, dispatches the specialist
  agents below as subagents (Task tool), then gates every applied change through reviewer. Coordinates
  and gates; holds no Edit/Write — never edits files itself. Replaces the decommissioned generalist
  maintainer. Requires Claude Code ≥ v2.1.172 (nested subagents); else it emits a dispatch plan for the
  top-level session. Invoke it for a dedicated Opus 4.8 coordinator or nested delegation — it is not a
  precondition for orchestration.
- **file-folder-operator** — drives the RUNNING access layer (the six MCP/REST ops) headlessly with
  a hard preview-then-confirm safety contract. Operates; never edits code.
- **core-dev** — headless core (query/destructive split, stat/metadata, predicates, exception types).
- **gui-dev** — PySide6 GUI; thin client over the core, preview-then-confirm safety dialog.
- **access-dev** — dual MCP+REST over one shared service; thread params, error mapping, bind, tool-name contract.
- **test-author** — pytest + the ≥90% core coverage gate; deterministic offline tests, exact MCP tool-name set.
- **packaging-builder** — PyInstaller spec/build + icon guard (FFX-B01) + OS-conditional hiddenimports (FFX-B04) + artifact hygiene.
- **docs-writer** — keeps README / operating doc / access docs / agent contracts truthful to code.
- **reviewer** — read-only correctness + destructive-safety/security PASS/FAIL gate; verifies the 7 invariants. Authors no fix.

Role split: the active session is the canonical orchestrator (per the Operating contract), with the
orchestrator subagent as its dispatchable form — both COORDINATE (dispatch + gate, never edit);
file-folder-operator OPERATES the live service; the dev agents EDIT their subsystem; reviewer GATES.
The roster is split by subsystem: core/gui/access/test/packaging/docs.

Model assignment (per-agent `model:` frontmatter, capability-tiered): **Opus 4.8**
(`claude-opus-4-8`) — orchestrator, reviewer (coordination + judgment gate). **Sonnet 4.6**
(`claude-sonnet-4-6`) — core-dev, access-dev, gui-dev, test-author (substantive implementation +
test correctness). **Haiku 4.5** (`claude-haiku-4-5-20251001`) — docs-writer, packaging-builder
(well-scoped doc/config edits). file-folder-operator inherits the session model. The `model:` field
may be overridden by `CLAUDE_CODE_SUBAGENT_MODEL` and is ignored on some Claude Code builds.

### Instructions (`.claude/instructions/`) — agents reference these, don't restate them
- **ai-execution-discipline.md** — verify-before-edit, assumption checks, minimal change, stop-and-confirm on irreversible/ambiguous, acceptance-criteria-driven done, context-budget (checkpoint ~70%, Gleaner=5), and Rule 11 maximal-effort completeness.
- **python-repo-conventions.md** — stdlib-first, typing, headless-core purity, deterministic offline tests, no secrets, optional-dep groups.
- **sdd-constitution.md** — project non-negotiable engineering principles and SDD gate definitions; governs all SDD pipeline skills.
- **pyside6-best-practices.md** — PySide6/Qt best practices (Qt-thread safety, offscreen testing, no-core-in-widgets); governs gui-dev.

### Skills (`.claude/skills/`)
- **add-search-feature** — add a new search/filter capability to the core + thread it through the access layer + tests.
- **expose-op** — add/thread a core op or param through service→REST→derived MCP tool, with error mapping, the destructive gate, and contract tests.
- **run-quality-gate** (`scripts/run_gate.py`) — pytest+coverage + invariant grep sweep → PASS/FAIL.
- **build-release** (`scripts/build_release.py`) — PyInstaller build with the FFX-B01 icon guard, send2trash bundling + clean-tree verify.
- **SDD pipeline** (`specify`→`clarify`→`plan`→`tasks`→`analyze`→`checklist`) — drives feature work from spec through acceptance gate; `analyze` and `checklist` delegate gate execution to `run-quality-gate`.

### Hooks (`.claude/settings.json` + `.claude/hooks/`) — harness-enforced invariants
- **headless_core_guard.py** (PreToolUse) — blocks a GUI/transport import into `ff_explorer/core.py` (invariant 1).
- **no_secrets_or_artifacts.py** (PreToolUse) — blocks writing a secret or a build-artifact path (invariant 6).
- **tkinter_regression_guard.py** (PreToolUse) — blocks any `import tkinter` or `.pyw` reappearing (FFX-B02).
- **destructive_op_safety_guard.py** (PreToolUse) — blocks weakening the destructive gate in core/api (raw delete on the remove path, dry_run/confirm defaults flipped, empty-seed rejection dropped) — invariant 2.
- **coverage_gate_reminder.py** (PostToolUse, non-blocking) — reminds to run the gate after touching core/api/tests (invariant 3).

## Backlog
The authoritative work list is `docs/BACKLOG.md`, referenced by item ID (`FFX-B01`…`FFX-B11`,
`FFX-I01`…`FFX-I11`). Each item is self-contained with acceptance criteria; backlog line references
are stale by policy — re-verify locations before editing.
</content>
