---
name: expose-op
description: >
  Adds a new operation (or a new parameter) to FF-Explorer's shared core and threads it end-to-end
  through the dual access layer over ONE shared service: core (ff_explorer/core.py) → shared
  service (api/service.py) → FastAPI route in api/rest.py (Pydantic validation + error mapping) →
  the auto-derived FastMCP tool (api/mcp_server.py `from_fastapi`) → contract tests. Keeps one core
  behind both transports; never forks logic. Use when asked to "expose <op> via REST+MCP", "add a
  param to the API", "thread <fn> through REST/MCP", or to surface a core capability to agents. A
  DESTRUCTIVE op (remove/compress-style: deletes, mutates the filesystem) is GATED — it must carry
  the dry_run+confirm+non-empty-seed safety contract and requires explicit re-approval. Pairs with
  the access-dev agent.
version: 0.1.0
principles_applied:
  inherited:
    - P1 — Source-of-Truth Grounding
    - P2 — Full Determinism
    - P4 — Consistency
    - P5 — Context Budget Discipline
    - P6 — Self-Containment
    - P7 — Reference Hygiene
  custom:
    - id: C1
      name: One Shared Core
      requires: >
        The capability is added in core+service so REST and MCP both inherit it; transport-shared
        logic never forks into rest.py or mcp_server.py (CLAUDE.md invariant 5).
      rationale: Forking the two transports is the exact drift the dual-access design exists to prevent.
    - id: C2
      name: Destructive Gate Preserved
      requires: >
        A destructive op carries the full safety contract: dry_run defaults true, a live run needs
        dry_run=false AND confirm=true together, and an empty/whitespace name_seed is rejected
        (EmptySeedError / min_length=1, removes route to the recycle bin via send2trash). Exposing a
        new destructive op requires explicit re-approval before adding it.
      rationale: A new destructive surface that skips the gate ships the catastrophic-loss regression
        the campaign exists to prevent (CLAUDE.md invariant 2).
---
# Expose Op

Procedural workflow to surface a core capability through FF-Explorer's dual REST + MCP access layer over one shared service, with validation, error mapping, the destructive gate, and contract tests.

## Workflow

### Step 1: Confirm (or add) the core capability
Read the function/parameter in `ff_explorer/core.py` you are exposing. If it does not exist yet, add it to the headless core FIRST (no GUI/transport imports — invariant 1), separating query helpers from destructive actions as the module already does. This skill threads an existing-or-just-added core capability; it does not design new filesystem semantics ad hoc.

### Step 2: Classify the op surface — GATE check (C2)
Determine if the op is READ-only (list/metadata/save-listing style) or DESTRUCTIVE (remove/compress style: deletes, moves, mutates the filesystem). A destructive op is GATED: it must carry the safety contract (Step 4) and exposing a NEW destructive op requires explicit re-approval before you add it (ai-execution-discipline). If gated and unapproved, STOP and request approval.

### Step 3: Thread through the shared service
Add/extend the function in `ff_explorer/api/service.py` so it delegates to the core. All transport-shared logic lives here — never fork it into `rest.py` or `mcp_server.py` (invariant 5 / C1).

### Step 4: Add the FastAPI route + validation + error mapping (+ destructive gate)
In `api/rest.py`: define the route with an explicit `operation_id` (this becomes the MCP tool name), a Pydantic request model that validates inputs at the boundary, and error mapping — `EmptySeedError`/`ValueError` → HTTP 422; `FileNotFoundError` → 404. No core error may escape as a 500. For a DESTRUCTIVE route, the request model MUST include `dry_run: bool = True` and `confirm: bool = False`, mutate only when `dry_run is False and confirm is True`, reject an empty/whitespace `name_seed` (`min_length=1` / EmptySeedError), and route removes to the recycle bin via send2trash (C2).

### Step 5: Confirm the derived MCP tool
The MCP tool name is derived from the FastAPI `operation_id` by `FastMCP.from_fastapi` in `api/mcp_server.py` — you do not hand-write the tool. Confirm the derived name matches the intended contract (e.g. `post_list_entries`, `post_remove`, `post_compress`). Changing an `operation_id` changes a tool name AND the operator-agent/docs contract.

