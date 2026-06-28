"""
ff_explorer.api.rest
=====================
FastAPI REST application over the shared ``service`` module.

Routes (18 total, 17 POST + 1 GET)
-----------------------------------
GET  /health                            — liveness + version.

Query (non-destructive):
POST /entries                           — list matching entries with search/filter/content options.
POST /list_with_report                  — list entries + skip report (SPEC-15).
POST /metadata                          — entry metadata (path, type, size, mtime, exists).
POST /listing                           — write a .txt listing (safe write).
POST /duplicates                        — find duplicate files by content hash (FFX-I06).
POST /largest                           — top-N largest files, sorted descending by size (FFX-I11).

Destructive (GUARDED — dry-run by default):
POST /remove                            — remove matched entries; moves to recycle bin or version archive.
POST /compress                          — compress matched entries; optionally version originals.
POST /rename                            — batch rename matched entries.
POST /copy                              — copy matched entries to a destination directory (SPEC-18).
POST /move                              — move matched entries to a destination directory (SPEC-18).

Presets (FFX-I03):
POST /presets/save                      — save (upsert) a named preset.
POST /presets/list                      — list all stored presets.
POST /presets/run                       — execute a named preset (destructive presets are guarded).

Index lifecycle (FFX-I10, non-destructive):
POST /index/start                       — build in-memory name index + start watchdog observer.
POST /index/stop                        — stop index + observer for a root.
POST /index/status                      — query indexing status for a root.

Hard-guard contract for destructive routes
------------------------------------------
``POST /remove``, ``POST /compress``, and ``POST /rename`` default to
**dry-run** mode: calling them without ``"dry_run": false, "confirm": true``
returns the ``.matched``/``.would_affect`` preview list and mutates nothing.

To actually mutate, the request body MUST contain both:
  ``"dry_run": false``   — explicitly disable the preview
  ``"confirm": true``    — explicit opt-in token

If either flag is missing or the wrong value, the core enforces the guard
and the route returns HTTP 422 with a structured explanation.

Empty ``name_seed`` is rejected for destructive operations — HTTP 422 with a
structured body naming the violation (``EmptySeedError`` from the core).

All routes delegate entirely to ``ff_explorer.api.service``.
Errors are mapped:
  ``EmptySeedError``    → HTTP 422 with ``{"detail": "...", "error": "EmptySeedError"}``
  ``ValueError``        → HTTP 422 with ``{"detail": "..."}``
  ``FileNotFoundError`` → HTTP 404 with ``{"detail": "..."}``

This module exposes a bare ``FastAPI`` instance (``app``).  Composition with
MCP routes happens in ``main.py`` so this module stays importable and
testable without the MCP stack.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from ff_explorer import __version__
from ff_explorer.core import EmptySeedError
from ff_explorer.api import service
from ff_explorer.api.service import ContentSearchUngatedError, CONTENT_MAX_BYTES

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FF-Explorer REST API",
    version=__version__,
    description=(
        "REST interface over the FF-Explorer pure core.  "
        "External agents can drive all file/folder operations without launching the GUI.  "
        "Destructive routes (remove, compress) default to dry-run preview mode; "
        "pass dry_run=false + confirm=true to actually mutate."
    ),
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Result of GET /health."""
    status: str
    version: str


class MatchEntryOut(BaseModel):
    """A single matched entry (serialisable form of core.MatchEntry)."""
    path: str
    kind: int  # 0=FOLDERS, 1=FILES
    in_archive: bool = False  # True when this hit is an archive-internal member (FFX-I05)


class ListEntriesRequest(BaseModel):
    """Body for POST /entries."""
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = ""
    case_sensitive: bool = True
    match_mode: Literal["substring", "glob", "regex"] = Field(
        default="substring",
        description=(
            "Name-matching strategy: "
            "'substring' (default) — case-aware 'in' test; "
            "'glob' — fnmatch wildcards (*, ?, [seq]); "
            "'regex' — full Python regex (InvalidRegexError→422 on bad pattern)."
        ),
    )
    min_size: int | None = Field(
        default=None,
        ge=0,
        description="Minimum file size in bytes (inclusive). Files only; None = no lower bound.",
    )
    max_size: int | None = Field(
        default=None,
        ge=0,
        description="Maximum file size in bytes (inclusive). Files only; None = no upper bound.",
    )
    modified_after: float | None = Field(
        default=None,
        description="Epoch seconds; only entries with mtime strictly after this are returned. None = no bound.",
    )
    modified_before: float | None = Field(
        default=None,
        description="Epoch seconds; only entries with mtime strictly before this are returned. None = no bound.",
    )
    extensions: list[str] | None = Field(
        default=None,
        description=(
            "Extension filter, e.g. [\".txt\", \"log\"]. "
            "Matched case-insensitively. Files only; None = no filter."
        ),
    )
    respect_ignore: bool = Field(
        default=False,
        description=(
            "When true, discover and honour .gitignore / .ignore files during "
            "the walk (nested precedence; ignored directories are pruned). "
            "Default false preserves legacy output."
        ),
    )
    ignore_globs: list[str] | None = Field(
        default=None,
        description=(
            "Additional gitwildmatch glob patterns always excluded when provided, "
            "e.g. [\"*.tmp\", \"build/\"]. None = no extra exclusions."
        ),
    )
    search_archives: bool = Field(
        default=False,
        description=(
            "When true (FILES mode only), open each encountered archive "
            "(.zip, .tar, .tar.gz/.tgz, .tar.bz2) read-only and match "
            "internal member names against name_seed.  Hits are returned with "
            "in_archive=true and path of the form '<archive_path>!<member/name>'. "
            "Malformed archives are skipped silently.  Default false preserves "
            "legacy output exactly (FFX-I05).  Never enabled on destructive routes."
        ),
    )
    content_query: str | None = Field(
        default=None,
        description=(
            "FFX-I09: Optional grep-style content search.  When set, only files "
            "whose text content matches this string (or regex when match_mode='regex', "
            "respecting case_sensitive) are returned.  Binary files (null-byte "
            "heuristic) and files exceeding content_max_bytes are skipped silently.  "
            "REQUIRES at least one name/type/size pre-filter to be active "
            "(non-empty name_seed, extensions, min_size, max_size, modified_after, "
            "or modified_before); omitting all pre-filters raises HTTP 422 "
            "(ContentSearchUngatedError)."
        ),
    )
    content_max_bytes: int = Field(
        default=CONTENT_MAX_BYTES,
        ge=1,
        description=(
            "FFX-I09: Maximum file size in bytes scanned for content matching.  "
            f"Files larger than this cap are skipped silently.  "
            f"Default {CONTENT_MAX_BYTES} bytes (10 MiB).  "
            "Ignored when content_query is None."
        ),
    )
    include_hidden: bool = Field(
        default=True,
        description=(
            "SPEC-17: When True (default), hidden and system entries are included — "
            "identical to pre-SPEC-17 behaviour (no regression).  When False, "
            "hidden/system entries are excluded: POSIX dotfiles (names starting "
            "with '.') and Windows entries marked FILE_ATTRIBUTE_HIDDEN or "
            "FILE_ATTRIBUTE_SYSTEM.  Default True preserves the existing output exactly."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "C:/Users/me/Documents", "kind": 1,
                 "name_seed": "report", "case_sensitive": True,
                 "match_mode": "substring"},
                {"path": "C:/Users/me/Documents", "kind": 1,
                 "name_seed": r"^report.*\.txt$", "case_sensitive": False,
                 "match_mode": "regex"},
                {"path": "C:/Users/me/Documents", "kind": 1,
                 "name_seed": "", "match_mode": "substring",
                 "min_size": 1024, "max_size": 10485760, "extensions": [".pdf", ".docx"]},
                {"path": "C:/Users/me/Documents", "kind": 1,
                 "name_seed": "", "include_hidden": False,
                 "description": "Exclude dotfiles and hidden/system entries"},
            ]
        }
    }


