"""
FF Explorer — core service layer
Juan García Sánchez, 2023-2026
License: GPLv3

Public API
----------
Pure query (no side effects):
    list_entries(path, kind, name_seed, *, case_sensitive=True,
                 match_mode="substring",
                 min_size=None, max_size=None,
                 modified_after=None, modified_before=None,
                 extensions=None,
                 respect_ignore=False, ignore_globs=None,
                 search_archives=False,
                 content_query=None, content_max_bytes=CONTENT_MAX_BYTES) -> list[MatchEntry]
    entry_metadata(path) -> dict
    largest_entries(path, top_n=50, *, name_seed="") -> list[SizedEntry]
    find_duplicates(path, *, min_size=0, algo="sha256") -> list[DuplicateGroup]

Guarded destructive operations:
    save_listing(path, kind, name_seed, *, case_sensitive=True) -> Path
    remove_entries(path, kind, name_seed, *, case_sensitive=True,
                   dry_run=True, confirm=False, versioning=False) -> RemovalReport
    compress_entries(path, kind, name_seed, *, case_sensitive=True,
                     dry_run=True, confirm=False) -> CompressionReport
    rename_entries(path, kind, name_seed, *, rules=None, case_sensitive=True,
                   match_mode="substring", dry_run=True, confirm=False) -> RenameReport

Typed errors:
    FFExplorerError          — base class for all structured errors from this module
    EmptySeedError           — raised when name_seed is blank/whitespace-only for a
                               destructive operation (reject-empty-seed guard)
    InvalidRegexError        — raised when match_mode="regex" is given an invalid
                               pattern; subclasses both FFExplorerError and ValueError
                               so callers can catch it as ValueError (maps to HTTP 422)
    ContentSearchUngatedError — raised when content_query is given without any
                               name/type/size pre-filter; subclasses both
                               FFExplorerError and ValueError (maps to HTTP 422)

Filter parameters (list_entries only):
    min_size / max_size:
        Filter by file size in bytes (inclusive).  Directories are skipped
        silently — no size concept for dirs; dirs always pass the size filter.
    modified_after / modified_before:
        Epoch float (seconds since Unix epoch).  Filters on mtime (last
        modification timestamp).  Applies to both files and directories.
    extensions:
        Iterable of file-extension strings (e.g. [".txt", "log"] — leading
        dot optional).  Matched case-insensitively.  Applies to FILES only;
        directories always pass the extensions filter (no extension concept).
    respect_ignore:
        When True, skip paths matching .gitignore / .ignore patterns (gitwildmatch).
    ignore_globs:
        Optional list of additional patterns to ignore (combined with gitignore if
        respect_ignore=True).
    search_archives:
        When True, treat ZIP/TAR/GZ/BZ2 files as navigable containers. Results include
        internal members as read-only paths (archive.zip!member). Destructive ops on
        archive-internal paths are forbidden.
    content_query:
        Grep-style search inside file contents (substring or regex). Requires a pre-filter
        (non-empty name_seed, extensions, or size bounds) for performance gating.
        Raises ContentSearchUngatedError if ungated. Binaries skipped, max_bytes enforced.
    All predicates combine with AND.  Default values reproduce the exact pre-filter result set.

match_mode parameter:
    "substring" (default) — case-aware `in` test; behaviour unchanged.
    "glob"                — fnmatch.fnmatch / fnmatch.fnmatchcase (*.log, test_*.py, etc).
    "regex"               — re.Pattern compiled once per call (not per entry).
                            Invalid pattern raises InvalidRegexError.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Iterable, Sequence

import pathspec  # gitwildmatch ignore-file support (FFX-I04; hard dep)

from ff_explorer.content_search import (  # FFX-I09
    CONTENT_MAX_BYTES,
    file_content_matches as _file_content_matches,
)

try:
    from send2trash import send2trash as _send2trash  # type: ignore[import-untyped]
    _SEND2TRASH_AVAILABLE = True
except ImportError:  # pragma: no cover — send2trash not installed
    _SEND2TRASH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Enumerations & data types
# ---------------------------------------------------------------------------

class EntryKind(IntEnum):
    """Maps directly to the legacy d_type values (0 = folders, 1 = files)."""
    FOLDERS = 0
    FILES = 1


@dataclass(frozen=True)
class MatchEntry:
    """A single result from list_entries."""
    path: Path
    kind: EntryKind
    # True when this entry is an archive-internal member (not a real filesystem path).
    # Archive-internal entries use the form ``<archive_path>!<member/name>`` in *path*.
    # Defaults to False so all existing construction sites remain valid unchanged.
    in_archive: bool = False

    # Convenience — stringifies to the absolute path for easy display/serialisation
    def __str__(self) -> str:
        return str(self.path)


@dataclass(frozen=True)
class SizedEntry:
    """A single result from largest_entries — a file path with its byte size."""
    path: str
    size: int


@dataclass
class RemovalReport:
    """Returned by remove_entries regardless of dry_run state."""
    matched: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    dry_run: bool = True
    # FFX-I08: when versioning=True, the timestamped version directory used
    # for this removal batch (e.g. "<root>/.ffe-versions/YYYYMMDD-HHMMSS").
    # None when versioning=False or on a dry_run.
    versioned_to: str | None = None

    @property
    def would_affect(self) -> list[Path]:
        """Paths that would be / were targeted (preview list)."""
        return self.matched


@dataclass
class CompressionReport:
    """Returned by compress_entries regardless of dry_run state."""
    matched: list[Path] = field(default_factory=list)
    archives: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    dry_run: bool = True

    @property
    def would_affect(self) -> list[Path]:
        """Paths that would be / were compressed (preview list)."""
        return self.matched


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------

class FFExplorerError(Exception):
    """Base class for structured errors raised by this module."""


class EmptySeedError(FFExplorerError):
    """
    Raised when a destructive operation is called with a blank or
    whitespace-only name_seed.

    An empty seed would match every entry under the path — a data-loss
    amplifier.  Pass an explicit non-empty seed, or use list_entries with
    an empty seed to enumerate everything first and pass the result to the
    destructive function manually.
    """

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"{operation}() requires a non-empty name_seed.  "
            "An empty seed would match every entry under the path.  "
            "Pass a non-empty seed, or call list_entries() first and "
            "review the match list before acting."
        )
        self.operation = operation


class InvalidRegexError(FFExplorerError, ValueError):
    """
    Raised when ``match_mode="regex"`` is supplied an invalid regex pattern.

    Inherits from both ``FFExplorerError`` and ``ValueError`` so that:
    - callers using ``except ValueError`` catch it (REST layer maps it to 422),
    - callers using ``except FFExplorerError`` also catch it.

    Attributes
    ----------
    pattern : str
        The pattern string that failed to compile.
    """

    def __init__(self, pattern: str, original: re.error) -> None:
        super().__init__(
            f"Invalid regex pattern {pattern!r}: {original}"
        )
        self.pattern = pattern
        self.original = original


class ContentSearchUngatedError(FFExplorerError, ValueError):
    """
    Raised when ``content_query`` is supplied to ``list_entries`` without any
    accompanying name/type/size pre-filter.

    Requiring a pre-filter is a deliberate performance gate: content search
    (grep-inside-files) is expensive on large trees.  At least one of
    ``name_seed`` (non-empty), ``extensions``, ``min_size``, ``max_size``,
    ``modified_after``, or ``modified_before`` must be active so the candidate
    set is bounded before file I/O begins.

    Inherits from both ``FFExplorerError`` and ``ValueError`` so that:
    - callers using ``except ValueError`` catch it (REST layer maps it to 422),
    - callers using ``except FFExplorerError`` also catch it.
    """

    def __init__(self) -> None:
        super().__init__(
            "content_query requires at least one name/type/size pre-filter to be "
            "active (non-empty name_seed, extensions, min_size, max_size, "
            "modified_after, or modified_before).  "
            "An ungated content search would scan every file in the tree."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_path(path: str | Path) -> Path:
    """Return an absolute, resolved Path, raising ValueError for missing dirs."""
    p = Path(path).resolve()
    if not p.is_dir():
        raise ValueError(f"path must be an existing directory, got: {path!r}")
    return p


def _build_matcher(
    seed: str,
    match_mode: str,
    case_sensitive: bool,
) -> "tuple[re.Pattern[str] | None, str | None]":
    """
    Compile and return the matcher state for the given mode.

    Returns
    -------
    (pattern, normalised_seed)
        For ``"regex"``: (compiled re.Pattern, None).
        For ``"glob"``:  (None, seed) — fnmatch handles normalisation.
        For ``"substring"``: (None, seed).

    Raises
    ------
    InvalidRegexError
        When match_mode is ``"regex"`` and *seed* is not a valid pattern.
    ValueError
        When match_mode is not one of the three supported values.
    """
    if match_mode not in ("substring", "glob", "regex"):
        raise ValueError(
            f"match_mode must be 'substring', 'glob', or 'regex'; got {match_mode!r}"
        )
    if match_mode == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(seed, flags)
        except re.error as exc:
            raise InvalidRegexError(seed, exc) from exc
        return compiled, None
    # glob / substring — no pre-compilation needed
    return None, seed


def _matches(
    name: str,
    seed: str,
    case_sensitive: bool,
    match_mode: str = "substring",
    _compiled: "re.Pattern[str] | None" = None,
) -> bool:
    """
    True when *name* matches *seed* according to *match_mode*.

    Parameters
    ----------
    name:
        The filename to test.
    seed:
        The pattern/substring to match against.
    case_sensitive:
        Controls case sensitivity for substring and glob modes.
        For regex mode, case is governed by the compiled pattern's flags
        (set in ``_build_matcher``); this flag is ignored at call time.
    match_mode:
        ``"substring"`` — ``seed in name`` test (default; legacy behaviour).
        ``"glob"``       — fnmatch test.
        ``"regex"``      — pre-compiled pattern search.
    _compiled:
        Pre-compiled ``re.Pattern`` for regex mode (must be provided when
        match_mode is ``"regex"``).
    """
    if match_mode == "regex":
        assert _compiled is not None, "_compiled must be provided for regex mode"
        return _compiled.search(name) is not None
    if match_mode == "glob":
        if case_sensitive:
            return fnmatch.fnmatchcase(name, seed)
        return fnmatch.fnmatch(name.lower(), seed.lower())
    # substring (default)
    if not case_sensitive:
        return seed.lower() in name.lower()
    return seed in name


def _normalise_extensions(extensions: Iterable[str] | None) -> frozenset[str] | None:
    """
    Normalise an extensions iterable to a frozenset of lowercase dotted strings.

    ``"txt"`` and ``".txt"`` both become ``".txt"``.
    Returns ``None`` when the input is ``None`` or empty (no filter).
    """
    if extensions is None:
        return None
    normalised = frozenset(
        (ext if ext.startswith(".") else f".{ext}").lower()
        for ext in extensions
    )
    return normalised if normalised else None


def _passes_filters(
    entry_path: Path,
    is_file: bool,
    stat: "os.stat_result | None",
    min_size: int | None,
    max_size: int | None,
    modified_after: float | None,
    modified_before: float | None,
    ext_set: frozenset[str] | None,
) -> bool:
    """
    Return True when *entry_path* passes all supplied filters.

    Filter semantics (all predicates are AND-combined):

    size (min_size / max_size):
        Applies to FILES only.  Directories always pass the size filter
        (no meaningful "size" for a directory at the OS level).
    modified_after / modified_before:
        Applies to both files and directories via mtime.
    extensions (ext_set):
        Applies to FILES only.  Directories always pass.

    *stat* must be pre-fetched when any filter is active; pass ``None``
    only when all filter args are None (no-op fast path).
    """
    # --- size filter (files only) ---
    if is_file and (min_size is not None or max_size is not None):
        sz = stat.st_size if stat is not None else entry_path.stat().st_size
        if min_size is not None and sz < min_size:
            return False
        if max_size is not None and sz > max_size:
            return False

    # --- mtime filter (files and dirs) ---
    if modified_after is not None or modified_before is not None:
        mtime = stat.st_mtime if stat is not None else entry_path.stat().st_mtime
        if modified_after is not None and mtime <= modified_after:
            return False
        if modified_before is not None and mtime >= modified_before:
            return False

    # --- extension filter (files only) ---
    if is_file and ext_set is not None:
        suffix = entry_path.suffix.lower()
        if suffix not in ext_set:
            return False

    return True


def _guard_destructive_seed(name_seed: str, operation: str) -> None:
    """Raise EmptySeedError if name_seed is blank; used by all destructive ops."""
    if not name_seed or not name_seed.strip():
        raise EmptySeedError(operation)


# _IGNORE_FILE_NAMES — filenames whose contents are treated as gitwildmatch
# ignore patterns during a respect_ignore walk (FFX-I04).
_IGNORE_FILE_NAMES: tuple[str, ...] = (".gitignore", ".ignore")


def _build_ignore_spec(
    directory: Path,
    parent_spec: "pathspec.PathSpec | None",
    extra_globs: "list[str] | None",
    read_files: bool = True,
) -> "pathspec.PathSpec | None":
    """
    Build (or extend) a ``pathspec.PathSpec`` for *directory*.

    Optionally reads ``.gitignore`` / ``.ignore`` files found directly in
    *directory* (controlled by *read_files*), merges their patterns with
    *parent_spec* (inherited from ancestor dirs) and any *extra_globs*
    (caller-supplied literal globs).  Returns a new combined ``PathSpec``,
    or ``None`` when there are no patterns at all (fast path).

    The returned spec's ``match_file`` is called with paths *relative to the
    walk root* — the caller is responsible for computing the correct relative
    path before testing.

    Parameters
    ----------
    directory:
        The directory being entered during the walk.
    parent_spec:
        The accumulated spec from ancestor directories (may be ``None``).
    extra_globs:
        Additional glob patterns supplied by the caller (``ignore_globs``).
        These are applied even when *read_files* is ``False``.
    read_files:
        When ``True`` (default), reads ``.gitignore`` / ``.ignore`` files in
        *directory*.  When ``False``, disk files are skipped — only
        *parent_spec* and *extra_globs* contribute.
    """
    patterns: list[str] = []

    # Inherit parent patterns first so subtree narrowing (nested .gitignore)
    # adds to, never replaces, the ancestor rules.
    if parent_spec is not None:
        # Re-extract the underlying patterns from the existing spec so we can
        # build a single merged PathSpec (pathspec doesn't expose a merge API).
        for pat in parent_spec.patterns:
            patterns.append(pat.pattern)

    # Read ignore files present in *directory* (only when respect_ignore=True).
    if read_files:
        for fname in _IGNORE_FILE_NAMES:
            candidate = directory / fname
            try:
                text = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                # Skip blank lines and comments (gitwildmatch convention).
                if stripped and not stripped.startswith("#"):
                    patterns.append(stripped)

    # Caller-supplied extra globs are always merged.
    if extra_globs:
        patterns.extend(extra_globs)

    if not patterns:
        return None

    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _is_ignored(
    entry_path: Path,
    spec: "pathspec.PathSpec | None",
    spec_root: Path,
    is_dir: bool = False,
) -> bool:
    """
    Return True when *entry_path* is matched by *spec*.

    *spec_root* is the walk root; the match is performed with a path relative
    to *spec_root* so gitignore anchoring works correctly.

    When *is_dir* is True, the relative path is tested both without and with a
    trailing ``/`` so that gitignore patterns like ``build/`` (which only match
    the directory token, not bare ``build``) are correctly honoured.

    Returns False when *spec* is ``None`` (no patterns active).
    """
    if spec is None:
        return False
    try:
        rel = entry_path.relative_to(spec_root)
    except ValueError:
        return False
    # Use POSIX separators for consistent behaviour on Windows.
    rel_str = rel.as_posix()
    if spec.match_file(rel_str):
        return True
    # For directories, also test with a trailing slash so that patterns like
    # ``build/`` match the directory entry itself (not just its contents).
    if is_dir:
        return spec.match_file(rel_str + "/")
    return False


# ---------------------------------------------------------------------------
# Archive-transparency helper  (FFX-I05 — read-only, query path only)
# ---------------------------------------------------------------------------

#: Extensions recognised as archive containers for FFX-I05 search_archives.
_ARCHIVE_EXTENSIONS: frozenset[str] = frozenset(
    {".zip", ".tar", ".gz", ".tgz", ".bz2"}
)


def _enumerate_archive_members(
    archive_path: Path,
    name_seed: str,
    case_sensitive: bool,
    match_mode: str,
    compiled_pattern: "re.Pattern[str] | None",
) -> list[MatchEntry]:
    """Open *archive_path* read-only and return MatchEntry objects for every
    internal member whose bare name matches the seed/mode/case settings.

    The returned entries use ``<archive_path>!<member_name>`` as *path* and
    have ``in_archive=True``.  The function never raises — malformed or
    unreadable archives are silently skipped (returns an empty list).

    Only stdlib ``zipfile`` and ``tarfile`` are used; no new dependency.
    """
    suffix = archive_path.suffix.lower()
    # .gz files that are NOT .tar.gz are plain compressed blobs (no member list);
    # only process them as tar when they look like .tar.gz/.tgz.
    # Bare .gz: skip — no member-name concept.
    results: list[MatchEntry] = []

    try:
        if suffix == ".zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    member = info.filename
                    # Strip trailing slash (directories inside zip)
                    bare = member.rstrip("/").split("/")[-1]
                    if not bare:
                        continue
                    if _matches(bare, name_seed, case_sensitive,
                                match_mode, compiled_pattern):
                        results.append(MatchEntry(
                            path=Path(f"{archive_path}!{member}"),
                            kind=EntryKind.FILES,
                            in_archive=True,
                        ))

        elif suffix in {".tar", ".tgz"} or (
            suffix == ".gz" and archive_path.stem.endswith(".tar")
        ) or (suffix == ".bz2" and archive_path.stem.endswith(".tar")):
            # tarfile.open handles .tar, .tar.gz (.tgz), .tar.bz2 transparently.
            with tarfile.open(archive_path, "r:*") as tf:
                for member in tf.getmembers():
                    bare = member.name.rstrip("/").split("/")[-1]
                    if not bare:
                        continue
                    if _matches(bare, name_seed, case_sensitive,
                                match_mode, compiled_pattern):
                        results.append(MatchEntry(
                            path=Path(f"{archive_path}!{member.name}"),
                            kind=EntryKind.FILES,
                            in_archive=True,
                        ))

        # .gz suffix without .tar stem = plain gzip blob; no member enumeration.

    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError):
        # Malformed / truncated / unreadable archive — skip gracefully.
        pass

    return results


# ---------------------------------------------------------------------------
# Pure query operations  (NO side effects)
# ---------------------------------------------------------------------------

def list_entries(
    path: str | Path,
    kind: EntryKind | int,
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
) -> list[MatchEntry]:
    """
    Traverse *path* recursively and return every entry whose name matches
    *name_seed* under the requested *match_mode*, further narrowed by the
    optional structured filters.

    Parameters
    ----------
    path:
        Root directory to walk.  Must exist and be a directory.
    kind:
        EntryKind.FOLDERS (0) — collect subdirectory names.
        EntryKind.FILES   (1) — collect file names.
    name_seed:
        Pattern/substring filter.  Empty string matches everything (query-only;
        safe because this function is non-destructive).
    case_sensitive:
        When False the match is lowercased on both sides.  Default True
        (preserves legacy behaviour).  For ``match_mode="regex"`` the flag is
        applied at pattern-compile time (re.IGNORECASE).
    match_mode:
        ``"substring"`` (default) — ``seed in name`` containment test.
        ``"glob"``       — fnmatch glob pattern (``*``, ``?``, ``[…]``).
        ``"regex"``      — full regular expression; pattern is compiled once
                           per call, not per entry.
    min_size:
        Minimum file size in bytes (inclusive).  Applies to FILES only;
        directories always pass.  Default None (no lower bound).
    max_size:
        Maximum file size in bytes (inclusive).  Applies to FILES only.
        Default None (no upper bound).
    modified_after:
        Epoch float (seconds).  Only entries with mtime *strictly after* this
        value are returned.  Applies to both files and directories.
        Default None (no lower bound).
    modified_before:
        Epoch float (seconds).  Only entries with mtime *strictly before* this
        value are returned.  Applies to both files and directories.
        Default None (no upper bound).
    extensions:
        Iterable of extension strings (with or without leading dot, e.g.
        ``[".txt", "log"]``).  Matched case-insensitively.  Applies to FILES
        only; directories always pass.  Default None (no extension filter).
    respect_ignore:
        When ``True``, discover and honour ``.gitignore`` / ``.ignore`` files
        encountered during the walk.  Each ignore file applies only to its own
        subtree (layered/nested precedence).  Ignored directories are pruned
        so their contents are never visited.  Default ``False`` — results are
        byte-for-byte identical to the pre-FFX-I04 output.
    ignore_globs:
        Additional gitwildmatch glob patterns applied regardless of
        ``respect_ignore``.  Paths matching any of these patterns are
        excluded.  ``None`` (default) means no extra exclusions.
    search_archives:
        When ``True`` (FILES mode only), each matched archive file whose
        extension is one of ``.zip``, ``.tar``, ``.tar.gz``/``.tgz``,
        ``.tar.bz2`` is opened read-only and its internal member names are
        tested against *name_seed*/*match_mode*/*case_sensitive*.  A hit is
        returned as a :class:`MatchEntry` with ``in_archive=True`` and
        ``path`` set to ``<archive_path>!<member/name>``.

        Default ``False`` — results are byte-for-byte identical to the
        pre-FFX-I05 output.  Malformed or unreadable archives are skipped
        silently.  **Never set True on a destructive path** — archive-internal
        entries are not real filesystem paths and cannot be removed or
        compressed.
    content_query:
        Optional grep-style content filter (FFX-I09).  When provided, only
        FILES whose text content contains a match are returned.  Directories
        are never excluded by this filter.  The match uses the same
        *match_mode* and *case_sensitive* settings as the name filter (regex
        patterns are compiled once per call).  Binary files (null-byte
        heuristic) and files larger than *content_max_bytes* are silently
        skipped (treated as no-match).  Unreadable files are silently skipped.

        **Performance gate**: *content_query* requires at least one of
        ``name_seed`` (non-empty), ``extensions``, ``min_size``, ``max_size``,
        ``modified_after``, or ``modified_before`` to be active.  An ungated
        content search would scan every file in the tree and is rejected with
        :class:`ContentSearchUngatedError`.

        Default ``None`` — no content filtering; results are byte-for-byte
        identical to the pre-FFX-I09 output.
    content_max_bytes:
        Maximum file size in bytes scanned for content matching.  Files
        larger than this cap are silently skipped (treated as no-match).
        Default :data:`ff_explorer.content_search.CONTENT_MAX_BYTES` (10 MiB).
        Ignored when *content_query* is ``None``.

    Returns
    -------
    list[MatchEntry]
        Ordered as os.walk yields (top-down, breadth-first per directory).
        Each entry carries the resolved absolute Path and its EntryKind.
        Archive-internal entries have ``in_archive=True``.

    Raises
    ------
    ValueError
        If *path* does not exist or is not a directory, or if *match_mode* is
        not one of ``"substring"``, ``"glob"``, ``"regex"``.
    InvalidRegexError
        If *match_mode* is ``"regex"`` and *name_seed* is not a valid pattern.
        (Also a subtype of ``ValueError``.)
    ContentSearchUngatedError
        If *content_query* is provided but no name/type/size pre-filter is
        active.  (Also a subtype of ``ValueError``.)
    """
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))

    # Compile matcher once (raises InvalidRegexError early for bad regex)
    compiled_pattern, _ = _build_matcher(name_seed, match_mode, case_sensitive)

    # Normalise extension set once
    ext_set = _normalise_extensions(extensions)

    # FFX-I09: content_query gate — at least one name/type/size pre-filter must
    # be active.  An ungated content search would scan every file in the tree.
    if content_query is not None:
        _has_prefilter = (
            bool(name_seed)           # non-empty name seed
            or ext_set is not None    # extension filter
            or min_size is not None   # size lower bound
            or max_size is not None   # size upper bound
            or modified_after is not None   # date lower bound
            or modified_before is not None  # date upper bound
        )
        if not _has_prefilter:
            raise ContentSearchUngatedError()

        # Compile the content regex separately from the name regex.
        # compiled_pattern applies to *name_seed* — content_query is a
        # different string and needs its own pattern object.
        if match_mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                _content_compiled: "re.Pattern[str] | None" = re.compile(
                    content_query, flags
                )
            except re.error as exc:
                raise InvalidRegexError(content_query, exc) from exc
        else:
            _content_compiled = None
    else:
        _content_compiled = None

    # Determine whether any structured filter is active to avoid stat() overhead
    # when no filters are requested (hot path: exact legacy behaviour).
    needs_stat = (
        min_size is not None
        or max_size is not None
        or modified_after is not None
        or modified_before is not None
        or ext_set is not None
    )

    # Ignore-awareness is active when either flag is set (FFX-I04).
    use_ignore = respect_ignore or bool(ignore_globs)

    # FFX-I10: index routing — serve from the in-memory name index when:
    #   • the root has an active index (opt-in per root)
    #   • no advanced filter is active that the index does not model
    #     (size/date/extension/content/archive/ignore)
    # Any active advanced filter falls back to the live walk for correctness.
    _use_index = (
        not needs_stat
        and not use_ignore
        and not search_archives
        and content_query is None
    )
    if _use_index:
        # Lazy import — keeps the rest of core.py importable without index.py
        # being available, and avoids a circular import at module load time.
        try:
            from ff_explorer.index import IndexManager as _IndexManager  # noqa: PLC0415
            _idx = _IndexManager.get_index(root_path)
        except Exception:  # pragma: no cover — import failure is non-fatal
            _idx = None

        if _idx is not None:
            # Route query to the index.
            matched_paths = _idx.query(
                name_seed,
                case_sensitive=case_sensitive,
                match_mode=match_mode,
            )
            # Filter by kind: the index holds both files and dirs; stat each to
            # determine type.  Paths that no longer exist are silently dropped.
            index_results: list[MatchEntry] = []
            for p in matched_paths:
                try:
                    is_dir = p.is_dir()
                except OSError:  # pragma: no cover
                    continue
                if kind == EntryKind.FOLDERS and is_dir:
                    index_results.append(MatchEntry(path=p, kind=EntryKind.FOLDERS))
                elif kind == EntryKind.FILES and not is_dir:
                    index_results.append(MatchEntry(path=p, kind=EntryKind.FILES))
            return index_results

    results: list[MatchEntry] = []

    # Per-directory spec cache: maps absolute dirpath -> PathSpec|None.
    # Built lazily as os.walk descends; the root entry is seeded before the
    # loop so the root's own ignore file is honoured for its direct children.
    dir_specs: dict[Path, "pathspec.PathSpec | None"] = {}

    if use_ignore:
        # Seed the root: any root-level .gitignore/.ignore + caller extra globs.
        # read_files=respect_ignore: only read disk files when the flag is on.
        dir_specs[root_path] = _build_ignore_spec(
            root_path, None, ignore_globs, read_files=respect_ignore
        )

    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath)

        if use_ignore:
            # Retrieve the inherited spec for *current* (set by parent iteration
            # or seeded for root above).
            current_spec = dir_specs.get(current)

            # Prune ignored subdirectories IN-PLACE so os.walk never descends.
            # Also pre-compute each surviving child's spec for the next level.
            surviving_dirs: list[str] = []
            for dname in dirnames:
                child = current / dname
                if _is_ignored(child, current_spec, root_path, is_dir=True):
                    continue  # prune — do not descend
                surviving_dirs.append(dname)
                # Build the child's own spec (inherits current + child's own
                # ignore files).  Store it so the next iteration can retrieve it.
                # read_files=respect_ignore: only read disk files when the flag is on.
                dir_specs[child] = _build_ignore_spec(
                    child, current_spec, ignore_globs, read_files=respect_ignore
                )
            # Mutate dirnames in-place: os.walk only descends into what remains.
            dirnames[:] = surviving_dirs

            # Filter filenames by ignore spec.
            filenames = [
                f for f in filenames
                if not _is_ignored(current / f, current_spec, root_path)
            ]

        if kind == EntryKind.FOLDERS:
            for name in dirnames:
                if not _matches(name, name_seed, case_sensitive,
                                match_mode, compiled_pattern):
                    continue
                entry_path = current / name
                if needs_stat:
                    try:
                        stat = entry_path.stat()
                    except OSError:
                        continue
                    if not _passes_filters(
                        entry_path, False, stat,
                        min_size, max_size,
                        modified_after, modified_before,
                        ext_set,
                    ):
                        continue
                results.append(MatchEntry(path=entry_path, kind=EntryKind.FOLDERS))
        else:
            for name in filenames:
                if not _matches(name, name_seed, case_sensitive,
                                match_mode, compiled_pattern):
                    continue
                entry_path = current / name
                if needs_stat:
                    try:
                        stat = entry_path.stat()
                    except OSError:
                        continue
                    if not _passes_filters(
                        entry_path, True, stat,
                        min_size, max_size,
                        modified_after, modified_before,
                        ext_set,
                    ):
                        continue
                # FFX-I09: content filter (files only; directories never excluded)
                if content_query is not None:
                    if not _file_content_matches(
                        entry_path,
                        content_query,
                        match_mode,
                        case_sensitive,
                        content_max_bytes,
                        _compiled=_content_compiled,
                    ):
                        continue
                results.append(MatchEntry(path=entry_path, kind=EntryKind.FILES))

            # FFX-I05: archive transparency — enumerate members of any archive
            # file found in the current directory when search_archives is True.
            # This is independent of whether the archive's own name matched;
            # we inspect every archive in *filenames* (post-ignore-filter).
            if search_archives:
                for name in filenames:
                    entry_path = current / name
                    if entry_path.suffix.lower() not in _ARCHIVE_EXTENSIONS:
                        continue
                    results.extend(
                        _enumerate_archive_members(
                            entry_path,
                            name_seed,
                            case_sensitive,
                            match_mode,
                            compiled_pattern,
                        )
                    )

    return results


def entry_metadata(path: str | Path) -> dict:
    """
    Return size, modification time, and type for *path*.

    Parameters
    ----------
    path:
        Absolute or relative path to a file or directory that exists.

    Returns
    -------
    dict with keys:
        "path"       – str — absolute path
        "type"       – str — "file" | "directory" | "symlink" | "other"
        "size_bytes" – int — file size in bytes (0 for directories)
        "mtime"      – float — last-modification timestamp (epoch seconds)
        "exists"     – bool

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"path does not exist: {path!r}")

    stat = p.stat()
    if p.is_symlink():
        entry_type = "symlink"
    elif p.is_file():
        entry_type = "file"
    elif p.is_dir():
        entry_type = "directory"
    else:
        entry_type = "other"

    return {
        "path": str(p),
        "type": entry_type,
        "size_bytes": stat.st_size,
        "mtime": stat.st_mtime,
        "exists": True,
    }


