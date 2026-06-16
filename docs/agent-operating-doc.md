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
10. [Search filters and options](#search-filters-and-options)
11. [Presets, duplicates, rename, and indexing](#presets-duplicates-rename-and-indexing)
12. [The confirm-token contract (concrete JSON)](#the-confirm-token-contract-concrete-json)
13. [Error table](#error-table)
14. [What the agent does NOT control](#what-the-agent-does-not-control)

---

## What this repo does for agents

FF-Explorer exposes a **filesystem-manipulation service** with 14 operations across 7 capability areas:

### Query (non-destructive)
- **List entries** — match files/folders by name (substring/glob/regex), with optional filters: size range,
  modification date range, extensions, content search (gated), ignore-file awareness, archive transparency.
- **Entry metadata** — inspect path, type, size, modification time.
- **Find duplicates** — group files by content hash; identify removable duplicates.
- **Largest files** — return top-N files by size across the tree.

### Safe write
- **Save listing** — write matched-entry list to a `.txt` index file in the scanned root.

### Destructive (guarded — dry-run by default, require confirm)
- **Remove entries** — move to recycle bin (default) or versioned archive; dry-run preview.
- **Compress entries** — create zip archive(s), then delete originals; dry-run preview.
- **Rename entries** — batch rename with collision detection, undo file; dry-run preview.

### Presets (automation)
- **Save preset** — persist a named query/action bundle.
- **List presets** — enumerate saved presets.
- **Run preset** — execute a named preset (destructive presets follow the dry-run/confirm gate).

### Indexing (performance opt-in)
- **Start index** — build in-memory name index + watchdog observer for real-time updates.
- **Stop index** — drop index and stop observer.
- **Index status** — query whether a root is currently indexed.

All 14 operations are exposed identically through the REST API and the 15-tool MCP set.

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

All 15 tools are available on both the Streamable HTTP MCP endpoint (`/mcp`) and the
stdio MCP server.

| MCP tool name | REST route | Description |
|---------------|------------|-------------|
| `health_health_get` | `GET /health` | Liveness and version check |
| `post_list_entries_entries_post` | `POST /entries` | List matching entries with search/filter options — non-destructive |
| `post_entry_metadata_metadata_post` | `POST /metadata` | Entry metadata (path, type, size, mtime, exists) |
| `post_save_listing_listing_post` | `POST /listing` | Write matched entries to a `.txt` listing file |
| `post_find_duplicates_duplicates_post` | `POST /duplicates` | Find duplicate files by content hash (FFX-I06) |
| `post_largest_entries_largest_post` | `POST /largest` | Top-N largest files, sorted descending by size (FFX-I11) |
| `post_remove_remove_post` | `POST /remove` | Remove matched entries — **dry-run by default** |
| `post_compress_compress_post` | `POST /compress` | Compress matched entries into zip(s) — **dry-run by default** |
| `post_rename_rename_post` | `POST /rename` | Batch rename matched entries — **dry-run by default** (FFX-I07) |
| `post_save_preset_presets_save_post` | `POST /presets/save` | Save (upsert) a named preset (FFX-I03) |
| `post_list_presets_presets_list_post` | `POST /presets/list` | List all stored presets (FFX-I03) |
| `post_run_preset_presets_run_post` | `POST /presets/run` | Execute a named preset (destructive presets are guarded) (FFX-I03) |
| `post_start_index_index_start_post` | `POST /index/start` | Build in-memory name index + start watchdog observer (FFX-I10) |
| `post_stop_index_index_stop_post` | `POST /index/stop` | Stop index + observer for a root (FFX-I10) |
| `post_index_status_index_status_post` | `POST /index/status` | Query indexing status for a root (FFX-I10) |

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

## Search filters and options

`POST /entries` supports advanced search and filtering beyond name matching:

### Match mode
- `match_mode: "substring"` (default) — current case-aware `in` test.
- `match_mode: "glob"` — fnmatch-style wildcards (`*.log`, `test_*.py`, etc.).
- `match_mode: "regex"` — full regex matching; invalid patterns return HTTP 422 / `InvalidRegexError`.

### File metadata filters
All are optional; all combine with AND logic (name match PLUS all active predicates):
- `min_size`, `max_size` — bytes range (inclusive). Applies to files; directories always pass.
- `modified_after`, `modified_before` — epoch float (seconds since Unix epoch). Applies to mtime.
- `extensions` — list of file extensions to match (case-insensitive; leading dot optional).
  Example: `[".log", "txt"]`. Applies to files; directories always pass.

### Archive transparency
- `search_archives: true` — treat ZIP/TAR/GZ/BZ2 files as navigable containers. Results include
  internal members as read-only paths (e.g., `archive.zip!member/name`). Default: false.
- Archive-internal paths cannot be passed to destructive operations (remove/compress/rename).

### Content search (grep-inside-files)
- `content_query: "search_string"` — find files whose contents contain the query (substring or regex).
- **Gating requirement:** At least one name/type/size pre-filter must be active. Sending
  `content_query` without `name_seed`, `extensions`, `min_size`, `max_size`, `modified_after`,
  or `modified_before` returns HTTP 422 / `ContentSearchUngatedError`.
- `content_max_bytes` — max file size to scan during content search (default: 1 MB).
  Binaries (detected by null-byte heuristic) are skipped.

### Gitignore/ignore-file awareness
- `respect_ignore: true` — skip paths matching `.gitignore`, `.ignore`, or custom patterns.
  Default: false.
- `ignore_globs: ["pattern1", "pattern2"]` — additional ignore patterns (optional).

---

## Presets, duplicates, rename, and indexing

### Presets (FFX-I03)
Save and reuse query/action bundles:

```json
// POST /presets/save
{
  "name": "my-old-logs",
  "path": "C:/Users/me/logs",
  "kind": 1,
  "name_seed": "old_",
  "match_mode": "substring",
  "min_size": 1000000,
  "operation": "list"  // or "remove" / "compress"
}
// → HTTP 204 (no body)
```

Execute a saved preset:

```json
// POST /presets/run
{
  "name": "my-old-logs",
  "dry_run": true,      // if operation is "remove" or "compress"
  "confirm": false      // if operation is "remove" or "compress"
}
```

Destructive presets (operation: "remove" or "compress") follow the same `dry_run`/`confirm` gate.

### Find duplicates (FFX-I06)
Identify files with identical content:

```json
// POST /duplicates
{
  "path": "C:/Users/me/documents",
  "min_size": 1000,     // only scan files ≥ 1000 bytes
  "algo": "sha256"      // hash algorithm (default: "sha256")
}
// Response: {"groups": [{"hash": "...", "size": 1024, "paths": [...]}, ...], "count": N}
```

Each group contains 2+ files with the same content. Use `/remove` or `/compress` to deduplicate.

### Batch rename (FFX-I07)
Rename matched entries with collision detection:

```json
// POST /rename
{
  "path": "C:/Users/me/project",
  "kind": 1,
  "name_seed": "old_",
  "rules": [
    {"rule_type": "prefix", "prefix": "archive_"},
    {"rule_type": "find_replace", "find": "old_", "replace": "new_"}
  ],
  "dry_run": true,
  "confirm": false
}
// Response includes mapping (old→new names), collisions, undo_file
```

Live rename creates a reverse-mapping undo file.

### Real-time indexing (FFX-I10)
Build an in-memory index for instant queries:

```json
// POST /index/start
{"path": "C:/Users/me/huge_tree"}
// → HTTP 200: {"root": "...", "indexed": true}
```

After indexing starts, queries against this root use the index instead of walking the tree.
Changes (create/rename/delete) are tracked by the watchdog observer and applied incrementally.

```json
// POST /index/status
{"path": "C:/Users/me/huge_tree"}
// → HTTP 200: {"root": "...", "indexed": true}
```

```json
// POST /index/stop
{"path": "C:/Users/me/huge_tree"}
// → HTTP 200: {"root": "...", "indexed": false}
```

---

## Input/output reference

### Common parameters (all routes)

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `path` | string | yes | — | Absolute path to an existing directory. |

### Query parameters (for `/entries` and related query routes)

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `kind` | integer | yes | — | `0` = folders, `1` = files. |
| `name_seed` | string | no | `""` | Substring/glob/regex filter (depends on `match_mode`). Blank matches everything. |
| `case_sensitive` | boolean | no | `true` | When `false`, matching lowercases both sides. |
| `match_mode` | string | no | `"substring"` | `"substring"`, `"glob"`, or `"regex"`. |
| `min_size` | integer | no | `null` | Minimum file size in bytes (inclusive). Files ≥ `min_size` only. |
| `max_size` | integer | no | `null` | Maximum file size in bytes (inclusive). Files ≤ `max_size` only. |
| `modified_after` | float | no | `null` | Epoch float (seconds since Unix epoch). Modified after this timestamp. |
| `modified_before` | float | no | `null` | Epoch float (seconds since Unix epoch). Modified before this timestamp. |
| `extensions` | array of string | no | `null` | File extensions to match (e.g., `[".txt", "log"]`). Case-insensitive. Applies to files only. |
| `respect_ignore` | boolean | no | `false` | When `true`, skip paths matching `.gitignore` / `.ignore`. |
| `ignore_globs` | array of string | no | `null` | Additional ignore patterns (combined with gitignore if `respect_ignore: true`). |
| `search_archives` | boolean | no | `false` | When `true`, search inside ZIP/TAR/GZ/BZ2 archives as containers. |
| `content_query` | string | no | `null` | Grep-inside-files search (requires a pre-filter: `name_seed`, `extensions`, or size bound). |
| `content_max_bytes` | integer | no | `1048576` | Max file size to scan during content search (1 MB default). |

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
| `versioned_to` | string or null | When `versioning: true` and `dry_run: false`, the timestamped version directory (e.g., `<root>/.ffe-versions/YYYYMMDD-HHMMSS`). Null for dry-run or when `versioning: false`. |

**Versioning parameter (FFX-I08):**

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `versioning` | boolean | no | `false` | When `true`, move removed entries to `.ffe-versions/<timestamp>/` instead of recycle bin. Same `dry_run`/`confirm` gate applies. |

### POST /compress — CompressResponse

| Field | Type | Notes |
|-------|------|-------|
| `dry_run` | boolean | Mirrors the request `dry_run` flag. |
| `matched` | array of string | All paths that matched the filter. |
| `archives` | array of string | Zip archive paths created (empty when `dry_run: true`). |
| `failed` | array of `[path, error_message]` | Compression/deletion errors, if any. |
| `would_affect` | array of string | Same as `matched` (preview alias). |

### Destructive-only parameters (for `/remove`, `/compress`, `/rename`, `/presets/run`)

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `dry_run` | boolean | no | `true` | `true` = preview only, no filesystem mutation. |
| `confirm` | boolean | no | `false` | Must be `true` together with `dry_run: false` to actually mutate. |
| `versioning` | boolean | no | `false` | (remove only) Move to `.ffe-versions/<timestamp>/` instead of recycle bin. |

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

| Error condition | HTTP status | MCP `isError` | Notes |
|----------------|-------------|---------------|-------|
| Blank / whitespace `name_seed` on destructive ops | 422 | true | `EmptySeedError` — destructive ops only |
| `dry_run=false` without `confirm=true` | 422 | true | ValueError — both flags required simultaneously |
| `content_query` without pre-filter (name/type/size) | 422 | true | `ContentSearchUngatedError` — performance gate |
| Invalid regex pattern (with `match_mode: "regex"`) | 422 | true | `InvalidRegexError` — compile failed |
| `path` not an existing directory (for query/destructive) | 422 | true | ValueError — path validation |
| `path` does not exist (for `/metadata` / `/index/*`) | 404 | true | FileNotFoundError |
| `kind` not `0` or `1` | 422 | true | Pydantic validation error |
| `watchdog` not installed (for `/index/start`) | 422 | true | ImportError → 422 |
| Preset name not found (for `/presets/run`) | 404 | true | KeyError → 404 |
| Name collision detected (for `/rename`) | 422 | true | ValueError — returned in `collisions` field, no rename applied |

On a 422 / `isError: true` response:

- Check that `name_seed` is non-empty (use `post_list_entries` first to enumerate candidates).
- Check that both `dry_run: false` AND `confirm: true` are present for live destructive runs.
- Check that `path` is an existing directory.
- For `content_query`: ensure at least one name/type/size pre-filter is active.
- For `match_mode: "regex"`: validate the regex pattern with a test tool first.

---

## What the agent does NOT control

- **The GUI** (`ff-explorer-gui`) — the PySide6 desktop application is a separate entry
  point and is not driven via the API.
- **The packaging build** (`packaging/`) — the PyInstaller executable is a build artifact,
  not an agent-accessible surface. See `packaging/README-packaging.md` for build
  instructions.