class ListEntriesResponse(BaseModel):
    """Result of POST /entries."""
    entries: list[MatchEntryOut]
    count: int


class MetadataRequest(BaseModel):
    """Body for POST /metadata."""
    path: str

    model_config = {
        "json_schema_extra": {"examples": [{"path": "C:/Users/me/Documents/notes.txt"}]}
    }


class SaveListingRequest(BaseModel):
    """Body for POST /listing."""
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = ""
    case_sensitive: bool = True

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "C:/Users/me/Documents", "kind": 1,
                 "name_seed": "report", "case_sensitive": True}
            ]
        }
    }


class SaveListingResponse(BaseModel):
    """Result of POST /listing."""
    listing_path: str


# ---------------------------------------------------------------------------
# Destructive operation models — confirm-token contract is explicit here
# ---------------------------------------------------------------------------

class RemoveRequest(BaseModel):
    """Body for POST /remove.

    Dry-run default
    ~~~~~~~~~~~~~~~
    Omitting ``dry_run`` / ``confirm`` (or sending ``dry_run: true``) returns
    the preview list without touching the filesystem.

    To actually remove, send **both**:
      - ``"dry_run": false``
      - ``"confirm": true``
    """
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = Field(..., min_length=1,
                           description="Non-empty seed required — empty seed would match everything")
    case_sensitive: bool = True
    dry_run: bool = Field(
        default=True,
        description="When true (default) return a preview list; nothing is removed.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit opt-in token.  Must be true together with dry_run=false "
            "to actually remove entries.  Has no effect when dry_run=true."
        ),
    )
    versioning: bool = Field(
        default=False,
        description=(
            "When true, a confirmed removal MOVES matches into a timestamped "
            "<path>/.ffe-versions/<YYYYMMDD-HHMMSS>/ directory (structure preserved) "
            "instead of the OS recycle bin.  Default false = recycle-bin behaviour.  "
            "Does NOT relax the dry_run/confirm gate."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Preview (safe, default)",
                    "value": {"path": "C:/tmp/test", "kind": 1,
                              "name_seed": "old_", "dry_run": True, "confirm": False},
                },
                {
                    "summary": "Actually remove (requires both flags)",
                    "value": {"path": "C:/tmp/test", "kind": 1,
                              "name_seed": "old_", "dry_run": False, "confirm": True},
                },
                {
                    "summary": "Versioned remove — moves to .ffe-versions/ instead of recycle bin",
                    "value": {"path": "C:/tmp/test", "kind": 1,
                              "name_seed": "old_", "dry_run": False, "confirm": True,
                              "versioning": True},
                },
            ]
        }
    }


class RemoveResponse(BaseModel):
    """Result of POST /remove."""
    dry_run: bool
    matched: list[str]
    removed: list[str]
    failed: list[tuple[str, str]]
    would_affect: list[str]
    versioned_to: str | None = None


class CompressRequest(BaseModel):
    """Body for POST /compress.

    Dry-run default
    ~~~~~~~~~~~~~~~
    Omitting ``dry_run`` / ``confirm`` (or sending ``dry_run: true``) returns
    the preview list without touching the filesystem.

    To actually compress, send **both**:
      - ``"dry_run": false``
      - ``"confirm": true``
    """
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = Field(..., min_length=1,
                           description="Non-empty seed required — empty seed would match everything")
    case_sensitive: bool = True
    dry_run: bool = Field(
        default=True,
        description="When true (default) return a preview list; nothing is compressed.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit opt-in token.  Must be true together with dry_run=false "
            "to actually compress entries.  Has no effect when dry_run=true."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Preview (safe, default)",
                    "value": {"path": "C:/tmp/test", "kind": 0,
                              "name_seed": "archive_", "dry_run": True, "confirm": False},
                },
                {
                    "summary": "Actually compress (requires both flags)",
                    "value": {"path": "C:/tmp/test", "kind": 0,
                              "name_seed": "archive_", "dry_run": False, "confirm": True},
                },
            ]
        }
    }


class CompressResponse(BaseModel):
    """Result of POST /compress."""
    dry_run: bool
    matched: list[str]
    archives: list[str]
    failed: list[tuple[str, str]]
    would_affect: list[str]


# ---------------------------------------------------------------------------
# Batch rename models — FFX-I07
# ---------------------------------------------------------------------------