# ---------------------------------------------------------------------------
# Destructive operations  (guarded — dry_run=True by default)
# ---------------------------------------------------------------------------

def save_listing(
    path: str | Path,
    kind: EntryKind | int,
    name_seed: str = "",
    *,
    case_sensitive: bool = True,
) -> Path:
    """
    Walk *path*, filter by *name_seed*, and write a plain-text listing file.

    The output file is written to *path* with a name derived from the search
    parameters: ``directory-<fl|fd>[-<seed>].txt``.

    Parameters
    ----------
    path, kind, name_seed, case_sensitive:
        Same semantics as list_entries.

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
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))
    matches = list_entries(root_path, kind, name_seed, case_sensitive=case_sensitive)

    prefix = "fl" if kind == EntryKind.FILES else "fd"
    separator = "-" if name_seed else ""
    filename = f"directory-{prefix}{separator}{name_seed}.txt"
    out_path = root_path / filename

    with open(out_path, "w", encoding="utf-8") as fp:
        for entry in matches:
            fp.write(str(entry.path) + "\n")

    return out_path


def remove_entries(
    path: str | Path,
    kind: EntryKind | int,
    name_seed: str,
    *,
    case_sensitive: bool = True,
    dry_run: bool = True,
    confirm: bool = False,
    versioning: bool = False,
) -> RemovalReport:
    """
    Walk *path*, filter by *name_seed*, and remove matched entries.

    Safety guards (applied before any mutation):
    1. *name_seed* must be non-empty and non-whitespace — EmptySeedError otherwise.
    2. *dry_run=True* (the default) returns what WOULD be removed without
       touching the filesystem.
    3. *confirm=True* is required alongside *dry_run=False* to actually remove.

    Removal strategy:
    - When *versioning=False* (default) and *send2trash* is installed, matched
      items are moved to the OS recycle bin / trash (recoverable).
    - When *versioning=False* and *send2trash* is not installed, items are
      permanently deleted via stdlib primitives.  Prefer installing send2trash
      for production use.
    - When *versioning=True*, matched items are moved into a timestamped
      directory ``<path>/.ffe-versions/YYYYMMDD-HHMMSS/`` preserving relative
      path structure.  The timestamp is computed once per call so all items in
      a batch land under the same version directory.  The ``.ffe-versions``
      directory is excluded from matching so previously versioned items are
      never re-targeted in a subsequent run.

    Parameters
    ----------
    path:
        Root directory to walk.
    kind:
        EntryKind.FOLDERS or EntryKind.FILES.
    name_seed:
        Non-empty substring filter.  Blank seed raises EmptySeedError.
    case_sensitive:
        Case-sensitive name matching (default True).
    dry_run:
        When True (default), return the preview list without removing anything.
    confirm:
        Must be True when dry_run is False.  Acts as an explicit opt-in token.
    versioning:
        When True, instead of sending items to the recycle bin, move them into
        ``<path>/.ffe-versions/<YYYYMMDD-HHMMSS>/`` preserving relative
        structure.  Default False preserves the existing send2trash /
        stdlib-delete behaviour exactly.

    Returns
    -------
    RemovalReport
        .matched      — all paths that matched the filter
        .removed      — paths successfully removed (empty on dry_run)
        .failed       — [(path, error_message), ...] for any removal error
        .dry_run      — mirrors the dry_run parameter
        .versioned_to — the version directory used (str), or None

    Raises
    ------
    EmptySeedError
        If name_seed is blank or whitespace-only.
    ValueError
        If dry_run is False but confirm is also False, or path is not a dir.
    """
    _guard_destructive_seed(name_seed, "remove_entries")
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))

    if not dry_run and not confirm:
        raise ValueError(
            "remove_entries() requires confirm=True when dry_run=False.  "
            "Set both dry_run=False and confirm=True to actually remove entries."
        )

    # search_archives=False: destructive ops must never target archive-internal
    # entries (they are not real filesystem paths — invariant 2 / FFX-I05 guard).
    # ignore_globs=[".ffe-versions/"]: exclude the versioning store so previously
    # versioned items are never re-targeted in a subsequent call (FFX-I08).
    matches = list_entries(
        root_path, kind, name_seed, case_sensitive=case_sensitive,
        search_archives=False,
        ignore_globs=[".ffe-versions/"],
    )
    matched_paths = [e.path for e in matches]
    report = RemovalReport(matched=matched_paths, dry_run=dry_run)

    if dry_run:
        return report

    if versioning:
        # FFX-I08: move matched items into a timestamped version directory that
        # preserves their path relative to root_path so structure is recoverable.
        # Timestamp is computed once per call — all items in a batch share it.
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        version_dir = root_path / ".ffe-versions" / ts
        version_dir.mkdir(parents=True, exist_ok=True)
        report.versioned_to = str(version_dir)
        for entry_path in matched_paths:
            try:
                rel = entry_path.relative_to(root_path)
                dest = version_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(entry_path), str(dest))
                report.removed.append(entry_path)
            except OSError as exc:
                report.failed.append((entry_path, str(exc)))
        return report

    # Live removal path (versioning=False — default)
    for entry_path in matched_paths:
        try:
            if _SEND2TRASH_AVAILABLE:
                _send2trash(str(entry_path))
            else:
                if entry_path.is_file() or entry_path.is_symlink():
                    os.remove(entry_path)
                elif entry_path.is_dir():
                    shutil.rmtree(entry_path, ignore_errors=False)
            report.removed.append(entry_path)
        except OSError as exc:
            report.failed.append((entry_path, str(exc)))

    return report


def compress_entries(
    path: str | Path,
    kind: EntryKind | int,
    name_seed: str,
    *,
    case_sensitive: bool = True,
    dry_run: bool = True,
    confirm: bool = False,
) -> CompressionReport:
    """
    Walk *path*, filter by *name_seed*, compress matched entries into zip
    archive(s), then permanently delete the originals.

    Safety guards mirror remove_entries:
    1. Non-empty name_seed required — EmptySeedError otherwise.
    2. dry_run=True (default) returns the preview list without touching the
       filesystem.
    3. confirm=True required alongside dry_run=False to act.

    Compression layout:
    - FILES mode: all matched files are compressed into a single
      ``Compressed_data.zip`` placed directly in *path*.
    - FOLDERS mode: each matched folder is compressed into its own
      ``<folder_name>.zip`` placed directly in *path*.
      (Fixes legacy R-2 path-construction bug.)

    After successful compression, originals are permanently deleted via
    os.remove() / shutil.rmtree() (not the recycle bin — compressed copies
    are the recovery mechanism).

    Parameters
    ----------
    path, kind, name_seed, case_sensitive, dry_run, confirm:
        Same semantics as remove_entries.

    Returns
    -------
    CompressionReport
        .matched  — paths that matched the filter
        .archives — zip archive paths created (empty on dry_run)
        .failed   — [(path, error_message), ...]
        .dry_run  — mirrors the dry_run parameter

    Raises
    ------
    EmptySeedError
        If name_seed is blank or whitespace-only.
    ValueError
        If dry_run=False but confirm=False, or if *path* is not a directory.
    """
    _guard_destructive_seed(name_seed, "compress_entries")
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))

    if not dry_run and not confirm:
        raise ValueError(
            "compress_entries() requires confirm=True when dry_run=False.  "
            "Set both dry_run=False and confirm=True to actually compress entries."
        )

    # search_archives=False: destructive ops must never target archive-internal
    # entries (they are not real filesystem paths — invariant 2 / FFX-I05 guard).
    matches = list_entries(root_path, kind, name_seed, case_sensitive=case_sensitive,
                           search_archives=False)
    matched_paths = [e.path for e in matches]
    report = CompressionReport(matched=matched_paths, dry_run=dry_run)

    if dry_run:
        return report

    if kind == EntryKind.FILES:
        # All matched files → one archive
        archive_path = root_path / "Compressed_data.zip"
        try:
            with zipfile.ZipFile(
                archive_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True
            ) as zf:
                for fl in matched_paths:
                    try:
                        zf.write(fl, fl.name)  # arcname = bare filename
                    except OSError as exc:
                        report.failed.append((fl, str(exc)))
            report.archives.append(archive_path)
            # Delete originals (compression is the recovery mechanism)
            for fl in matched_paths:
                if not any(f == fl for f, _ in report.failed):
                    try:
                        os.remove(fl)
                    except OSError as exc:
                        report.failed.append((fl, f"post-compress delete failed: {exc}"))
        except OSError as exc:
            report.failed.append((archive_path, str(exc)))

    else:
        # FOLDERS mode — one archive per folder (R-2 fix: use pathlib for paths)
        for fd in matched_paths:
            archive_path = root_path / (fd.name + ".zip")  # FIX: was path+fd.split('\\')[-1]+'.zip'
            try:
                with zipfile.ZipFile(
                    archive_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True
                ) as zf:
                    for item in os.listdir(fd):
                        item_path = fd / item
                        try:
                            zf.write(item_path, item)
                        except OSError as exc:
                            report.failed.append((item_path, str(exc)))
                report.archives.append(archive_path)
                # Delete original folder
                try:
                    shutil.rmtree(fd, ignore_errors=False)
                except OSError as exc:
                    report.failed.append((fd, f"post-compress delete failed: {exc}"))
            except OSError as exc:
                report.failed.append((fd, str(exc)))

    return report


def largest_entries(
    path: str | Path,
    top_n: int = 50,
    *,
    name_seed: str = "",
) -> list[SizedEntry]:
    """Return the *top_n* largest files under *path*, sorted largest first.

    This is a non-destructive, headless size-aggregation query.  It walks the
    entire directory tree under *path* collecting files (not directories), reads
    their byte sizes via ``os.stat``, and returns the *top_n* largest in
    descending size order.  Unreadable files (``OSError`` on stat) are silently
    skipped, consistent with the rest of the core's walk semantics.

    Parameters
    ----------
    path:
        Root directory to walk.  Must be an existing directory.
    top_n:
        Number of results to return.  Must be ≥ 1; raises ``ValueError``
        otherwise (maps to HTTP 422 in the REST layer, consistent with existing
        core validation style).
    name_seed:
        Optional substring filter applied to the **filename** (not the full
        path).  An empty string (default) matches every file — the whole tree
        is aggregated.  This is a non-destructive query so an empty seed is
        explicitly allowed (unlike the destructive ops that reject it with
        ``EmptySeedError``).

    Returns
    -------
    list[SizedEntry]
        At most *top_n* entries, each carrying ``path`` (absolute path as
        ``str``) and ``size`` (bytes as ``int``).  Sorted descending by size;
        ties are broken by path string ascending so the result is fully
        deterministic.  When fewer files than *top_n* exist, all files are
        returned (no padding).

    Raises
    ------
    FileNotFoundError
        If *path* does not exist or is not a directory.
    ValueError
        If *top_n* is less than 1.
    """
    p = Path(path).resolve()
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(
            f"largest_entries: path does not exist or is not a directory: {path!r}"
        )
    if top_n < 1:
        raise ValueError(
            f"largest_entries: top_n must be >= 1, got {top_n!r}"
        )

    seed_lower = name_seed.lower() if name_seed else ""
    use_filter = bool(name_seed)

    sized: list[SizedEntry] = []
    for dirpath, _dirnames, filenames in os.walk(p):
        current = Path(dirpath)
        for name in filenames:
            if use_filter and seed_lower not in name.lower():
                continue
            entry_path = current / name
            try:
                size = entry_path.stat().st_size
            except OSError:
                continue
            sized.append(SizedEntry(path=str(entry_path), size=size))

    # Sort: descending by size, ascending by path for deterministic tie-breaking.
    sized.sort(key=lambda e: (-e.size, e.path))
    return sized[:top_n]
