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
# via console script
ff-explorer-api

# or directly with uvicorn
uvicorn ff_explorer.api.main:app --host 0.0.0.0 --port 8000
```

Interactive docs at `http://localhost:8000/docs` once running.

## Run MCP over stdio (for CLI/agent clients)

```bash
ff-explorer-mcp
```

## REST endpoints

| Method | Path        | Tag          | Description |
|--------|-------------|--------------|-------------|
| GET    | /health     | meta         | Liveness + version |
| POST   | /entries    | query        | List matching file/folder entries (non-destructive) |
| POST   | /metadata   | query        | Return size/mtime/type for a single path |
| POST   | /listing    | safe-write   | Walk and write a .txt listing file |
| POST   | /remove     | destructive  | Remove matched entries (GUARDED — dry-run default) |
| POST   | /compress   | destructive  | Compress matched entries into zip(s) (GUARDED — dry-run default) |

## MCP tools

| Tool name             | Derived from       | Description |
|-----------------------|--------------------|-------------|
| `health`              | GET /health        | Liveness + version |
| `post_list_entries`   | POST /entries      | List matching entries (non-destructive) |
| `post_entry_metadata` | POST /metadata     | Metadata for a single path |
| `post_save_listing`   | POST /listing      | Write a .txt listing file |
| `post_remove`         | POST /remove       | GUARDED remove (dry-run default) |
| `post_compress`       | POST /compress     | GUARDED compress (dry-run default) |

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