class RenameRuleIn(BaseModel):
    """A single composable rename rule (mirrors RenameRule dataclass).

    Each ``kind`` only requires its relevant ``params`` fields; unused fields
    should be omitted or left at their defaults.

    Supported kinds and their params
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``find_replace``   — ``find`` (str), ``replace`` (str, default "")
    ``regex_replace``  — ``pattern`` (str), ``replacement`` (str, default ""),
                         ``ignore_case`` (bool, default false)
    ``prefix``         — ``text`` (str) prepended to the stem (before extension)
    ``suffix``         — ``text`` (str) appended to the stem (before extension)
    ``case``           — ``mode`` one of "lower" (default), "upper", "title"
    ``counter``        — ``start`` (int, default 1), ``step`` (int, default 1),
                         ``padding`` (int, default 1),
                         ``template`` (str, default "{stem}{n}{suffix}")
    """
    kind: Literal[
        "find_replace", "regex_replace", "prefix", "suffix", "case", "counter"
    ] = Field(..., description="Rule kind — one of find_replace, regex_replace, prefix, suffix, case, counter.")

    # find_replace
    find: str | None = Field(default=None, description="find_replace: substring to find.")
    replace: str | None = Field(default=None, description="find_replace: replacement string.")

    # regex_replace
    pattern: str | None = Field(default=None, description="regex_replace: regex pattern.")
    replacement: str | None = Field(default=None, description="regex_replace: replacement string.")
    ignore_case: bool = Field(default=False, description="regex_replace: case-insensitive match.")

    # prefix / suffix
    text: str | None = Field(default=None, description="prefix/suffix: text to prepend/append to the stem.")

    # case
    mode: Literal["lower", "upper", "title"] | None = Field(
        default=None,
        description="case: transformation mode — 'lower', 'upper', or 'title'.",
    )

    # counter
    start: int | None = Field(default=None, description="counter: starting value (default 1).")
    step: int | None = Field(default=None, description="counter: increment per file (default 1).")
    padding: int | None = Field(default=None, description="counter: zero-pad width (default 1).")
    template: str | None = Field(
        default=None,
        description="counter: format template, e.g. '{stem}{n}{suffix}' (default).",
    )

    def to_rename_rule(self) -> "service.RenameRule":
        """Convert to the core RenameRule dataclass."""
        params: dict = {}
        if self.kind == "find_replace":
            if self.find is not None:
                params["find"] = self.find
            if self.replace is not None:
                params["replace"] = self.replace
        elif self.kind == "regex_replace":
            if self.pattern is not None:
                params["pattern"] = self.pattern
            if self.replacement is not None:
                params["replacement"] = self.replacement
            params["ignore_case"] = self.ignore_case
        elif self.kind in ("prefix", "suffix"):
            if self.text is not None:
                params["text"] = self.text
        elif self.kind == "case":
            if self.mode is not None:
                params["mode"] = self.mode
        elif self.kind == "counter":
            if self.start is not None:
                params["start"] = self.start
            if self.step is not None:
                params["step"] = self.step
            if self.padding is not None:
                params["padding"] = self.padding
            if self.template is not None:
                params["template"] = self.template
        return service.RenameRule(kind=self.kind, params=params)


class RenameRequest(BaseModel):
    """Body for POST /rename.

    Dry-run default
    ~~~~~~~~~~~~~~~
    Omitting ``dry_run`` / ``confirm`` (or sending ``dry_run: true``) returns
    the preview mapping without touching the filesystem.

    To actually rename, send **both**:
      - ``"dry_run": false``
      - ``"confirm": true``
    """
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = Field(
        ...,
        min_length=1,
        description="Non-empty seed required — empty seed would match everything",
    )
    case_sensitive: bool = True
    match_mode: Literal["substring", "glob", "regex"] = Field(
        default="substring",
        description="Name-matching strategy: 'substring' (default), 'glob', or 'regex'.",
    )
    rules: list[RenameRuleIn] = Field(
        ...,
        description="Ordered list of rename rules applied to each matched filename in sequence.",
    )
    dry_run: bool = Field(
        default=True,
        description="When true (default) return a preview mapping; nothing is renamed.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit opt-in token.  Must be true together with dry_run=false "
            "to actually rename entries.  Has no effect when dry_run=true."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Preview (safe, default)",
                    "value": {
                        "path": "C:/tmp/test", "kind": 1, "name_seed": "report",
                        "rules": [{"kind": "prefix", "text": "2024_"}],
                        "dry_run": True, "confirm": False,
                    },
                },
                {
                    "summary": "Actually rename (requires both flags)",
                    "value": {
                        "path": "C:/tmp/test", "kind": 1, "name_seed": "report",
                        "rules": [{"kind": "prefix", "text": "2024_"}],
                        "dry_run": False, "confirm": True,
                    },
                },
            ]
        }
    }


class RenameResponse(BaseModel):
    """Result of POST /rename."""
    dry_run: bool
    matched: list[str]
    mapping: list[tuple[str, str]]
    renamed: list[tuple[str, str]]
    collisions: list[str]
    failed: list[tuple[str, str]]
    undo_file: str | None


# ---------------------------------------------------------------------------
# Duplicate-detection models — FFX-I06
# ---------------------------------------------------------------------------

class DuplicateGroupOut(BaseModel):
    """A group of files with identical content (serialisable form of dedupe.DuplicateGroup)."""
    hash: str
    size: int
    paths: list[str]


class FindDuplicatesRequest(BaseModel):
    """Body for POST /duplicates."""
    path: str
    min_size: int = Field(default=1, ge=0,
                          description="Minimum file size in bytes (inclusive). Default 1 skips empty files.")
    algo: Literal["blake2b", "sha256"] = Field(
        default="blake2b",
        description="Hash algorithm for content comparison: 'blake2b' (default) or 'sha256'.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "C:/Users/me/Documents", "min_size": 1, "algo": "blake2b"},
            ]
        }
    }


class FindDuplicatesResponse(BaseModel):
    """Result of POST /duplicates."""
    groups: list[DuplicateGroupOut]
    count: int


# ---------------------------------------------------------------------------
# Preset models — FFX-I03
# ---------------------------------------------------------------------------

class PresetIn(BaseModel):
    """Body for POST /presets/save — mirrors the Preset dataclass fields."""
    name: str = Field(..., min_length=1, description="Unique preset name (non-empty).")
    path: str = Field(..., description="Root directory to walk when the preset is run.")
    kind: int = Field(default=1, ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = Field(default="", description="Pattern/substring filter.")
    case_sensitive: bool = Field(default=True, description="Case-sensitive name matching.")
    match_mode: Literal["substring", "glob", "regex"] = Field(
        default="substring",
        description="Name-matching strategy: 'substring', 'glob', or 'regex'.",
    )
    min_size: int | None = Field(default=None, ge=0, description="Min file size in bytes (inclusive).")
    max_size: int | None = Field(default=None, ge=0, description="Max file size in bytes (inclusive).")
    modified_after: float | None = Field(default=None, description="Epoch lower bound on mtime.")
    modified_before: float | None = Field(default=None, description="Epoch upper bound on mtime.")
    extensions: list[str] | None = Field(default=None, description="Extension filter list.")
    respect_ignore: bool = Field(default=False, description="Honour .gitignore/.ignore during walk.")
    ignore_globs: list[str] | None = Field(default=None, description="Extra gitwildmatch exclusion patterns.")
    operation: Literal["list", "remove", "compress"] = Field(
        default="list",
        description="Operation to run: 'list' (safe), 'remove' (guarded), or 'compress' (guarded).",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "find_reports",
                    "path": "C:/Users/me/Documents",
                    "kind": 1,
                    "name_seed": "report",
                    "case_sensitive": False,
                    "match_mode": "substring",
                    "operation": "list",
                }
            ]
        }
    }


