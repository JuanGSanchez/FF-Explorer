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

import logging
from pathlib import Path
from typing import Iterable, Iterator

from ff_explorer.core import (
    EntryKind,
    MatchEntry,
    SkippedEntry,
    ListingResult,
    SizedEntry,
    RemovalReport,
    CompressionReport,
    TransferReport,
    EmptySeedError,
    InvalidRegexError,
    ContentSearchUngatedError,
    list_entries as _core_list_entries,
    iter_entries as _core_iter_entries,
    list_entries_with_report as _core_list_entries_with_report,
    entry_metadata as _core_entry_metadata,
    save_listing as _core_save_listing,
    remove_entries as _core_remove_entries,
    compress_entries as _core_compress_entries,
    copy_entries as _core_copy_entries,
    move_entries as _core_move_entries,
    largest_entries as _core_largest_entries,
)
from ff_explorer.content_search import CONTENT_MAX_BYTES
from ff_explorer.presets import (
    Preset,
    save_preset as _presets_save,
    list_presets as _presets_list,
    get_preset as _presets_get,
)
from ff_explorer.dedupe import (
    DuplicateGroup,
    find_duplicates as _dedupe_find_duplicates,
)
from ff_explorer.rename import (
    RenameRule,
    RenameReport,
    rename_entries as _rename_entries,
    replay_undo as _replay_undo,
)
from ff_explorer.index import IndexManager as _IndexManager

logger = logging.getLogger(__name__)

