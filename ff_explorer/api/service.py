"""
ff_explorer.api.service
=======================
Single shared service layer.

**Both** the REST app (``rest.py``) and the MCP server (``mcp_server.py``)
call this module.  No traversal or filesystem logic is duplicated here —
every operation is a thin, typed wrapper over ``ff_explorer.core``.

Error contract
--------------
``EmptySeedError``, ``ValueError``, and ``FileNotFoundError`` raised by the
core are re-raised unchanged.  Callers (REST layer: ``HTTPException``; MCP
layer: FastMCP tool error) are responsible for mapping to their transport's
error format.

Destructive-ops contract
------------------------
``remove_entries`` and ``compress_entries`` default to ``dry_run=True``.
To actually mutate the filesystem the caller must pass
``dry_run=False, confirm=True`` — both flags are required simultaneously.
Empty ``name_seed`` is rejected at the core level with ``EmptySeedError``.
Deletes (``remove_entries``) route to the OS recycle bin via *send2trash*
when available (see ``ff_explorer.core.remove_entries`` docstring).
"""
from __future__ import annotations

from pathlib import Path

from ff_explorer.core import (
    EntryKind,
    MatchEntry,
    RemovalReport,
    CompressionReport,
    EmptySeedError,
    list_entries as _core_list_entries,
    entry_metadata as _core_entry_metadata,
    save_listing as _core_save_listing,
    remove_entries as _core_remove_entries,
    compress_entries as _core_compress_entries,
)

__all__ = [
    "list_entries",
    "entry_metadata",
    "save_listing",
    "remove_entries",
    "compress_entries",
    "EntryKind",
    "MatchEntry",
    "RemovalReport",
    "CompressionReport",
    "EmptySeedError",
]


# ---------------------------------------------------------------------------
# Safe / non-destructive operations
# ---------------------------------------------------------------------------

def list_entries(
    path: str,
    kind: int,
    name_seed: str = "",
    *,
    case_sensitive: bool = True,
) -> list[MatchEntry]:
    """Return every file/folder entry under *path* whose name contains *name_seed*.

    Parameters
    ----------
    path:
        Root directory to walk.  Must exist and be a directory.
    kind:
        ``0`` — collect subdirectory names (``EntryKind.FOLDERS``).
        ``1`` — collect file names (``EntryKind.FILES``).
    name_seed:
        Substring filter.  Empty string matches everything (safe — this
        operation is non-destructive).
    case_sensitive:
        When ``False`` the match is lowercased on both sides.  Default
        ``True`` (preserves legacy behaviour).

    Returns
    -------
    list[MatchEntry]
        Each entry carries the resolved absolute path and its ``EntryKind``.

    Raises
    ------
    ValueError
        If *path* does not exist or is not a directory.
    """
    return _core_list_entries(path, EntryKind(int(kind)), name_seed,
                              case_sensitive=case_sensitive)


def entry_metadata(path: str) -> dict:
    """Return size, modification time, and type for *path*.

    Parameters
    ----------
    path:
        Absolute or relative path to a file or directory.

    Returns
    -------
    dict
        ``{"path": str, "type": str, "size_bytes": int, "mtime": float,
        "exists": bool}``

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    return _core_entry_metadata(path)


def save_listing(
    path: str,
    kind: int,
    name_seed: str = "",
    *,
    case_sensitive: bool = True,
) -> Path:
    """Walk *path*, filter by *name_seed*, and write a plain-text listing file.

    Parameters
    ----------
    path, kind, name_seed, case_sensitive:
        Same semantics as :func:`list_entries`.

    Returns
    -------
    Path
        Absolute path of the written ``.txt`` file.

    Raises
    ------
    ValueError
        If *path* is not a directory.
    OSError
        If the listing file cannot be written.
    """
    return _core_save_listing(path, EntryKind(int(kind)), name_seed,
                              case_sensitive=case_sensitive)


# ---------------------------------------------------------------------------
# Destructive operations — default dry_run=True; require confirm=True to act
# ---------------------------------------------------------------------------

def remove_entries(
    path: str,
    kind: int,
    name_seed: str,
    *,
    case_sensitive: bool = True,
    dry_run: bool = True,
    confirm: bool = False,
) -> RemovalReport:
    """Walk *path*, filter by *name_seed*, and remove matched entries.

    Safety guards (enforced before any mutation):

    1. *name_seed* must be non-empty and non-whitespace —
       ``EmptySeedError`` otherwise.
    2. *dry_run=True* (the default) — returns what WOULD be removed without
       touching the filesystem.  This is the safe preview mode.
    3. *confirm=True* is required alongside *dry_run=False* to actually
       remove.  Both flags must be set explicitly.

    Removal strategy: when *send2trash* is installed, matched items are moved
    to the OS recycle bin / trash (recoverable).  Without *send2trash*, items
    are permanently deleted via ``os.remove`` / ``shutil.rmtree``.

    Parameters
    ----------
    path:
        Root directory to walk.
    kind:
        ``0`` — FOLDERS, ``1`` — FILES.
    name_seed:
        Non-empty substring filter.  Blank raises ``EmptySeedError``.
    case_sensitive:
        Case-sensitive name matching (default ``True``).
    dry_run:
        When ``True`` (default), return the preview list without removing.
    confirm:
        Must be ``True`` when *dry_run=False*.  Explicit opt-in token.

    Returns
    -------
    RemovalReport
        ``.matched``     — all paths that matched the filter.
        ``.removed``     — paths successfully removed (empty on dry-run).
        ``.failed``      — ``[(path, error_message), ...]``.
        ``.dry_run``     — mirrors the *dry_run* parameter.
        ``.would_affect`` — alias for ``.matched`` (preview list).

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If *dry_run=False* but *confirm=False*, or *path* is not a directory.
    """
    return _core_remove_entries(
        path, EntryKind(int(kind)), name_seed,
        case_sensitive=case_sensitive,
        dry_run=dry_run,
        confirm=confirm,
    )


def compress_entries(
    path: str,
    kind: int,
    name_seed: str,
    *,
    case_sensitive: bool = True,
    dry_run: bool = True,
    confirm: bool = False,
) -> CompressionReport:
    """Walk *path*, filter by *name_seed*, compress matched entries into
    zip archive(s), then permanently delete the originals.

    Safety guards mirror :func:`remove_entries`:

    1. Non-empty *name_seed* required — ``EmptySeedError`` otherwise.
    2. *dry_run=True* (default) — returns the preview list without touching
       the filesystem.
    3. *confirm=True* required alongside *dry_run=False* to act.

    Compression layout:

    - **FILES** mode: all matched files into one ``Compressed_data.zip``
      placed directly in *path*.
    - **FOLDERS** mode: each matched folder into its own
      ``<folder_name>.zip`` placed directly in *path*.

    After successful compression, originals are permanently deleted
    (compressed copies are the recovery mechanism).

    Parameters
    ----------
    path, kind, name_seed, case_sensitive, dry_run, confirm:
        Same semantics as :func:`remove_entries`.

    Returns
    -------
    CompressionReport
        ``.matched``     — paths that matched the filter.
        ``.archives``    — zip archive paths created (empty on dry-run).
        ``.failed``      — ``[(path, error_message), ...]``.
        ``.dry_run``     — mirrors the *dry_run* parameter.
        ``.would_affect`` — alias for ``.matched`` (preview list).

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If *dry_run=False* but *confirm=False*, or *path* is not a directory.
    """
    return _core_compress_entries(
        path, EntryKind(int(kind)), name_seed,
        case_sensitive=case_sensitive,
        dry_run=dry_run,
        confirm=confirm,
    )