class PresetOut(BaseModel):
    """Serialisable representation of a stored preset (response for POST /presets/list)."""
    name: str
    path: str
    kind: int
    name_seed: str
    case_sensitive: bool
    match_mode: str
    min_size: int | None
    max_size: int | None
    modified_after: float | None
    modified_before: float | None
    extensions: list[str] | None
    respect_ignore: bool
    ignore_globs: list[str] | None
    operation: str


class PresetListResponse(BaseModel):
    """Result of POST /presets/list."""
    presets: list[PresetOut]
    count: int


class PresetRunRequest(BaseModel):
    """Body for POST /presets/run.

    Dry-run default
    ~~~~~~~~~~~~~~~
    Omitting ``dry_run`` / ``confirm`` (or leaving ``dry_run: true``) returns a
    safe preview for destructive presets and the full entry list for 'list' presets.

    To actually mutate with a destructive preset, send **both**:
      - ``"dry_run": false``
      - ``"confirm": true``
    """
    name: str = Field(..., description="Name of the preset to execute.")
    dry_run: bool = Field(
        default=True,
        description="When true (default) return a preview for destructive presets; nothing is mutated.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit opt-in token for destructive presets.  Must be true together with "
            "dry_run=false to actually mutate.  Has no effect for 'list' presets."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Run a list preset (always safe)",
                    "value": {"name": "find_reports"},
                },
                {
                    "summary": "Preview a destructive preset (safe default)",
                    "value": {"name": "remove_old", "dry_run": True, "confirm": False},
                },
                {
                    "summary": "Execute a destructive preset (requires both flags)",
                    "value": {"name": "remove_old", "dry_run": False, "confirm": True},
                },
            ]
        }
    }


class PresetRunResponse(BaseModel):
    """Uniform envelope returned by POST /presets/run.

    Shape varies by the preset's ``operation`` field:

    * ``operation="list"``     — ``entries`` is populated; ``report`` is ``null``.
    * ``operation="remove"``   — ``report`` is populated (RemoveResponse shape); ``entries`` is ``null``.
    * ``operation="compress"`` — ``report`` is populated (CompressResponse shape); ``entries`` is ``null``.
    """
    operation: str
    entries: list[MatchEntryOut] | None = None
    report: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Size aggregation models — FFX-I11
# ---------------------------------------------------------------------------

class SizedEntryOut(BaseModel):
    """A single sized entry (serialisable form of core.SizedEntry)."""
    path: str
    size: int


class LargestEntriesRequest(BaseModel):
    """Body for POST /largest."""
    path: str
    top_n: int = Field(
        default=50,
        ge=1,
        description=(
            "Number of results to return (must be ≥ 1).  "
            "A value < 1 is rejected with HTTP 422."
        ),
    )
    name_seed: str = Field(
        default="",
        description=(
            "Optional substring filter on the filename.  "
            "Empty string (default) aggregates the whole tree.  "
            "Empty is allowed — this is a non-destructive query."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "C:/Users/me/Documents", "top_n": 10},
                {"path": "C:/Users/me/Documents", "top_n": 20, "name_seed": ".log"},
            ]
        }
    }


class LargestEntriesResponse(BaseModel):
    """Result of POST /largest."""
    entries: list[SizedEntryOut]
    count: int


# ---------------------------------------------------------------------------
# Copy / move models — SPEC-18 (gated destructive)
# ---------------------------------------------------------------------------

class TransferReportResponse(BaseModel):
    """Result of POST /copy and POST /move.

    Shape mirrors :class:`~ff_explorer.core.TransferReport`:

    * ``kind``        — ``"copy"`` or ``"move"`` — discriminates the operation.
    * ``matched``     — all paths that matched the filter (source side).
    * ``transferred`` — paths successfully copied/moved (empty on dry_run).
    * ``failed``      — ``[(source_path, error_message), ...]``.
    * ``dry_run``     — mirrors the request *dry_run* flag.
    * ``destination`` — the destination directory used (str), or ``null`` on
                        dry_run.
    * ``would_affect`` — alias for ``matched`` (preview list, same semantics
                          as on :class:`RemoveResponse`).
    """
    kind: str
    dry_run: bool
    matched: list[str]
    transferred: list[str]
    failed: list[tuple[str, str]]
    destination: str | None = None
    would_affect: list[str]


class CopyRequest(BaseModel):
    """Body for POST /copy.

    Dry-run default
    ~~~~~~~~~~~~~~~
    Omitting ``dry_run`` / ``confirm`` (or sending ``dry_run: true``) returns
    the preview list without touching the filesystem.

    To actually copy, send **both**:
      - ``"dry_run": false``
      - ``"confirm": true``
    """
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = Field(
        ...,
        min_length=1,
        description="Non-empty seed required — empty seed would match everything",
    )
    case_sensitive: bool = True
    match_mode: Literal["substring", "glob", "regex"] = Field(
        default="substring",
        description="Name-matching strategy: 'substring' (default), 'glob', or 'regex'.",
    )
    destination: str = Field(
        ...,
        min_length=1,
        description=(
            "Target directory path (non-empty, required).  Created with parents "
            "if it does not exist.  Must not be inside the source *path*."
        ),
    )
    dry_run: bool = Field(
        default=True,
        description="When true (default) return a preview list; nothing is copied.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit opt-in token.  Must be true together with dry_run=false "
            "to actually copy entries.  Has no effect when dry_run=true."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Preview (safe, default)",
                    "value": {
                        "path": "C:/tmp/src", "kind": 1, "name_seed": "report",
                        "destination": "C:/tmp/dst",
                        "dry_run": True, "confirm": False,
                    },
                },
                {
                    "summary": "Actually copy (requires both flags)",
                    "value": {
                        "path": "C:/tmp/src", "kind": 1, "name_seed": "report",
                        "destination": "C:/tmp/dst",
                        "dry_run": False, "confirm": True,
                    },
                },
            ]
        }
    }


