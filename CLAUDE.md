# FF-Explorer — repository guide for Claude

Recursive file/folder explorer: lists folders/files whose name contains a substring "name seed"
under a root, and can Save a listing, Remove (recycle-bin), or Compress (zip then delete) the
matches. One pure headless core powers a PySide6 GUI, a dual FastAPI (REST) + FastMCP access layer,
and a PyInstaller build. This file is the always-loaded ground truth; the full architecture/file-map
orientation lives in `.claude/CLAUDE.md` (read it once when you need the map). The in-repo subagents
below own the actual work.

## Principles Applied
- P1 Source-of-Truth Grounding — architecture/commands below are verified against the real code
  (`ff_explorer/core.py`, `pyproject.toml`), not assumed; read the named file before acting on it.
- P5 Context Budget Discipline — target files by search (Grep/Glob), read only the region you need.
- P6 Self-Containment — invariants, gate/build commands, and agent roles are stated here with
  explicit paths.
- P7 Reference Hygiene — every path named here resolves in the tree.

## Architecture (one core, many faces)
- **Headless core** — `ff_explorer/core.py`: query (`list_entries`, `entry_metadata`,
  `save_listing`) split from destructive actions (`remove_entries`, `compress_entries`). No
  tkinter/Qt/PySide6/fastapi/fastmcp imports, ever.
- **Access layer (one shared core, two transports)** — `ff_explorer/api/service.py` (shared
  wrapper), `rest.py` (FastAPI routes + Pydantic models; `name_seed` min_length=1;
  EmptySeedError/ValueError→422, FileNotFound→404), `mcp_server.py` (`FastMCP.from_fastapi` derives
  the MCP tools from the REST routes), `main.py` (combined ASGI app + `run_server`).
- **GUI** — `ff_explorer/gui/` (PySide6; ~485-line main window) with a UI-side preview-then-confirm
  dialog (defaults to No). Separate from core; not agent-driven.
- **Packaging** — `packaging/FFExplorer.spec`, `packaging/build.py` (PyInstaller). Legacy
  `FF_utils.py` (top-level, pre-refactor core) is slated for removal — do not extend it.
- **Tests** — `tests/test_core.py`, `test_core_extra.py`, `test_service.py`, `test_rest.py`.

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
- **file-folder-operator** — drives the RUNNING access layer (the six MCP/REST ops) headlessly with
  a hard preview-then-confirm safety contract. Operates; never edits code.
- **ffe-maintainer** — implements `docs/BACKLOG.md` items end-to-end while preserving the invariants.
- **core-dev** — headless core (query/destructive split, stat/metadata, predicates, exception types).
- **gui-dev** — PySide6 GUI; thin client over the core, preview-then-confirm safety dialog.
- **access-dev** — dual MCP+REST over one shared service; thread params, error mapping, bind, tool-name contract.
- **test-author** — pytest + the ≥90% core coverage gate; deterministic offline tests, exact MCP tool-name set.
- **packaging-builder** — PyInstaller spec/build + icon guard (FFX-B01) + OS-conditional hiddenimports (FFX-B04) + artifact hygiene.
- **docs-writer** — keeps README / operating doc / access docs / agent contracts truthful to code.
- **reviewer** — read-only correctness + destructive-safety/security PASS/FAIL gate; verifies the 7 invariants. Authors no fix.

### Instructions (`.claude/instructions/`) — agents reference these, don't restate them
- **ai-execution-discipline.md** — verify-before-edit, assumption checks, minimal change, stop-and-confirm on irreversible/ambiguous, acceptance-criteria-driven done, context-budget (checkpoint ~70%, Gleaner=5).
- **python-repo-conventions.md** — stdlib-first, typing, headless-core purity, deterministic offline tests, no secrets, optional-dep groups.

### Skills (`.claude/skills/`)
- **add-search-feature** — add a new search/filter capability to the core + thread it through the access layer + tests.
- **expose-op** — add/thread a core op or param through service→REST→derived MCP tool, with error mapping, the destructive gate, and contract tests.
- **run-quality-gate** (`scripts/run_gate.py`) — pytest+coverage + invariant grep sweep → PASS/FAIL.
- **build-release** (`scripts/build_release.py`) — PyInstaller build with the FFX-B01 icon guard, send2trash bundling + clean-tree verify.

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
