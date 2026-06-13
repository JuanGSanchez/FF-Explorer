# FF-Explorer — Agent Orientation (CLAUDE.md)

Single orientation file for any Claude agent working in this repo. Read it ONCE at the
start of a task; it is the source of truth for architecture, invariants, and gate
commands so you do not have to read the whole tree to learn them. If you need exact
code, search to the named location — do not re-derive the map below by reading modules.

## Principles Applied

Inherited:
- P1 — Source-of-Truth Grounding
- P4 — Consistency
- P6 — Self-Containment
- P7 — Reference Hygiene
(P2/P3/P5 n/a — this is a prose orientation document, not an executable asset.)

Custom:
- C1 — Invariant Authority: this file is the canonical statement of the repo's invariants and gate commands; agents preserve them rather than re-inferring them. (Rationale: a single authoritative orientation prevents drift and saves context.)

## What this repo is
FF-Explorer recursively lists folders/files whose name contains a substring "name seed"
under a root, and can Save a listing, Remove (recycle-bin), or Compress (zip then delete)
the matches. Stack: Python; PySide6 GUI; FastMCP + FastAPI dual access layer over one
shared headless core; PyInstaller packaging; pytest + coverage gate.

## Architecture & file map (search to these — don't bulk-read)
- `ff_explorer/core.py` — headless core: query (`list_entries`, `entry_metadata`,
  `save_listing`) separated from destructive actions (`remove_entries`,
  `compress_entries`). No GUI/Qt/FastAPI imports.
- `ff_explorer/api/service.py` — shared wrapper both transports call.
- `ff_explorer/api/rest.py` — FastAPI routes + Pydantic request/response models
  (`name_seed` `min_length=1`; error mapping EmptySeedError/ValueError->422, FileNotFound->404).
- `ff_explorer/api/mcp_server.py` — `FastMCP.from_fastapi` (MCP tools generated from REST).
- `ff_explorer/api/main.py` — combined ASGI app + `run_server` console entry.
- `ff_explorer/gui/main_window.py` (~485 lines), `app.py`, `_resources.py` — PySide6 GUI;
  UI-side preview-then-confirm dialog (defaults to No).
- `packaging/FFExplorer.spec`, `packaging/build.py`, `packaging/scripts/png_to_ico.py`.
- `tests/test_core.py`, `test_core_extra.py`, `test_service.py`, `test_rest.py`, `conftest.py`.
- `pyproject.toml` — deps, console scripts, `[tool.pytest.ini_options]`, `[tool.coverage.run]`.
- `docs/BACKLOG.md` — the improvement backlog (items FFX-B01..B11, FFX-I01..I11).
- Note: `FF_utils.py` (top-level) is legacy and slated for removal — do not extend it.

## Invariants — MUST hold after any change
1. Headless core: `ff_explorer/core.py` imports no tkinter/PySide6/fastapi/fastmcp.
2. Destructive gate: remove/compress mutate only with `dry_run=false` AND `confirm=true`;
   empty/whitespace `name_seed` is rejected (EmptySeedError); removes go to the OS recycle
   bin via `send2trash` (compress permanently deletes originals — zip is the recovery).
3. Coverage gate: `--cov-fail-under=90` over `ff_explorer` with `gui/*`, `__init__.py`,
   `api/main.py` omitted. Stays green; do not lower the threshold or widen omit to pass.
4. Packaging: `packaging/FFExplorer.spec`/`build.py` keep building.
5. One shared core: add a capability in core+service so REST and MCP both inherit it; never
   fork logic between the two transports.
6. No secrets committed (use env vars; never inline credentials/keys/tokens).
7. Branch safety: work stays on the enhancement branch; agents do not run git mutations and
   never target main/master (committing is the orchestrator's job).

## Gate & build commands
- Install: `pip install -e ".[dev,api]"`
- Suite + coverage gate (the real gate): `pytest`  (addopts inject `--cov=ff_explorer --cov-fail-under=90 --cov-report=term-missing`)
- Targeted iteration: `pytest tests/test_core.py -k <name>`  (not a substitute for the full gate)
- Headless GUI test: set `QT_QPA_PLATFORM=offscreen` before `pytest`
- Find dangling refs after a deletion: `rg "<symbol>" -n`
- Packaging sanity (when touched): `python packaging/build.py` completes and exits 0
- Run the GUI: `ff-explorer-gui`; run the access layer: `ff-explorer-api` (HTTP, bind
  loopback by default) or `ff-explorer-mcp` (stdio).

## Agents in this repo
- `.claude/agents/file-folder-operator.md` — drives the RUNNING access layer (the six MCP/REST
  ops) headlessly with a preview-then-confirm safety contract. Operates the app; does not edit code.
- `.claude/agents/ffe-maintainer.md` — implements `docs/BACKLOG.md` items end-to-end (edit code,
  add tests, pass the gate, update docs, check packaging) while preserving the invariants above.

## Sources
- Repo ground truth: `ff_explorer/` tree, `pyproject.toml`, `packaging/`, `tests/`, `docs/BACKLOG.md`.
- Campaign invariants: the enhancement strategy and review for FF-Explorer (orchestrator docs).