class MoveRequest(BaseModel):
    """Body for POST /move.

    Dry-run default
    ~~~~~~~~~~~~~~~
    Omitting ``dry_run`` / ``confirm`` (or sending ``dry_run: true``) returns
    the preview list without touching the filesystem.

    To actually move, send **both**:
      - ``"dry_run": false``
      - ``"confirm": true``
    """
    path: str
    kind: int = Field(..., ge=0, le=1, description="0=FOLDERS, 1=FILES")
    name_seed: str = Field(
        ...,
        min_length=1,
        description="Non-empty seed required — empty seed would match everything",
    )
    case_sensitive: bool = True
    match_mode: Literal["substring", "glob", "regex"] = Field(
        default="substring",
        description="Name-matching strategy: 'substring' (default), 'glob', or 'regex'.",
    )
    destination: str = Field(
        ...,
        min_length=1,
        description=(
            "Target directory path (non-empty, required).  Created with parents "
            "if it does not exist.  Must not be inside the source *path*."
        ),
    )
    dry_run: bool = Field(
        default=True,
        description="When true (default) return a preview list; nothing is moved.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit opt-in token.  Must be true together with dry_run=false "
            "to actually move entries.  Has no effect when dry_run=true."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "Preview (safe, default)",
                    "value": {
                        "path": "C:/tmp/src", "kind": 1, "name_seed": "report",
                        "destination": "C:/tmp/dst",
                        "dry_run": True, "confirm": False,
                    },
                },
                {
                    "summary": "Actually move (requires both flags)",
                    "value": {
                        "path": "C:/tmp/src", "kind": 1, "name_seed": "report",
                        "destination": "C:/tmp/dst",
                        "dry_run": False, "confirm": True,
                    },
                },
            ]
        }
    }


# ---------------------------------------------------------------------------
# List-with-report models — SPEC-15
# ---------------------------------------------------------------------------

class SkippedEntryOut(BaseModel):
    """A single entry skipped during the walk due to a recoverable error.

    Serialisable form of :class:`~ff_explorer.core.SkippedEntry`.
    """
    path: str = Field(..., description="Path that could not be accessed.")
    reason: str = Field(
        ...,
        description=(
            "Human-readable description of why the entry was skipped "
            "(e.g. 'PermissionError: [Errno 13] Permission denied: ...')."
        ),
    )


class ListWithReportResponse(BaseModel):
    """Result of POST /list_with_report.

    Bundles the matched entries with a (possibly empty) list of paths that
    were skipped due to recoverable errors encountered during the walk.

    * ``entries`` — matched entries (same shape as POST /entries).
    * ``skipped`` — entries that could not be accessed; empty list when the
                    walk completed without errors.
    * ``count``   — ``len(entries)``.
    * ``skipped_count`` — ``len(skipped)``.
    """
    entries: list[MatchEntryOut]
    skipped: list[SkippedEntryOut]
    count: int
    skipped_count: int


# ---------------------------------------------------------------------------
# Index lifecycle models — FFX-I10
# ---------------------------------------------------------------------------

class IndexRequest(BaseModel):
    """Body for POST /index/start, POST /index/stop, POST /index/status."""
    path: str = Field(..., description="Absolute path to the root directory to index.")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"path": "C:/Users/me/Documents"},
            ]
        }
    }


class IndexStatusResponse(BaseModel):
    """Result of POST /index/start, POST /index/stop, POST /index/status."""
    root: str
    indexed: bool


# ---------------------------------------------------------------------------
# Error helpers
# ---------------------------------------------------------------------------

# Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY -> HTTP_422_UNPROCESSABLE_CONTENT
# (the old alias is deprecated and will eventually be removed).  Resolve in two
# lazy steps so that on a Starlette which has the new name we NEVER touch the
# deprecated one (a single getattr-with-default would evaluate the default
# eagerly and still fire the DeprecationWarning).  Falls back cleanly on an
# older Starlette where only the old name exists and is not yet deprecated.
if hasattr(status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _HTTP_422 = status.HTTP_422_UNPROCESSABLE_CONTENT
elif hasattr(status, "HTTP_422_UNPROCESSABLE_ENTITY"):
    _HTTP_422 = status.HTTP_422_UNPROCESSABLE_ENTITY
else:  # pragma: no cover - defensive; both names absent
    _HTTP_422 = 422


def _empty_seed_to_422(exc: EmptySeedError) -> HTTPException:
    return HTTPException(
        status_code=_HTTP_422,
        detail={"error": "EmptySeedError", "message": str(exc)},
    )


def _value_error_to_422(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=_HTTP_422,
        detail=str(exc),
    )


def _not_found_to_404(exc: FileNotFoundError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    )


# ---------------------------------------------------------------------------
# Routes — safe / non-destructive
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness and version check",
    tags=["meta"],
)
def health() -> HealthResponse:
    """Return a liveness confirmation and the package version."""
    return HealthResponse(status="ok", version=__version__)


@app.post(
    "/entries",
    response_model=ListEntriesResponse,
    summary="List matching file/folder entries",
    tags=["query"],
)
def post_list_entries(body: ListEntriesRequest) -> ListEntriesResponse:
    """Recursively walk *path* and return entries whose name contains
    *name_seed*.  Non-destructive — safe to call with any seed including
    empty (which matches everything).

    Raises HTTP 422 if *path* is not a directory.
    """
    try:
        entries = service.list_entries(
            body.path, body.kind, body.name_seed,
            case_sensitive=body.case_sensitive,
            match_mode=body.match_mode,
            min_size=body.min_size,
            max_size=body.max_size,
            modified_after=body.modified_after,
            modified_before=body.modified_before,
            extensions=body.extensions,
            respect_ignore=body.respect_ignore,
            ignore_globs=body.ignore_globs,
            search_archives=body.search_archives,
            content_query=body.content_query,
            content_max_bytes=body.content_max_bytes,
            include_hidden=body.include_hidden,
        )
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    out = [MatchEntryOut(path=str(e.path), kind=int(e.kind), in_archive=e.in_archive) for e in entries]
    return ListEntriesResponse(entries=out, count=len(out))


@app.post(
    "/metadata",
    response_model=dict,
    summary="Return metadata for a single path",
    tags=["query"],
)
def post_entry_metadata(body: MetadataRequest) -> dict:
    """Return ``{"path", "type", "size_bytes", "mtime", "exists"}`` for
    *path*.

    Raises HTTP 404 if *path* does not exist.
    """
    try:
        return service.entry_metadata(body.path)
    except FileNotFoundError as exc:
        raise _not_found_to_404(exc) from exc