__all__ = [
    "list_entries",
    "iter_entries",
    "list_entries_with_report",
    "entry_metadata",
    "save_listing",
    "remove_entries",
    "compress_entries",
    "copy_entries",
    "move_entries",
    "largest_entries",
    "save_preset",
    "list_presets",
    "run_preset",
    "find_duplicates",
    "rename_entries",
    "replay_undo",
    "start_index",
    "stop_index",
    "index_status",
    "EntryKind",
    "MatchEntry",
    "SkippedEntry",
    "ListingResult",
    "SizedEntry",
    "RemovalReport",
    "CompressionReport",
    "TransferReport",
    "EmptySeedError",
    "InvalidRegexError",
    "ContentSearchUngatedError",
    "DuplicateGroup",
    "Preset",
    "RenameRule",
    "RenameReport",
    "CONTENT_MAX_BYTES",
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
    match_mode: str = "substring",
    min_size: int | None = None,
    max_size: int | None = None,
    modified_after: float | None = None,
    modified_before: float | None = None,
    extensions: Iterable[str] | None = None,
    respect_ignore: bool = False,
    ignore_globs: list[str] | None = None,
    search_archives: bool = False,
    content_query: str | None = None,
    content_max_bytes: int = CONTENT_MAX_BYTES,
    include_hidden: bool = True,
) -> list[MatchEntry]:
    """Return every file/folder entry under *path* whose name matches *name_seed*.

    Parameters
    ----------
    path:
        Root directory to walk.  Must exist and be a directory.
    kind:
        ``0`` — collect subdirectory names (``EntryKind.FOLDERS``).
        ``1`` — collect file names (``EntryKind.FILES``).
    name_seed:
        Pattern/substring filter.  Empty string matches everything (safe —
        this operation is non-destructive).
    case_sensitive:
        When ``False`` the match is case-insensitive.  Default ``True``
        (preserves legacy behaviour).
    match_mode:
        ``"substring"`` (default), ``"glob"``, or ``"regex"``.  See
        :func:`ff_explorer.core.list_entries` for full semantics.
    min_size:
        Minimum file size in bytes (inclusive); ``None`` = no bound.
        Files only — directories always pass.
    max_size:
        Maximum file size in bytes (inclusive); ``None`` = no bound.
        Files only — directories always pass.
    modified_after:
        Epoch float; only entries with mtime strictly after this value
        are returned.  ``None`` = no bound.
    modified_before:
        Epoch float; only entries with mtime strictly before this value
        are returned.  ``None`` = no bound.
    extensions:
        Iterable of extension strings (``".txt"``, ``"log"`` etc.).
        Matched case-insensitively.  Files only — directories always pass.
        ``None`` = no filter.
    respect_ignore:
        When ``True``, discover and honour ``.gitignore`` / ``.ignore`` files
        encountered during the walk (layered/nested precedence; ignored
        directories are pruned).  Default ``False`` — preserves legacy output.
    ignore_globs:
        Additional gitwildmatch glob patterns always applied when provided.
        ``None`` = no extra exclusions.
    search_archives:
        When ``True`` (FILES mode only), open each encountered archive
        (``.zip``, ``.tar``, ``.tar.gz``/``.tgz``, ``.tar.bz2``) read-only
        and yield internal members whose names match *name_seed*.  Hits are
        returned as :class:`MatchEntry` objects with ``in_archive=True`` and
        ``path`` of the form ``<archive_path>!<member/name>``.  Malformed
        archives are skipped silently.  Default ``False`` — preserves legacy
        output exactly (FFX-I05).
    content_query:
        Optional grep-style content filter (FFX-I09).  When provided, only
        FILES whose text content contains a match are returned.  Requires at
        least one name/type/size pre-filter to be active — raises
        :class:`ContentSearchUngatedError` otherwise.  Default ``None``.
    content_max_bytes:
        Maximum file size in bytes scanned for content matching.  Default
        :data:`CONTENT_MAX_BYTES` (10 MiB).  Ignored when *content_query*
        is ``None``.
    include_hidden:
        When ``True`` (default), hidden and system entries are included —
        identical to pre-SPEC-17 behaviour.  When ``False``, hidden/system
        entries are excluded (POSIX dotfiles; Windows FILE_ATTRIBUTE_HIDDEN /
        FILE_ATTRIBUTE_SYSTEM).  Default ``True`` — no regression.

    Returns
    -------
    list[MatchEntry]
        Each entry carries the resolved absolute path and its ``EntryKind``.
        Archive-internal entries have ``in_archive=True``.

    Raises
    ------
    ValueError
        If *path* does not exist or is not a directory, or *match_mode* is
        not a recognised value.
    InvalidRegexError
        If *match_mode* is ``"regex"`` and *name_seed* is not a valid pattern.
        (Also a subtype of ``ValueError``.)
    ContentSearchUngatedError
        If *content_query* is provided without any name/type/size pre-filter.
        (Also a subtype of ``ValueError``.)
    """
    return _core_list_entries(
        path,
        EntryKind(int(kind)),
        name_seed,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        min_size=min_size,
        max_size=max_size,
        modified_after=modified_after,
        modified_before=modified_before,
        extensions=extensions,
        respect_ignore=respect_ignore,
        ignore_globs=ignore_globs,
        search_archives=search_archives,
        content_query=content_query,
        content_max_bytes=content_max_bytes,
        include_hidden=include_hidden,
    )


def iter_entries(
    path: str,
    kind: int,
    name_seed: str = "",
    *,
    case_sensitive: bool = True,
    match_mode: str = "substring",
    min_size: int | None = None,
    max_size: int | None = None,
    modified_after: float | None = None,
    modified_before: float | None = None,
    extensions: Iterable[str] | None = None,
    respect_ignore: bool = False,
    ignore_globs: list[str] | None = None,
    search_archives: bool = False,
    content_query: str | None = None,
    content_max_bytes: int = CONTENT_MAX_BYTES,
    include_hidden: bool = True,
    _skipped: "list[SkippedEntry] | None" = None,
) -> "Iterator[MatchEntry]":
    """Streaming generator variant of :func:`list_entries`.

    Yields each :class:`MatchEntry` as the walk discovers it without
    accumulating a full results list.  Thin passthrough to
    :func:`ff_explorer.core.iter_entries`.

    Parameters
    ----------
    path, kind, name_seed, case_sensitive, match_mode, min_size, max_size,
    modified_after, modified_before, extensions, respect_ignore, ignore_globs,
    search_archives, content_query, content_max_bytes, include_hidden:
        Same semantics as :func:`list_entries`.
    _skipped:
        Optional list; mutated in-place with :class:`SkippedEntry` objects for
        every path skipped due to a recoverable error.  ``None`` = errors are
        only logged.

    Yields
    ------
    MatchEntry
        One per matching entry in ``os.walk`` top-down order.

    Raises
    ------
    ValueError, InvalidRegexError, ContentSearchUngatedError:
        Same conditions as :func:`list_entries`.
    """
    return _core_iter_entries(
        path,
        EntryKind(int(kind)),
        name_seed,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        min_size=min_size,
        max_size=max_size,
        modified_after=modified_after,
        modified_before=modified_before,
        extensions=extensions,
        respect_ignore=respect_ignore,
        ignore_globs=ignore_globs,
        search_archives=search_archives,
        content_query=content_query,
        content_max_bytes=content_max_bytes,
        include_hidden=include_hidden,
        _skipped=_skipped,
    )