### Step 6: Add contract tests
In `tests/test_rest.py` / `test_service.py` (and an integration case against the combined `api/main.app` — FFX-B03): assert the route status codes (success + each mapped error), boundary validation rejections, and — for a destructive op — that an empty-seed and a missing-confirm call BOTH still return 422 / are refused, dry-run does not mutate, and the exact MCP tool-name set is unchanged. A drifted tool set is a FAIL.

### Step 7: Update the contract docs + verify
Update `docs/agent-operating-doc.md` (op table, I/O, error table), `ff_explorer/api/README-access.md`, and the `file-folder-operator` agent's six-op table so the documented contract matches (route to docs-writer or do it inline). Run the suite, READ the output (the >=90% gate must stay green — invariant 3), and report status codes, the tool-name set, and an acceptance checklist.

## Output Format

```
EXPOSE OP: <op/param> via REST+MCP
- Surface: read-only | DESTRUCTIVE (GATE: approved? yes/no; dry_run+confirm+non-empty-seed wired?)
- core.py: <fn/param added-or-confirmed>
- service.py: <fn/param threaded>
- rest.py: route <method path> operation_id=<id>, validation <model>, errors <codes mapped>
- MCP tool (derived): <name>
- Tests: <route status, validation, gate (empty-seed/no-confirm refused), exact tool-name set>
- Docs contract updated: <files>
- Gate: coverage >=90% green (yes/no)
- Checklist: <criterion: met/NOT met + evidence>
```

## Examples

### Example 1
**Input:** "Add a `match_mode` param (substring|glob|regex) to the list API (FFX-I01)."
**Output:**
```
EXPOSE OP: match_mode param via REST+MCP
- Surface: read-only (no gate)
- core.py: list_entries gains match_mode (compile re once for regex, fnmatch.translate for glob)
- service.py: list_entries(...) passes match_mode through to core
- rest.py: POST /entries operation_id=post_list_entries, Pydantic match_mode:Literal[...]=substring, invalid regex→422
- MCP tool (derived): post_list_entries (unchanged name; new param exposed)
- Tests: regex match set asserted; invalid regex→422; default substring unchanged; exact tool set
- Docs contract updated: agent-operating-doc.md, README-access.md, file-folder-operator.md
- Gate: coverage >=90% green (yes)
- Checklist: regex matches ✓; invalid→422 ✓; default unchanged ✓; exact tool set ✓
```

### Example 2
**Input:** "Expose a new `find_duplicates` op that bulk-removes dupes (FFX-I06)."
**Output:**
```
EXPOSE OP: find_duplicates (+ guarded bulk-remove) via REST+MCP
- Surface: DESTRUCTIVE (GATE: approval REQUIRED before adding the remove path; dry_run+confirm+non-empty-seed must be wired)
- core.py: find_duplicates (size-bucket then hash); reuses guarded remove_entries for the bulk-remove
- service.py: find_duplicates threaded; remove path delegates to existing recycle-bin route
- rest.py: POST /duplicates operation_id=post_find_duplicates (read), remove via post_remove (dry_run=True/confirm=False defaults)
- MCP tool (derived): post_find_duplicates
- Tests: duplicate groups asserted; bulk-remove refused without confirm; empty-seed→422; exact tool set
- Docs contract updated: agent-operating-doc.md, README-access.md, file-folder-operator.md
- Gate: coverage >=90% green (yes)
- Checklist: groups by content ✓; remove gated (dry_run+confirm) ✓; recycle-bin route ✓
```

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format, examples

External dependencies (must be available in the execution environment):
- Python 3.13 with the repo `[api]` and `[dev]` extras (fastmcp, fastapi, pytest, send2trash) installed.

## Sources
- `ff_explorer/core.py` (query vs destructive split, EmptySeedError, send2trash route), `ff_explorer/api/{service,rest,mcp_server,main}.py` (shared service, routes, error mapping, `from_fastapi` tool derivation, combined ASGI app).
- `CLAUDE.md` (invariants 1, 2, 3, 5), `docs/BACKLOG.md` (FFX-I01/I02/I06, gated I05/I07/I08, FFX-B03 combined-app test), `docs/agent-operating-doc.md` (six-op contract, error table).
- `.claude/instructions/ai-execution-discipline.md` (gate / stop-and-confirm), `.claude/agents/file-folder-operator.md` (operator op table).
- references/claude.md §SKILL: frontmatter, description rules, body structure.