@app.post(
    "/listing",
    response_model=SaveListingResponse,
    summary="Walk a directory and write a .txt listing file",
    tags=["safe-write"],
)
def post_save_listing(body: SaveListingRequest) -> SaveListingResponse:
    """Walk *path*, filter by *name_seed*, and write a plain-text listing
    file into *path*.  Returns the absolute path of the created file.

    Raises HTTP 422 if *path* is not a directory.
    """
    try:
        out_path = service.save_listing(
            body.path, body.kind, body.name_seed,
            case_sensitive=body.case_sensitive,
        )
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    return SaveListingResponse(listing_path=str(out_path))


# ---------------------------------------------------------------------------
# Routes — duplicate detection (FFX-I06, read-only)
# ---------------------------------------------------------------------------

@app.post(
    "/duplicates",
    response_model=FindDuplicatesResponse,
    summary="Find duplicate files by content hash",
    tags=["query"],
)
def post_find_duplicates(body: FindDuplicatesRequest) -> FindDuplicatesResponse:
    """Recursively walk *path* and return groups of files that share identical
    content (determined by hashing).

    Only groups with two or more members are returned.  The operation is
    entirely read-only — no files are modified or removed.  Use the existing
    ``POST /remove`` route to act on duplicates identified here.

    Raises HTTP 422 if *path* is not an existing directory.
    """
    try:
        groups = service.find_duplicates(body.path, min_size=body.min_size, algo=body.algo)
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    out = [DuplicateGroupOut(hash=g.hash, size=g.size, paths=[str(p) for p in g.paths])
           for g in groups]
    return FindDuplicatesResponse(groups=out, count=len(out))


# ---------------------------------------------------------------------------
# Routes — destructive (guarded)
# ---------------------------------------------------------------------------

