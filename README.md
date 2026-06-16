# FF-Explorer

FF-Explorer (Files/Folders Explorer) is a Windows-first desktop utility that recursively
walks a chosen root directory and returns every folder or file matching a search pattern (substring,
glob, or regex). It can filter results by size, modification date, extension, and file content.
Against the matched list it can **save** a plain-text index, **remove** items (via recycle bin or
versioned archive), **compress** them into zip archives, **rename** them in batch, **find
duplicates** by content hash, or **index** for real-time updates.

Three surfaces are provided:

| Surface | What it is |
|---------|------------|
| **PySide6 GUI** | Interactive desktop window; entry point `ff-explorer-gui` |
| **REST + MCP access layer** | Headless FastAPI/FastMCP server; drives all operations without the GUI |
| **Packaged executable** | Self-contained one-dir build (`packaging/bin/FFExplorer/FFExplorer.exe`) |

---

## Safety — read before using destructive operations

FF-Explorer can **delete** and **compress-then-delete** matched entries. Three hard guards
prevent accidental data loss:

### 1 — Non-empty name seed is mandatory for destructive operations

Passing a blank or whitespace-only `name_seed` to `remove_entries` or `compress_entries`
raises `EmptySeedError` immediately. No filesystem access occurs. This guard exists because
an empty seed would match *every* entry under the path.

REST equivalent: a blank `name_seed` field on `POST /remove` or `POST /compress` returns
**HTTP 422** with `{"error": "EmptySeedError", "message": "..."}`.

### 2 — dry_run defaults to True

Every destructive call is a **preview by default**. Calling `POST /remove` or
`POST /compress` (or the equivalent MCP tools `post_remove` / `post_compress`) without
explicitly setting `"dry_run": false` returns the matched-paths list and changes nothing.

### 3 — confirm=true is required for a live run

To actually mutate the filesystem, the request body must contain **both** flags together:

```json
{
  "dry_run": false,
  "confirm": true
}
```

Sending only one of the two flags is not sufficient. The confirm flag is the explicit
opt-in token that prevents accidental live runs from tooling that omits defaults.

### 4 — Deletes go to the recycle bin

When `send2trash` is installed (it is a declared dependency and is bundled in the packaged
executable), matched items are moved to the OS recycle bin — not permanently unlinked.
This makes remove operations recoverable from the shell.

### Quick reference — exact 422 patterns

| Trigger | HTTP status | `detail` shape |
|---------|-------------|----------------|
| Blank/whitespace `name_seed` on `/remove` or `/compress` | 422 | `{"error": "EmptySeedError", "message": "..."}` |
| `dry_run=false` without `confirm=true` | 422 | plain string from `ValueError` |
| Non-existent or non-directory `path` | 422 | plain string from `ValueError` |
| `path` does not exist for `/metadata` | 404 | plain string from `FileNotFoundError` |

---

## Requirements

- Python **3.11** or later (build/CI ceiling: Python **3.13**)
- Windows primary; POSIX paths work for the core and access layer
- Core dependencies: `send2trash` (recycle-bin routing), `PySide6` (GUI), `pathspec` (gitignore support), `watchdog` (real-time indexing)

---

## Installation

```bash
# Core + GUI only
pip install ff-explorer

# Core + GUI + REST/MCP access layer
pip install "ff-explorer[api]"

# Full development toolchain (pytest, coverage, PyInstaller)
pip install "ff-explorer[dev]"
```

---

## Entry points

### Desktop GUI

```bash
ff-explorer-gui
```

Launches the PySide6 desktop window. Choose a root directory, enter a name seed, select
match mode (substring / glob / regex), apply filters (size, date, extensions, content search,
archives, ignore files), pick an action, and press Run. Preview-then-confirm for destructive ops.
Actions include: List / Save / Remove (recycle bin or versioned) / Compress / Rename / Find
Duplicates / Disk Usage View / Create/Load Presets / Index Management.

### REST + MCP access layer (Streamable HTTP)

```bash
pip install "ff-explorer[api]"
ff-explorer-api
# Server ready at http://localhost:8000
# REST docs:        http://localhost:8000/docs
# MCP endpoint:     http://localhost:8000/mcp
```

All 14 REST routes (query, destructive, presets, index) plus 15 derived MCP tools are available.
The access layer is the recommended interface for automation, scripting, and agent-driven workflows.

### MCP stdio transport (agent / Claude Desktop)

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

### Packaged executable (no Python required)

A pre-built one-dir executable is available in `packaging/bin/FFExplorer/`:

```bat
packaging\bin\FFExplorer\FFExplorer.exe
```

To rebuild from source:

```bat
REM Windows — from the repo root
py -3.13 -m pip install "pyinstaller~=6.20.0" "PySide6~=6.11.1" Pillow
packaging\build_windows.bat
```

See `packaging/README-packaging.md` for full build instructions and Linux/macOS variants.

---

## REST API quick reference

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/health` | Liveness and version check |
| `POST` | `/entries` | List matching entries (non-destructive) |
| `POST` | `/metadata` | File/folder metadata for a single path |
| `POST` | `/listing` | Walk and write a `.txt` listing file |
| `POST` | `/remove` | Remove matched entries — **dry-run by default** |
| `POST` | `/compress` | Compress matched entries into zip(s) — **dry-run by default** |

Interactive documentation (OpenAPI/Swagger): `http://localhost:8000/docs`

---

## Development

```bash
pip install "ff-explorer[dev]"

# Run the full test suite (97 % core coverage, 140 tests)
pytest

# Run with explicit coverage report
pytest --cov=ff_explorer --cov-report=term-missing
```

---

## License

GPLv3 — see `LICENSE`.

This software includes PySide6, distributed under the LGPLv3 / GPL-2.0 / GPL-3.0.
See `packaging/README-packaging.md` for Qt license obligations.
