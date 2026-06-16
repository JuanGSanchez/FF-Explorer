# FF-Explorer — Agent Access Layer

External agents can drive all FF-Explorer operations without launching the
GUI via a **dual REST + MCP interface** over one shared core module.

## Architecture

```
ff_explorer.core          (pure filesystem logic — traversal, filter, save, remove, compress)
        |
ff_explorer.api.service   (thin typed wrappers — single shared layer)
       / \
 rest.py   mcp_server.py  (FastAPI REST app  /  FastMCP MCP server)
       \  /
      main.py             (combined ASGI app: REST routes + MCP at /mcp)
```

Both REST and MCP call the **same** service module.  No logic is duplicated.

## Install

```bash
pip install "ff-explorer[api]"
```

## Run the combined server (REST + MCP Streamable HTTP)

```bash
# via console script — binds 127.0.0.1 (loopback) by default
ff-explorer-api

# opt-in to all interfaces: explicit --host flag
ff-explorer-api --host 0.0.0.0

# opt-in to all interfaces: environment variable
FFE_BIND_ALL=1 ff-explorer-api

# or directly with uvicorn
uvicorn ff_explorer.api.main:app --host 127.0.0.1 --port 8000
```

> **Security note:** The access layer exposes destructive operations (remove,
> compress).  The default bind is `127.0.0.1` (loopback only).  Binding
> `0.0.0.0` requires an explicit opt-in via `--host 0.0.0.0` or
> `FFE_BIND_ALL=1` and should only be used in trusted network environments.

Interactive docs at `http://localhost:8000/docs` once running.

## Run MCP over stdio (for CLI/agent clients)

```bash
ff-explorer-mcp
```

## REST endpoints

| Method | Path              | Tag          | Description |
|--------|-------------------|--------------|-------------|
| GET    | /health           | meta         | Liveness + version |
| POST   | /entries          | query        | List matching file/folder entries (non-destructive) |
| POST   | /metadata         | query        | Return size/mtime/type for a single path |
| POST   | /listing          | safe-write   | Walk and write a .txt listing file |
| POST   | /duplicates       | query        | Find duplicate files by content hash (FFX-I06) |
| POST   | /largest          | query        | Top-N largest files by size, sorted descending (FFX-I11) |
| POST   | /remove           | destructive  | Remove matched entries (GUARDED — dry-run default) |
| POST   | /compress         | destructive  | Compress matched entries into zip(s) (GUARDED — dry-run default) |
| POST   | /rename           | destructive  | Batch rename matched entries (GUARDED — dry-run default, FFX-I07) |
| POST   | /presets/save     | presets      | Save (upsert) a named preset (FFX-I03) |
| POST   | /presets/list     | presets      | List all stored presets (FFX-I03) |
| POST   | /presets/run      | presets      | Execute a named preset (GUARDED for destructive, FFX-I03) |
| POST   | /index/start      | index        | Build in-memory name index + start watchdog observer (FFX-I10) |
| POST   | /index/stop       | index        | Stop index + observer for a root (FFX-I10) |
| POST   | /index/status     | index        | Query whether a root is currently indexed (FFX-I10) |

### POST /largest — size aggregation (FFX-I11)

Non-destructive.  No `dry_run`/`confirm` gate required.  Empty `name_seed`
is allowed and aggregates the whole tree.

```json
POST /largest
{
  "path": "C:/Users/me/Documents",
  "top_n": 10,
  "name_seed": ""
}
```

Response: `{"entries": [{"path": "...", "size": 12345}, ...], "count": 10}`
— sorted descending by `size`; capped at `top_n` (must be ≥ 1).

Error mapping: missing path → HTTP 404; `top_n < 1` → HTTP 422.

## MCP tools

FastMCP derives tool names from the FastAPI route function name + path.
Pattern: `<function_name>_<path_segments>_<method>`.  All 15 tools below
are available via the MCP Streamable-HTTP endpoint at `/mcp` or via stdio
(`ff-explorer-mcp`).