@app.post(
    "/remove",
    response_model=RemoveResponse,
    summary="Remove matching entries (GUARDED — dry-run by default)",
    tags=["destructive"],
)
def post_remove(body: RemoveRequest) -> RemoveResponse:
    """Walk *path*, filter by *name_seed*, and optionally remove matched entries.

    **Default behaviour (safe):** ``dry_run=true`` — returns ``.matched``
    (the preview list) without touching the filesystem.

    **To actually remove:** send ``"dry_run": false`` AND ``"confirm": true``
    in the request body.  Both flags are required simultaneously.  The
    confirm flag is the explicit, unambiguous opt-in token.

    Empty ``name_seed`` is always rejected (HTTP 422, ``EmptySeedError``).
    When *send2trash* is installed, entries are moved to the OS recycle bin
    (recoverable); otherwise they are permanently deleted.

    Raises HTTP 422 on ``EmptySeedError``, missing confirm flag, or bad path.
    """
    try:
        report = service.remove_entries(
            body.path, body.kind, body.name_seed,
            case_sensitive=body.case_sensitive,
            dry_run=body.dry_run,
            confirm=body.confirm,
            versioning=body.versioning,
        )
    except EmptySeedError as exc:
        raise _empty_seed_to_422(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    return RemoveResponse(
        dry_run=report.dry_run,
        matched=[str(p) for p in report.matched],
        removed=[str(p) for p in report.removed],
        failed=[(str(p), msg) for p, msg in report.failed],
        would_affect=[str(p) for p in report.would_affect],
        versioned_to=report.versioned_to,
    )


@app.post(
    "/compress",
    response_model=CompressResponse,
    summary="Compress matching entries into zip(s) (GUARDED — dry-run by default)",
    tags=["destructive"],
)
def post_compress(body: CompressRequest) -> CompressResponse:
    """Walk *path*, filter by *name_seed*, and optionally compress matched
    entries into zip archive(s) then delete the originals.

    **Default behaviour (safe):** ``dry_run=true`` — returns ``.matched``
    (the preview list) without touching the filesystem.

    **To actually compress:** send ``"dry_run": false`` AND ``"confirm": true``
    in the request body.  Both flags are required simultaneously.  The
    confirm flag is the explicit, unambiguous opt-in token.

    Empty ``name_seed`` is always rejected (HTTP 422, ``EmptySeedError``).

    Compression layout:
    - FILES mode: all matched files → one ``Compressed_data.zip`` in *path*.
    - FOLDERS mode: each matched folder → its own ``<name>.zip`` in *path*.

    Raises HTTP 422 on ``EmptySeedError``, missing confirm flag, or bad path.
    """
    try:
        report = service.compress_entries(
            body.path, body.kind, body.name_seed,
            case_sensitive=body.case_sensitive,
            dry_run=body.dry_run,
            confirm=body.confirm,
        )
    except EmptySeedError as exc:
        raise _empty_seed_to_422(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    return CompressResponse(
        dry_run=report.dry_run,
        matched=[str(p) for p in report.matched],
        archives=[str(p) for p in report.archives],
        failed=[(str(p), msg) for p, msg in report.failed],
        would_affect=[str(p) for p in report.would_affect],
    )


@app.post(
    "/rename",
    response_model=RenameResponse,
    summary="Batch rename matching entries (GUARDED — dry-run by default)",
    tags=["destructive"],
)
def post_rename(body: RenameRequest) -> RenameResponse:
    """Walk *path*, filter by *name_seed*, and optionally rename matched entries.

    **Default behaviour (safe):** ``dry_run=true`` — returns the planned
    old→new name mapping without touching the filesystem.

    **To actually rename:** send ``"dry_run": false`` AND ``"confirm": true``
    in the request body.  Both flags are required simultaneously.  The
    confirm flag is the explicit, unambiguous opt-in token.

    Empty ``name_seed`` is always rejected (HTTP 422, ``EmptySeedError``).

    Collision detection is performed before any mutation.  When any collision
    is detected the entire batch is refused and ``collisions`` is populated;
    no rename is performed.  On a confirmed apply with no collisions an undo
    JSON file is written and its path is returned in ``undo_file``.

    Raises HTTP 422 on ``EmptySeedError``, missing confirm flag, collision, or bad path.
    """
    rules = [r.to_rename_rule() for r in body.rules]
    try:
        report = service.rename_entries(
            body.path, body.kind, body.name_seed,
            rules=rules,
            case_sensitive=body.case_sensitive,
            match_mode=body.match_mode,
            dry_run=body.dry_run,
            confirm=body.confirm,
        )
    except EmptySeedError as exc:
        raise _empty_seed_to_422(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    return RenameResponse(
        dry_run=report.dry_run,
        matched=report.matched,
        mapping=report.mapping,
        renamed=report.renamed,
        collisions=report.collisions,
        failed=report.failed,
        undo_file=report.undo_file,
    )


# ---------------------------------------------------------------------------
# Routes — copy / move (SPEC-18, gated destructive)
# ---------------------------------------------------------------------------

@app.post(
    "/copy",
    response_model=TransferReportResponse,
    summary="Copy matching entries to a destination directory (GUARDED — dry-run by default)",
    tags=["destructive"],
)
def post_copy(body: CopyRequest) -> TransferReportResponse:
    """Walk *path*, filter by *name_seed*, and optionally copy matched entries
    to *destination*.

    **Default behaviour (safe):** ``dry_run=true`` — returns the would-affect
    preview list without touching the filesystem.

    **To actually copy:** send ``"dry_run": false`` AND ``"confirm": true``
    in the request body.  Both flags are required simultaneously.

    Empty ``name_seed`` is always rejected (HTTP 422, ``EmptySeedError``).
    *destination* must not be inside *path* (recursion guard — HTTP 422).

    Raises HTTP 422 on ``EmptySeedError``, missing confirm flag, or bad paths.
    Raises HTTP 404 if *path* does not exist or is not a directory.
    """
    try:
        report = service.copy_entries(
            body.path, body.kind, body.name_seed,
            destination=body.destination,
            case_sensitive=body.case_sensitive,
            match_mode=body.match_mode,
            dry_run=body.dry_run,
            confirm=body.confirm,
        )
    except EmptySeedError as exc:
        raise _empty_seed_to_422(exc) from exc
    except FileNotFoundError as exc:
        raise _not_found_to_404(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    return TransferReportResponse(
        kind=report.kind,
        dry_run=report.dry_run,
        matched=[str(p) for p in report.matched],
        transferred=[str(p) for p in report.transferred],
        failed=[(str(p), msg) for p, msg in report.failed],
        destination=report.destination,
        would_affect=[str(p) for p in report.would_affect],
    )


@app.post(
    "/move",
    response_model=TransferReportResponse,
    summary="Move matching entries to a destination directory (GUARDED — dry-run by default)",
    tags=["destructive"],
)
def post_move(body: MoveRequest) -> TransferReportResponse:
    """Walk *path*, filter by *name_seed*, and optionally move matched entries
    to *destination*.

    **Default behaviour (safe):** ``dry_run=true`` — returns the would-affect
    preview list without touching the filesystem.

    **To actually move:** send ``"dry_run": false`` AND ``"confirm": true``
    in the request body.  Both flags are required simultaneously.

    Empty ``name_seed`` is always rejected (HTTP 422, ``EmptySeedError``).
    *destination* must not be inside *path* (recursion guard — HTTP 422).

    Raises HTTP 422 on ``EmptySeedError``, missing confirm flag, or bad paths.
    Raises HTTP 404 if *path* does not exist or is not a directory.
    """
    try:
        report = service.move_entries(
            body.path, body.kind, body.name_seed,
            destination=body.destination,
            case_sensitive=body.case_sensitive,
            match_mode=body.match_mode,
            dry_run=body.dry_run,
            confirm=body.confirm,
        )
    except EmptySeedError as exc:
        raise _empty_seed_to_422(exc) from exc
    except FileNotFoundError as exc:
        raise _not_found_to_404(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    return TransferReportResponse(
        kind=report.kind,
        dry_run=report.dry_run,
        matched=[str(p) for p in report.matched],
        transferred=[str(p) for p in report.transferred],
        failed=[(str(p), msg) for p, msg in report.failed],
        destination=report.destination,
        would_affect=[str(p) for p in report.would_affect],
    )


# ---------------------------------------------------------------------------
# Routes — list with skip report (SPEC-15, non-destructive)
# ---------------------------------------------------------------------------

@app.post(
    "/list_with_report",
    response_model=ListWithReportResponse,
    summary="List matching entries and return a skip report",
    tags=["query"],
)
def post_list_with_report(body: ListEntriesRequest) -> ListWithReportResponse:
    """Recursively walk *path* and return matched entries together with a skip
    report for any paths that could not be accessed due to recoverable errors.

    This is a superset of ``POST /entries``: the entries list is identical to
    what ``POST /entries`` returns with the same parameters, and ``skipped``
    surfaces any ``PermissionError`` / ``OSError`` paths that were silently
    skipped during the walk.

    The existing ``POST /entries`` endpoint is **unchanged** (back-compat).

    Non-destructive — safe to call with any seed including empty (which matches
    everything).  No dry_run/confirm gate.

    Raises HTTP 422 if *path* is not a directory or other validation fails.
    """
    try:
        result = service.list_entries_with_report(
            body.path, body.kind, body.name_seed,
            case_sensitive=body.case_sensitive,
            match_mode=body.match_mode,
            min_size=body.min_size,
            max_size=body.max_size,
            modified_after=body.modified_after,
            modified_before=body.modified_before,
            extensions=body.extensions,
            respect_ignore=body.respect_ignore,
            ignore_globs=body.ignore_globs,
            search_archives=body.search_archives,
            content_query=body.content_query,
            content_max_bytes=body.content_max_bytes,
            include_hidden=body.include_hidden,
        )
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    entries_out = [
        MatchEntryOut(path=str(e.path), kind=int(e.kind), in_archive=e.in_archive)
        for e in result.entries
    ]
    skipped_out = [
        SkippedEntryOut(path=s.path, reason=s.reason)
        for s in result.skipped
    ]
    return ListWithReportResponse(
        entries=entries_out,
        skipped=skipped_out,
        count=len(entries_out),
        skipped_count=len(skipped_out),
    )


# ---------------------------------------------------------------------------
# Routes — preset operations (FFX-I03)
# ---------------------------------------------------------------------------

@app.post(
    "/presets/save",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Save (upsert) a named preset",
    tags=["presets"],
)
def post_save_preset(body: PresetIn) -> None:
    """Persist a named preset to the JSON store (upsert by name).

    The preset bundles a root path, kind, name seed, match mode, filters, and
    an operation (``"list"``, ``"remove"``, or ``"compress"``).  Once saved it
    can be executed via ``POST /presets/run``.

    Raises HTTP 422 on invalid operation or empty/whitespace name.
    """
    preset = service.Preset(
        name=body.name,
        path=body.path,
        kind=body.kind,
        name_seed=body.name_seed,
        case_sensitive=body.case_sensitive,
        match_mode=body.match_mode,
        min_size=body.min_size,
        max_size=body.max_size,
        modified_after=body.modified_after,
        modified_before=body.modified_before,
        extensions=body.extensions,
        respect_ignore=body.respect_ignore,
        ignore_globs=body.ignore_globs,
        operation=body.operation,
    )
    try:
        service.save_preset(preset)
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc


@app.post(
    "/presets/list",
    response_model=PresetListResponse,
    summary="List all stored presets",
    tags=["presets"],
)
def post_list_presets() -> PresetListResponse:
    """Return all stored presets.

    Returns an empty list when the store is absent, empty, or corrupt.
    This operation is always safe and non-destructive.
    """
    presets = service.list_presets()
    out = [
        PresetOut(
            name=p.name,
            path=p.path,
            kind=p.kind,
            name_seed=p.name_seed,
            case_sensitive=p.case_sensitive,
            match_mode=p.match_mode,
            min_size=p.min_size,
            max_size=p.max_size,
            modified_after=p.modified_after,
            modified_before=p.modified_before,
            extensions=p.extensions,
            respect_ignore=p.respect_ignore,
            ignore_globs=p.ignore_globs,
            operation=p.operation,
        )
        for p in presets
    ]
    return PresetListResponse(presets=out, count=len(out))


@app.post(
    "/presets/run",
    response_model=PresetRunResponse,
    summary="Execute a named preset (GUARDED for destructive presets — dry-run by default)",
    tags=["presets"],
)
def post_run_preset(body: PresetRunRequest) -> PresetRunResponse:
    """Load the named preset and execute it.

    * ``operation="list"``     — returns entries in ``entries``; ``report`` is null.
    * ``operation="remove"``   — returns removal report in ``report``; ``entries`` is null.
    * ``operation="compress"`` — returns compression report in ``report``; ``entries`` is null.

    **Destructive gate (remove/compress):** ``dry_run=true`` (the default) returns a
    safe preview; nothing is mutated.  To actually mutate, send **both**
    ``"dry_run": false`` AND ``"confirm": true``.

    Raises HTTP 404 if the preset name is not found.
    Raises HTTP 422 on ``EmptySeedError``, missing confirm flag, or bad path.
    """
    try:
        result = service.run_preset(
            body.name,
            dry_run=body.dry_run,
            confirm=body.confirm,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Preset not found: {body.name!r}",
        ) from exc
    except EmptySeedError as exc:
        raise _empty_seed_to_422(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc

    # result is list[MatchEntry] for "list", RemovalReport for "remove",
    # CompressionReport for "compress".  Discriminate by type.
    from ff_explorer.core import MatchEntry, RemovalReport, CompressionReport

    if isinstance(result, list):
        # "list" operation
        entries = [MatchEntryOut(path=str(e.path), kind=int(e.kind)) for e in result]
        return PresetRunResponse(operation="list", entries=entries, report=None)

    if isinstance(result, RemovalReport):
        report_dict: dict[str, Any] = {
            "dry_run": result.dry_run,
            "matched": [str(p) for p in result.matched],
            "removed": [str(p) for p in result.removed],
            "failed": [(str(p), msg) for p, msg in result.failed],
            "would_affect": [str(p) for p in result.would_affect],
        }
        return PresetRunResponse(operation="remove", entries=None, report=report_dict)

    if isinstance(result, CompressionReport):
        report_dict = {
            "dry_run": result.dry_run,
            "matched": [str(p) for p in result.matched],
            "archives": [str(p) for p in result.archives],
            "failed": [(str(p), msg) for p, msg in result.failed],
            "would_affect": [str(p) for p in result.would_affect],
        }
        return PresetRunResponse(operation="compress", entries=None, report=report_dict)

    # Defensive: should not be reached (service validates operation on save)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Unexpected result type from run_preset: {type(result).__name__}",
    )


# ---------------------------------------------------------------------------
# Routes — index lifecycle (FFX-I10, non-destructive, no dry_run/confirm gate)
# ---------------------------------------------------------------------------

@app.post(
    "/index/start",
    response_model=IndexStatusResponse,
    summary="Start real-time name indexing for a root directory",
    tags=["index"],
)
def post_start_index(body: IndexRequest) -> IndexStatusResponse:
    """Build an in-memory name index for *path* and start a watchdog observer.

    Once started, queries against this root are served from the index instead
    of a full tree walk.  Indexing is opt-in per root; calling this on an
    already-indexed root is a safe no-op.

    Raises HTTP 404 if *path* does not exist or is not a directory.
    Raises HTTP 422 if ``watchdog`` is not installed.
    """
    try:
        service.start_index(body.path)
    except FileNotFoundError as exc:
        raise _not_found_to_404(exc) from exc
    except (ImportError, ValueError) as exc:
        raise _value_error_to_422(exc) from exc
    return IndexStatusResponse(root=body.path, indexed=True)


@app.post(
    "/index/stop",
    response_model=IndexStatusResponse,
    summary="Stop real-time name indexing for a root directory",
    tags=["index"],
)
def post_stop_index(body: IndexRequest) -> IndexStatusResponse:
    """Stop the watchdog observer and drop the in-memory index for *path*.

    If *path* is not currently indexed, this is a safe no-op.  After this
    call, queries against the root fall back to a live tree walk.
    """
    service.stop_index(body.path)
    return IndexStatusResponse(root=body.path, indexed=False)


@app.post(
    "/index/status",
    response_model=IndexStatusResponse,
    summary="Query whether a root directory is currently indexed",
    tags=["index"],
)
def post_index_status(body: IndexRequest) -> IndexStatusResponse:
    """Return whether *path* currently has an active in-memory name index.

    Non-destructive read-only query; always safe to call.
    """
    result = service.index_status(body.path)
    return IndexStatusResponse(root=result["root"], indexed=result["indexed"])


# ---------------------------------------------------------------------------
# Routes — size aggregation (FFX-I11, non-destructive, no dry_run/confirm gate)
# ---------------------------------------------------------------------------

@app.post(
    "/largest",
    response_model=LargestEntriesResponse,
    summary="Return the top-N largest files by size",
    tags=["query"],
)
def post_largest_entries(body: LargestEntriesRequest) -> LargestEntriesResponse:
    """Recursively walk *path* and return the *top_n* largest files, sorted
    descending by size.

    Non-destructive query — no dry_run/confirm gate required.  Empty
    *name_seed* is allowed and aggregates the whole tree.

    Raises HTTP 404 if *path* does not exist or is not a directory.
    Raises HTTP 422 if *top_n* is less than 1 (also enforced at schema level
    by ``ge=1``; the core ``ValueError`` is a backstop).
    """
    try:
        entries = service.largest_entries(body.path, body.top_n, name_seed=body.name_seed)
    except FileNotFoundError as exc:
        raise _not_found_to_404(exc) from exc
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    out = [SizedEntryOut(path=str(e.path), size=e.size) for e in entries]
    return LargestEntriesResponse(entries=out, count=len(out))
