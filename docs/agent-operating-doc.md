# FF-Explorer — In-Repo Agent Operating Guide

This document describes how an external agent (or any automated client) should drive the
FF-Explorer repository via its access layer. It is the operating guide that the in-repo
Claude agent asset references.

> **In-repo agent asset:** [`.claude/agents/file-folder-operator.md`](../.claude/agents/file-folder-operator.md)
> — the `file-folder-operator` Claude Code subagent that drives this repo's file and folder
> operations headlessly through the MCP/REST access layer described below.

---

## Table of contents

1. [What this repo does for agents](#what-this-repo-does-for-agents)
2. [Safety contract — read first](#safety-contract--read-first)
3. [Starting the access layer](#starting-the-access-layer)
4. [Available tools](#available-tools)
5. [Workflow: discovery and listing](#workflow-discovery-and-listing)
6. [Workflow: save a listing to disk](#workflow-save-a-listing-to-disk)
7. [Workflow: preview then remove](#workflow-preview-then-remove)
8. [Workflow: preview then compress](#workflow-preview-then-compress)
9. [Input/output reference](#inputoutput-reference)
10. [The confirm-token contract (concrete JSON)](#the-confirm-token-contract-concrete-json)
11. [Error table](#error-table)
12. [What the agent does NOT control](#what-the-agent-does-not-control)

---

## What this repo does for agents

FF-Explorer exposes a **filesystem-manipulation service**. An agent uses it to:

- **List** every folder or file under a root directory whose name contains a substring seed.
- **Inspect** size, modification time, and type for a single path.
- **Save** a matched-entry list to a `.txt` index file in the scanned root.
- **Remove** matched entries, with recycle-bin routing and dry-run preview.
- **Compress** matched entries into zip archives, then delete the originals, with dry-run
  preview.

All five operations are exposed identically through the REST API and the MCP tool set.

---

## Safety contract — read first

This is the single most important section. FF-Explorer can delete and compress-then-delete
matched filesystem entries. Three hard guards prevent accidental data loss. An agent MUST
understand all three before calling any destructive tool.

### Guard 1 — Non-empty name seed is mandatory

`POST /remove` and `POST /compress` (and their MCP equivalents `post_remove` /
`post_compress`) require a non-empty, non-whitespace `name_seed`. A blank seed would
match every entry under the path. The core raises `EmptySeedError` immediately and no
filesystem access occurs. The REST API returns **HTTP 422**.

Never call a destructive tool with `name_seed: ""` or `name_seed: "   "`.

### Guard 2 — dry_run defaults to True

Every destructive call is a **preview by default**. Sending a request body without
`"dry_run": false` returns the `matched` / `would_affect` list and changes nothing on disk.
This is intentional and safe to call as many times as needed.

### Guard 3 — confirm=true is required for a live run

To actually mutate the filesystem, the request body must contain **both**:

```json
{
  "dry_run": false,
  "confirm": true
}
```

Either flag alone is not sufficient. The confirm field is an explicit opt-in token.

### Guard 4 — Deletes go to the recycle bin

When `send2trash` is available (it is a declared dependency and is bundled in the
executable), removals send matched entries to the OS recycle bin — not permanent unlink.
After compression the originals are permanently deleted (the zip is the recovery
mechanism).

---

## Starting the access layer

The server must be running before any tool call (Streamable HTTP transport), or the
`ff-explorer-mcp` process must be launched (stdio transport).

### Streamable HTTP (preferred for remote / multi-client use)

```bash
pip install "ff-explorer[api]"
ff-explorer-api
# Server ready at http://localhost:8000
# REST endpoints:   http://localhost:8000/health  (and /entries, /metadata, /listing, /remove, /compress)
# MCP endpoint:     http://localhost:8000/mcp
# Interactive docs: http://localhost:8000/docs
```

Or invoke uvicorn directly:

```bash
uvicorn ff_explorer.api.main:app --host 0.0.0.0 --port 8000
```

### stdio (preferred for local / single-client / Claude Desktop use)

```bash
pip install "ff-explorer[api]"
ff-explorer-mcp
```

MCP client configuration:

```json
{
  "mcpServers": {
    "ff-explorer": {
      "command": "ff-explorer-mcp"
    }
  }
}
```

---

## Available tools

All six tools are available on both the Streamable HTTP MCP endpoint (`/mcp`) and the
stdio MCP server.

| MCP tool name | REST method | REST route | Description |
|---------------|-------------|------------|-------------|
| `health` | `GET` | `/health` | Liveness and version check |
| `post_list_entries` | `POST` | `/entries` | List matching entries — non-destructive |
| `post_entry_metadata` | `POST` | `/metadata` | Metadata for a single path |
| `post_save_listing` | `POST` | `/listing` | Walk and write a `.txt` listing file |
| `post_remove` | `POST` | `/remove` | Remove matched entries — **dry-run by default** |
| `post_compress` | `POST` | `/compress` | Compress matched entries into zip(s) — **dry-run by default** |

---

## Workflow: discovery and listing

The typical non-destructive workflow is:

1. Call `health` to confirm the server is up.
2. Call `post_list_entries` with the root path, kind (`0`=folders / `1`=files), and a
   name seed.
3. Optionally call `post_entry_metadata` on any returned path for size/mtime detail.

### Example — list all `.log` files under a directory

```json
// POST /entries  (or MCP tool: post_list_entries)
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": ".log",
  "case_sensitive": true
}
```

```json
// Response
{
  "entries": [
    {"path": "C:/Users/me/project/build/output.log", "kind": 1},
    {"path": "C:/Users/me/project/tests/run.log",    "kind": 1}
  ],
  "count": 2
}
```

An empty `name_seed` is valid for `post_list_entries` (non-destructive) and returns every
entry of the requested kind under the path.

### Example — metadata for a single path

```json
// POST /metadata  (or MCP tool: post_entry_metadata)
{
  "path": "C:/Users/me/project/build/output.log"
}
```

```json
// Response
{
  "path": "C:/Users/me/project/build/output.log",
  "type": "file",
  "size_bytes": 4096,
  "mtime": 1718000000.0,
  "exists": true
}
```

---

## Workflow: save a listing to disk

Call `post_save_listing` to write the matched-entry list to a `.txt` file in the scanned
root. This is a safe write — no entries are removed or compressed.

```json
// POST /listing  (or MCP tool: post_save_listing)
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": "report",
  "case_sensitive": false
}
```

```json
// Response
{
  "listing_path": "C:/Users/me/project/directory-fl-report.txt"
}
```

The output file is named `directory-<fl|fd>[-<seed>].txt` (`fl` for files, `fd` for
folders). It is written into the scanned root, one absolute path per line.

---

## Workflow: preview then remove

Always call with `dry_run: true` (the default) first to inspect the match list before
committing.

### Step 1 — preview

```json
// POST /remove  (or MCP tool: post_remove)
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": "old_",
  "dry_run": true,
  "confirm": false
}
```

```json
// Response — nothing was removed
{
  "dry_run": true,
  "matched": [
    "C:/Users/me/project/src/old_utils.py",
    "C:/Users/me/project/src/old_config.py"
  ],
  "removed": [],
  "failed": [],
  "would_affect": [
    "C:/Users/me/project/src/old_utils.py",
    "C:/Users/me/project/src/old_config.py"
  ]
}
```

### Step 2 — live remove (after reviewing the preview list)

```json
// POST /remove  (or MCP tool: post_remove)
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": "old_",
  "dry_run": false,
  "confirm": true
}
```

```json
// Response — entries moved to recycle bin
{
  "dry_run": false,
  "matched": [
    "C:/Users/me/project/src/old_utils.py",
    "C:/Users/me/project/src/old_config.py"
  ],
  "removed": [
    "C:/Users/me/project/src/old_utils.py",
    "C:/Users/me/project/src/old_config.py"
  ],
  "failed": [],
  "would_affect": [
    "C:/Users/me/project/src/old_utils.py",
    "C:/Users/me/project/src/old_config.py"
  ]
}
```

---

## Workflow: preview then compress

The compress workflow mirrors remove. Originals are permanently deleted after compression
(the zip is the recovery mechanism).

### Step 1 — preview

```json
// POST /compress  (or MCP tool: post_compress)
{
  "path": "C:/Users/me/project",
  "kind": 0,
  "name_seed": "archive_",
  "dry_run": true,
  "confirm": false
}
```

```json
// Response — nothing was compressed
{
  "dry_run": true,
  "matched": [
    "C:/Users/me/project/archive_2025",
    "C:/Users/me/project/archive_2024"
  ],
  "archives": [],
  "failed": [],
  "would_affect": [
    "C:/Users/me/project/archive_2025",
    "C:/Users/me/project/archive_2024"
  ]
}
```

### Step 2 — live compress (after reviewing the preview list)

```json
// POST /compress  (or MCP tool: post_compress)
{
  "path": "C:/Users/me/project",
  "kind": 0,
  "name_seed": "archive_",
  "dry_run": false,
  "confirm": true
}
```

```json
// Response — folders compressed, originals deleted
{
  "dry_run": false,
  "matched": [
    "C:/Users/me/project/archive_2025",
    "C:/Users/me/project/archive_2024"
  ],
  "archives": [
    "C:/Users/me/project/archive_2025.zip",
    "C:/Users/me/project/archive_2024.zip"
  ],
  "failed": [],
  "would_affect": [
    "C:/Users/me/project/archive_2025",
    "C:/Users/me/project/archive_2024"
  ]
}
```

Compression layout:

- `kind: 1` (FILES mode): all matched files are compressed into a single
  `Compressed_data.zip` placed directly in `path`.
- `kind: 0` (FOLDERS mode): each matched folder is compressed into its own
  `<folder_name>.zip` placed directly in `path`.

---

## Input/output reference

### Common parameters

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `path` | string | yes | — | Absolute path to an existing directory. |
| `kind` | integer | yes | — | `0` = folders, `1` = files. |
| `name_seed` | string | yes (destructive) / no (query) | `""` | Substring filter. Blank matches everything (safe for query; rejected for destructive). |
| `case_sensitive` | boolean | no | `true` | When `false`, matching lowercases both sides. |

### POST /entries — ListEntriesResponse

| Field | Type | Notes |
|-------|------|-------|
| `entries` | array of `{path: string, kind: int}` | Ordered top-down, breadth-first. |
| `count` | integer | Length of `entries`. |

### POST /metadata — metadata response

| Field | Type | Notes |
|-------|------|-------|
| `path` | string | Absolute resolved path. |
| `type` | string | `"file"` / `"directory"` / `"symlink"` / `"other"`. |
| `size_bytes` | integer | File size in bytes; 0 for directories. |
| `mtime` | float | Last-modification time, epoch seconds. |
| `exists` | boolean | Always `true` (404 is returned if the path does not exist). |

### POST /listing — SaveListingResponse

| Field | Type | Notes |
|-------|------|-------|
| `listing_path` | string | Absolute path of the written `.txt` file. |

### POST /remove — RemoveResponse

| Field | Type | Notes |
|-------|------|-------|
| `dry_run` | boolean | Mirrors the request `dry_run` flag. |
| `matched` | array of string | All paths that matched the filter. |
| `removed` | array of string | Paths successfully removed (empty when `dry_run: true`). |
| `failed` | array of `[path, error_message]` | Removal errors, if any. |
| `would_affect` | array of string | Same as `matched` (preview alias). |

### POST /compress — CompressResponse

| Field | Type | Notes |
|-------|------|-------|
| `dry_run` | boolean | Mirrors the request `dry_run` flag. |
| `matched` | array of string | All paths that matched the filter. |
| `archives` | array of string | Zip archive paths created (empty when `dry_run: true`). |
| `failed` | array of `[path, error_message]` | Compression/deletion errors, if any. |
| `would_affect` | array of string | Same as `matched` (preview alias). |

### Destructive-only parameters

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `dry_run` | boolean | no | `true` | `true` = preview only, no filesystem mutation. |
| `confirm` | boolean | no | `false` | Must be `true` together with `dry_run: false` to actually mutate. |

---

## The confirm-token contract (concrete JSON)

### Preview — safe, idempotent, recommended first step

```json
{
  "path": "<root_directory>",
  "kind": 1,
  "name_seed": "<non-empty-seed>"
}
```

(Omitting `dry_run` and `confirm` is equivalent to `"dry_run": true, "confirm": false`.)

### Live run — requires both flags explicitly

```json
{
  "path": "<root_directory>",
  "kind": 1,
  "name_seed": "<non-empty-seed>",
  "dry_run": false,
  "confirm": true
}
```

### What triggers HTTP 422 (or MCP `isError: true`)

```json
// Blank seed — EmptySeedError
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": "",
  "dry_run": false,
  "confirm": true
}
// → 422: {"error": "EmptySeedError", "message": "remove_entries() requires a non-empty name_seed. ..."}
```

```json
// confirm missing while dry_run=false — ValueError
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": "old_",
  "dry_run": false,
  "confirm": false
}
// → 422: "remove_entries() requires confirm=True when dry_run=False. ..."
```

---

## Error table

| Error condition | HTTP status | MCP `isError` | `detail` shape |
|----------------|-------------|---------------|----------------|
| Blank / whitespace `name_seed` on `/remove` or `/compress` | 422 | true | `{"error": "EmptySeedError", "message": "..."}` |
| `dry_run=false` without `confirm=true` | 422 | true | plain string (ValueError message) |
| `path` not an existing directory | 422 | true | plain string (ValueError message) |
| `path` does not exist (for `/metadata`) | 404 | true | plain string (FileNotFoundError message) |
| `kind` not `0` or `1` | 422 | true | Pydantic validation error |

On a 422 / `isError: true` response:

- Check that `name_seed` is non-empty (use `post_list_entries` first to enumerate candidates).
- Check that both `dry_run: false` AND `confirm: true` are present for live runs.
- Check that `path` is an existing directory.

---

## What the agent does NOT control

- **The GUI** (`ff-explorer-gui`) — the PySide6 desktop application is a separate entry
  point and is not driven via the API.
- **The packaging build** (`packaging/`) — the PyInstaller executable is a build artifact,
  not an agent-accessible surface. See `packaging/README-packaging.md` for build
  instructions.
- **The legacy Tkinter entry point** (`FF_UI.pyw`) — not connected to the API layer.