| Derived tool name                          | REST route             | Description |
|--------------------------------------------|------------------------|-------------|
| `health_health_get`                        | GET /health            | Liveness + version |
| `post_list_entries_entries_post`           | POST /entries          | List matching entries (non-destructive) |
| `post_entry_metadata_metadata_post`        | POST /metadata         | Metadata for a single path |
| `post_save_listing_listing_post`           | POST /listing          | Write a .txt listing file |
| `post_find_duplicates_duplicates_post`     | POST /duplicates       | Find duplicate files (FFX-I06) |
| `post_largest_entries_largest_post`        | POST /largest          | Top-N largest files (FFX-I11) |
| `post_remove_remove_post`                  | POST /remove           | GUARDED remove (dry-run default) |
| `post_compress_compress_post`              | POST /compress         | GUARDED compress (dry-run default) |
| `post_rename_rename_post`                  | POST /rename           | GUARDED batch rename (FFX-I07) |
| `post_save_preset_presets_save_post`       | POST /presets/save     | Save preset (FFX-I03) |
| `post_list_presets_presets_list_post`      | POST /presets/list     | List presets (FFX-I03) |
| `post_run_preset_presets_run_post`         | POST /presets/run      | Run preset (FFX-I03) |
| `post_start_index_index_start_post`        | POST /index/start      | Start index (FFX-I10) |
| `post_stop_index_index_stop_post`          | POST /index/stop       | Stop index (FFX-I10) |
| `post_index_status_index_status_post`      | POST /index/status     | Index status (FFX-I10) |

## Hard-guard contract for destructive operations

`POST /remove`, `POST /compress` (and MCP tools `post_remove`, `post_compress`) are
**destructive**.  The contract is:

### Default (safe — preview mode)

Omitting the guard flags, or sending `"dry_run": true`, returns the
`.matched` / `.would_affect` preview list and **mutates nothing**:

```json
POST /remove
{
  "path": "C:/tmp/test",
  "kind": 1,
  "name_seed": "old_"
}
```

Response includes `"dry_run": true` and `"matched": [...]` — no files touched.

### To actually mutate: send BOTH flags explicitly

```json
POST /remove
{
  "path": "C:/tmp/test",
  "kind": 1,
  "name_seed": "old_",
  "dry_run": false,
  "confirm": true
}
```

**Both `"dry_run": false` AND `"confirm": true` are required.**
Sending only one of the two is rejected (HTTP 422).

> Recommendation for agents: always call `POST /entries` or the tool
> in default (dry-run) mode first to inspect the match list, then issue
> the confirmed call if the preview is acceptable.

### Recycle-bin routing

`POST /remove` routes deletes through **send2trash** (OS recycle bin / trash)
when the package is installed, making removals recoverable.  Without
send2trash, files are permanently deleted.

### Empty name_seed rejection

Passing an empty or whitespace-only `name_seed` to a destructive route is
**always rejected** with HTTP 422 / MCP `isError: true` and an
`EmptySeedError` body.  An empty seed would match every entry under the path.

## Error mapping

| Core exception       | HTTP status | MCP               | Notes |
|----------------------|-------------|-------------------|-------|
| `EmptySeedError`     | 422         | `isError: true`   | Destructive ops only |
| `ValueError`         | 422         | `isError: true`   | Bad path or missing confirm |
| `FileNotFoundError`  | 404         | `isError: true`   | Entry metadata only |

## kind values

| Value | Meaning        |
|-------|----------------|
| `0`   | `EntryKind.FOLDERS` — match subdirectory names |
| `1`   | `EntryKind.FILES`   — match file names |

## Version pins (access-layer deps)

| Package  | Pin            |
|----------|----------------|
| fastmcp  | `>=3.4,<4`     |
| fastapi  | `>=0.136,<1`   |
| uvicorn  | `>=0.49,<1`    |

Build/runtime ceiling: **Python 3.13** (FastMCP 3.4.2 declares 3.10–3.13;
see `docs/research-unit-converter.md` limitation L1).