def list_entries_with_report(
    path: str,
    kind: int,
    name_seed: str = "",
    *,
    case_sensitive: bool = True,
    match_mode: str = "substring",
    min_size: int | None = None,
    max_size: int | None = None,
    modified_after: float | None = None,
    modified_before: float | None = None,
    extensions: Iterable[str] | None = None,
    respect_ignore: bool = False,
    ignore_globs: list[str] | None = None,
    search_archives: bool = False,
    content_query: str | None = None,
    content_max_bytes: int = CONTENT_MAX_BYTES,
    include_hidden: bool = True,
) -> ListingResult:
    """Walk *path* and return matched entries together with a skip report.

    Thin passthrough to :func:`ff_explorer.core.list_entries_with_report`.
    Identical to :func:`list_entries` except the return value bundles entries
    with a :class:`SkippedEntry` list for every path skipped due to a
    recoverable error.  The walk always completes.

    Parameters
    ----------
    path, kind, name_seed, case_sensitive, match_mode, min_size, max_size,
    modified_after, modified_before, extensions, respect_ignore, ignore_globs,
    search_archives, content_query, content_max_bytes, include_hidden:
        Same semantics as :func:`list_entries`.

    Returns
    -------
    ListingResult
        ``.entries`` — matched :class:`MatchEntry` objects.
        ``.skipped`` — :class:`SkippedEntry` objects for paths that could not
        be accessed.  Empty list when no errors occurred.

    Raises
    ------
    ValueError, InvalidRegexError, ContentSearchUngatedError:
        Same conditions as :func:`list_entries`.
    """
    return _core_list_entries_with_report(
        path,
        EntryKind(int(kind)),
        name_seed,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        min_size=min_size,
        max_size=max_size,
        modified_after=modified_after,
        modified_before=modified_before,
        extensions=extensions,
        respect_ignore=respect_ignore,
        ignore_globs=ignore_globs,
        search_archives=search_archives,
        content_query=content_query,
        content_max_bytes=content_max_bytes,
        include_hidden=include_hidden,
    )


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
    versioning: bool = False,
) -> RemovalReport:
    """Walk *path*, filter by *name_seed*, and remove matched entries.

    Safety guards (enforced before any mutation):

    1. *name_seed* must be non-empty and non-whitespace —
       ``EmptySeedError`` otherwise.
    2. *dry_run=True* (the default) — returns what WOULD be removed without
       touching the filesystem.  This is the safe preview mode.
    3. *confirm* must be set to True alongside *dry_run* set to False to
       actually remove.  Both flags must be set explicitly.

    Removal strategy: when *versioning=False* (default) and *send2trash* is
    installed, matched items are moved to the OS recycle bin / trash
    (recoverable).  When *versioning=True*, items are moved into a timestamped
    directory ``<path>/.ffe-versions/<YYYYMMDD-HHMMSS>/`` preserving relative
    structure — see ``ff_explorer.core.remove_entries`` for full semantics.

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
        Must be True when *dry_run* is False.  Explicit opt-in token.
    versioning:
        When ``True``, move matched items into a timestamped recovery archive
        under ``<path>/.ffe-versions/`` instead of the OS recycle bin.
        Default ``False`` — preserves existing recycle-bin behaviour.

    Returns
    -------
    RemovalReport
        ``.matched``      — all paths that matched the filter.
        ``.removed``      — paths successfully removed (empty on dry-run).
        ``.failed``       — ``[(path, error_message), ...]``.
        ``.dry_run``      — mirrors the *dry_run* parameter.
        ``.versioned_to`` — the version directory used (str), or ``None``.
        ``.would_affect`` — alias for ``.matched`` (preview list).

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If *dry_run* is False but *confirm* is also False, or *path* is
        not a directory.
    """
    return _core_remove_entries(
        path, EntryKind(int(kind)), name_seed,
        case_sensitive=case_sensitive,
        dry_run=dry_run,
        confirm=confirm,
        versioning=versioning,
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


# ---------------------------------------------------------------------------
# Bulk copy / move — SPEC-18 (gated; default dry_run=True)
# ---------------------------------------------------------------------------

def copy_entries(
    path: str,
    kind: int,
    name_seed: str,
    *,
    destination: str,
    case_sensitive: bool = True,
    match_mode: str = "substring",
    dry_run: bool = True,
    confirm: bool = False,
) -> TransferReport:
    """Walk *path*, filter by *name_seed*, and copy matched entries to
    *destination*.

    Thin passthrough to :func:`ff_explorer.core.copy_entries`.

    Safety guards (identical to :func:`remove_entries`):

    1. *name_seed* must be non-empty — ``EmptySeedError`` otherwise.
    2. *dry_run* defaults to ``True`` (safe preview; nothing is copied).
    3. Passing *confirm* as ``True`` alongside *dry_run* as ``False`` is
       the only way to actually copy.

    Parameters
    ----------
    path:
        Root directory to walk.
    kind:
        ``0`` — FOLDERS, ``1`` — FILES.
    name_seed:
        Non-empty filter pattern.  Blank raises ``EmptySeedError``.
    destination:
        Target directory (created with parents if absent).  Must not be
        inside *path*.
    case_sensitive:
        Case-sensitive name matching (default ``True``).
    match_mode:
        ``"substring"`` (default), ``"glob"``, or ``"regex"``.
    dry_run:
        When ``True`` (default), return the preview list without copying.
    confirm:
        Explicit opt-in token (default ``False``).

    Returns
    -------
    TransferReport
        ``.kind``        — ``"copy"``.
        ``.matched``     — all paths that matched the filter.
        ``.transferred`` — paths successfully copied (empty on dry-run).
        ``.failed``      — ``[(source_path, error_message), ...]``.
        ``.dry_run``     — mirrors the *dry_run* parameter.
        ``.destination`` — destination directory (str), or ``None`` on
                           dry-run.

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If the gate conditions are not met, *path* is not a directory, or
        *destination* is inside *path*.
    """
    return _core_copy_entries(
        path, EntryKind(int(kind)), name_seed,
        destination=destination,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        dry_run=dry_run,
        confirm=confirm,
    )


def move_entries(
    path: str,
    kind: int,
    name_seed: str,
    *,
    destination: str,
    case_sensitive: bool = True,
    match_mode: str = "substring",
    dry_run: bool = True,
    confirm: bool = False,
) -> TransferReport:
    """Walk *path*, filter by *name_seed*, and move matched entries to
    *destination*.

    Thin passthrough to :func:`ff_explorer.core.move_entries`.

    Safety guards (identical to :func:`remove_entries`):

    1. *name_seed* must be non-empty — ``EmptySeedError`` otherwise.
    2. *dry_run* defaults to ``True`` (safe preview; nothing is moved).
    3. Passing *confirm* as ``True`` alongside *dry_run* as ``False`` is
       the only way to actually move.

    Parameters
    ----------
    path:
        Root directory to walk.
    kind:
        ``0`` — FOLDERS, ``1`` — FILES.
    name_seed:
        Non-empty filter pattern.  Blank raises ``EmptySeedError``.
    destination:
        Target directory (created with parents if absent).  Must not be
        inside *path*.
    case_sensitive:
        Case-sensitive name matching (default ``True``).
    match_mode:
        ``"substring"`` (default), ``"glob"``, or ``"regex"``.
    dry_run:
        When ``True`` (default), return the preview list without moving.
    confirm:
        Explicit opt-in token (default ``False``).

    Returns
    -------
    TransferReport
        ``.kind``        — ``"move"``.
        ``.matched``     — all paths that matched the filter.
        ``.transferred`` — paths successfully moved (empty on dry-run).
        ``.failed``      — ``[(source_path, error_message), ...]``.
        ``.dry_run``     — mirrors the *dry_run* parameter.
        ``.destination`` — destination directory (str), or ``None`` on
                           dry-run.

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If the gate conditions are not met, *path* is not a directory, or
        *destination* is inside *path*.
    """
    return _core_move_entries(
        path, EntryKind(int(kind)), name_seed,
        destination=destination,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        dry_run=dry_run,
        confirm=confirm,
    )


# ---------------------------------------------------------------------------
# Preset operations — FFX-I03
# ---------------------------------------------------------------------------

def save_preset(preset: Preset) -> None:
    """Persist *preset* to the JSON store (upsert by name).

    Parameters
    ----------
    preset:
        The :class:`~ff_explorer.presets.Preset` to save.

    Raises
    ------
    ValueError
        If ``preset.name`` is empty/whitespace or ``preset.operation`` is not
        one of ``"list"``, ``"remove"``, ``"compress"``.
    """
    _presets_save(preset)


def list_presets() -> list[Preset]:
    """Return all stored presets.

    Returns an empty list when the store file is absent, empty, or corrupt.
    """
    return _presets_list()


def run_preset(
    name: str,
    *,
    dry_run: bool = True,
    confirm: bool = False,
):
    """Load the named preset and execute it.

    * ``operation == "list"``     — calls :func:`list_entries` and returns
      ``list[MatchEntry]``.
    * ``operation == "remove"``   — calls :func:`remove_entries`, forwarding
      *dry_run* and *confirm* verbatim; returns :class:`RemovalReport`.
    * ``operation == "compress"`` — calls :func:`compress_entries`, forwarding
      *dry_run* and *confirm* verbatim; returns :class:`CompressionReport`.

    The destructive gate is **not** bypassed.  The default ``dry_run=True``
    returns a safe preview.  A live destructive run requires the caller to
    supply ``dry_run`` as ``False`` together with ``confirm`` as ``True`` —
    identical to calling :func:`remove_entries` / :func:`compress_entries`
    directly.

    Parameters
    ----------
    name:
        Name of the preset to execute.
    dry_run:
        Forwarded to the destructive ops unchanged (ignored for ``"list"``).
    confirm:
        Forwarded to the destructive ops unchanged (ignored for ``"list"``).

    Raises
    ------
    KeyError
        If no preset with *name* exists.
    EmptySeedError
        If the preset has a blank ``name_seed`` and ``operation`` is
        destructive.
    ValueError
        If the destructive gate conditions are not met, or *path* is invalid.
    """
    preset = _presets_get(name)

    if preset.operation == "list":
        return _core_list_entries(
            preset.path,
            EntryKind(int(preset.kind)),
            preset.name_seed,
            case_sensitive=preset.case_sensitive,
            match_mode=preset.match_mode,
            min_size=preset.min_size,
            max_size=preset.max_size,
            modified_after=preset.modified_after,
            modified_before=preset.modified_before,
            extensions=preset.extensions,
            respect_ignore=preset.respect_ignore,
            ignore_globs=preset.ignore_globs,
        )

    if preset.operation == "remove":
        return _core_remove_entries(
            preset.path,
            EntryKind(int(preset.kind)),
            preset.name_seed,
            case_sensitive=preset.case_sensitive,
            dry_run=dry_run,
            confirm=confirm,
        )

    if preset.operation == "compress":
        return _core_compress_entries(
            preset.path,
            EntryKind(int(preset.kind)),
            preset.name_seed,
            case_sensitive=preset.case_sensitive,
            dry_run=dry_run,
            confirm=confirm,
        )

    # Should never reach here — save_preset validates operation on write.
    raise ValueError(f"Unknown preset operation: {preset.operation!r}")


# ---------------------------------------------------------------------------
# Duplicate detection (read-only)
# ---------------------------------------------------------------------------

def find_duplicates(
    path: str,
    *,
    min_size: int = 1,
    algo: str = "blake2b",
) -> list[DuplicateGroup]:
    """Return groups of files under *path* that share identical content.

    Thin passthrough to :func:`ff_explorer.dedupe.find_duplicates`.

    Parameters
    ----------
    path:
        Root directory to walk.  Must be an existing directory.
    min_size:
        Minimum file size in bytes (inclusive).  Files strictly smaller than
        this value are skipped.  Default ``1`` excludes 0-byte files.
    algo:
        Hash algorithm: ``"blake2b"`` (default) or ``"sha256"``.

    Returns
    -------
    list[DuplicateGroup]
        Sorted by size descending then hash; paths within each group are sorted.
        Only groups with ≥ 2 members are returned.

    Raises
    ------
    ValueError
        If *path* is not an existing directory, or *algo* is not supported.
    """
    return _dedupe_find_duplicates(path, min_size=min_size, algo=algo)


# ---------------------------------------------------------------------------
# Batch rename (FFX-I07) — destructive; defaults to safe dry_run preview
# ---------------------------------------------------------------------------

def rename_entries(
    path: str,
    kind: int,
    name_seed: str,
    *,
    rules: list[RenameRule],
    case_sensitive: bool = True,
    match_mode: str = "substring",
    dry_run: bool = True,
    confirm: bool = False,
) -> RenameReport:
    """Walk *path*, filter by *name_seed*, and rename matched entries.

    Thin passthrough to :func:`ff_explorer.rename.rename_entries`.

    Safety guards (identical to remove_entries / compress_entries):

    1. *name_seed* must be non-empty and non-whitespace —
       ``EmptySeedError`` otherwise.
    2. *dry_run=True* (the default) returns the planned old-to-new mapping
       without touching the filesystem.
    3. Passing ``confirm`` as ``True`` alongside ``dry_run`` as ``False``
       is the only way to perform an actual rename.  Both flags must be set
       explicitly — the defaults are safe.

    Collision detection is performed before any mutation.  When any collision
    is detected the batch is refused and ``RenameReport.collisions`` is
    populated; no rename is performed.

    Parameters
    ----------
    path:
        Root directory to walk.  Must be an existing directory.
    kind:
        ``0`` — FOLDERS, ``1`` — FILES.
    name_seed:
        Non-empty filter pattern.  Blank raises ``EmptySeedError``.
    rules:
        Ordered list of :class:`~ff_explorer.rename.RenameRule` objects
        applied to each matched filename in sequence.
    case_sensitive:
        Case-sensitive name matching (default ``True``).
    match_mode:
        ``"substring"`` (default), ``"glob"``, or ``"regex"``.
    dry_run:
        When ``True`` (default), return the preview mapping without renaming.
    confirm:
        Explicit opt-in token; must be set ``True`` together with ``dry_run``
        set ``False`` to actually rename entries.

    Returns
    -------
    RenameReport
        ``.matched``    — matched file/folder names.
        ``.mapping``    — planned (old_name, new_name) pairs.
        ``.renamed``    — (old_path, new_path) pairs actually renamed.
        ``.collisions`` — collision descriptions (non-empty means batch refused).
        ``.failed``     — per-file OSError pairs.
        ``.undo_file``  — path to the undo JSON, or ``None``.
        ``.dry_run``    — mirrors the *dry_run* parameter.

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If the gate conditions are not met, or *path* is not a directory.
    """
    return _rename_entries(
        path,
        EntryKind(int(kind)),
        name_seed,
        rules=rules,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        dry_run=dry_run,
        confirm=confirm,
    )


def replay_undo(undo_file: str) -> list[tuple[str, str]]:
    """Reverse a rename batch recorded in *undo_file*.

    Thin passthrough to :func:`ff_explorer.rename.replay_undo`.

    Parameters
    ----------
    undo_file:
        Absolute path to the ``.json`` undo file written by
        :func:`rename_entries`.

    Returns
    -------
    list[tuple[str, str]]
        ``[(attempted_new_path, original_path), ...]`` for each entry where
        the reverse rename was attempted.

    Raises
    ------
    FileNotFoundError
        If *undo_file* does not exist.
    ValueError
        If the file is not valid JSON.
    """
    return _replay_undo(undo_file)


# ---------------------------------------------------------------------------
# Index lifecycle — FFX-I10 (non-destructive; no dry_run/confirm gate)
# ---------------------------------------------------------------------------

def start_index(root: str) -> None:
    """Build an in-memory name index for *root* and start a watchdog observer.

    If *root* is already indexed, this is a no-op (the existing index is kept).

    Parameters
    ----------
    root:
        Root directory to index.  Must be an existing directory.

    Raises
    ------
    FileNotFoundError
        If *root* does not exist or is not a directory.  (The underlying
        ``IndexManager.start_index`` raises ``ValueError`` in that case; this
        wrapper converts it to ``FileNotFoundError`` so the REST layer can map
        it to HTTP 404, consistent with the service error-mapping convention.)
    ImportError
        If the ``watchdog`` package is not installed.
    """
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        raise FileNotFoundError(
            f"start_index: root does not exist or is not a directory: {root!r}"
        )
    try:
        _IndexManager.start_index(root_path)
    except ValueError as exc:
        # IndexManager also raises ValueError for bad roots (belt-and-suspenders)
        raise FileNotFoundError(str(exc)) from exc


def stop_index(root: str) -> None:
    """Stop the watchdog observer and drop the index for *root*.

    If *root* is not currently indexed, this is a no-op.

    Parameters
    ----------
    root:
        Root directory whose index should be stopped.
    """
    _IndexManager.stop_index(root)


def index_status(root: str) -> dict:
    """Return whether *root* is currently indexed.

    Parameters
    ----------
    root:
        Root directory to query.

    Returns
    -------
    dict
        ``{"root": str, "indexed": bool}``
    """
    indexed = _IndexManager.is_indexed(root)
    return {"root": root, "indexed": indexed}


# ---------------------------------------------------------------------------
# Size aggregation — FFX-I11 (non-destructive; no dry_run/confirm gate)
# ---------------------------------------------------------------------------

def largest_entries(
    path: str,
    top_n: int = 50,
    *,
    name_seed: str = "",
) -> list[SizedEntry]:
    """Return the *top_n* largest files under *path*, sorted largest first.

    Thin passthrough to :func:`ff_explorer.core.largest_entries`.

    Parameters
    ----------
    path:
        Root directory to walk.  Must be an existing directory.
    top_n:
        Number of results to return.  Must be ≥ 1 — raises ``ValueError``
        otherwise (maps to HTTP 422 in the REST layer).  Default ``50``.
    name_seed:
        Optional substring filter on the filename.  Empty string (default)
        aggregates the whole tree.  Empty is allowed here — this is a
        non-destructive query.

    Returns
    -------
    list[SizedEntry]
        At most *top_n* :class:`~ff_explorer.core.SizedEntry` objects, each
        with ``path`` (str) and ``size`` (int bytes), sorted descending by
        size; ties broken by path ascending.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist or is not a directory.
    ValueError
        If *top_n* is less than 1.
    """
    return _core_largest_entries(path, top_n, name_seed=name_seed)
