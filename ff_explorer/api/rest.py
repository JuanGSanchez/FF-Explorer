"""
ff_explorer.api.rest
=====================
FastAPI REST application over the shared ``service`` module.

Routes
------
GET  /health                            — liveness + version.
GET  /entries                           — list matching entries (query).
GET  /metadata                          — entry metadata (query).
POST /listing                           — write a .txt listing (safe write).
POST /remove                            — remove entries (GUARDED — dry-run by default).
POST /compress                          — compress entries (GUARDED — dry-run by default).

Hard-guard contract for destructive routes
------------------------------------------
``POST /remove`` and ``POST /compress`` default to **dry-run** mode: calling
them without ``"dry_run": false, "confirm": true`` returns the
``.matched``/``.would_affect`` preview list and mutates nothing.

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

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from ff_explorer import __version__
from ff_explorer.core import EmptySeedError
from ff_explorer.api import service

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


class ListEntriesRequest(BaseModel):
    """Body for GET /entries (also accepted as query params via direct GET)."""
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


class ListEntriesResponse(BaseModel):
    """Result of GET /entries."""
    entries: list[MatchEntryOut]
    count: int


class MetadataRequest(BaseModel):
    """Body for GET /metadata."""
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
# Error helpers
# ---------------------------------------------------------------------------

def _empty_seed_to_422(exc: EmptySeedError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"error": "EmptySeedError", "message": str(exc)},
    )


def _value_error_to_422(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
        )
    except ValueError as exc:
        raise _value_error_to_422(exc) from exc
    out = [MatchEntryOut(path=str(e.path), kind=int(e.kind)) for e in entries]
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
