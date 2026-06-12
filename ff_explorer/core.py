"""
FF Explorer — core service layer
Juan García Sánchez, 2023-2026
License: GPLv3

Public API
----------
Pure query (no side effects):
    list_entries(path, kind, name_seed, *, case_sensitive=True) -> list[MatchEntry]
    entry_metadata(path) -> dict

Guarded destructive operations:
    save_listing(path, kind, name_seed, *, case_sensitive=True) -> Path
    remove_entries(path, kind, name_seed, *, case_sensitive=True,
                   dry_run=True, confirm=False) -> RemovalReport
    compress_entries(path, kind, name_seed, *, case_sensitive=True,
                     dry_run=True, confirm=False) -> CompressionReport

Typed errors:
    FFExplorerError  — base class for all structured errors from this module
    EmptySeedError   — raised when name_seed is blank/whitespace-only for a
                       destructive operation (reject-empty-seed guard)
"""

from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Sequence

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

    # Convenience — stringifies to the absolute path for easy display/serialisation
    def __str__(self) -> str:
        return str(self.path)


@dataclass
class RemovalReport:
    """Returned by remove_entries regardless of dry_run state."""
    matched: list[Path] = field(default_factory=list)
    removed: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)
    dry_run: bool = True

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_path(path: str | Path) -> Path:
    """Return an absolute, resolved Path, raising ValueError for missing dirs."""
    p = Path(path).resolve()
    if not p.is_dir():
        raise ValueError(f"path must be an existing directory, got: {path!r}")
    return p


def _matches(name: str, seed: str, case_sensitive: bool) -> bool:
    """True when *seed* is contained in *name* (case-sensitive by option)."""
    if not case_sensitive:
        return seed.lower() in name.lower()
    return seed in name


def _guard_destructive_seed(name_seed: str, operation: str) -> None:
    """Raise EmptySeedError if name_seed is blank; used by all destructive ops."""
    if not name_seed or not name_seed.strip():
        raise EmptySeedError(operation)


# ---------------------------------------------------------------------------
# Pure query operations  (NO side effects)
# ---------------------------------------------------------------------------

def list_entries(
    path: str | Path,
    kind: EntryKind | int,
    name_seed: str = "",
    *,
    case_sensitive: bool = True,
) -> list[MatchEntry]:
    """
    Traverse *path* recursively and return every entry whose name contains
    *name_seed* as a substring.

    Parameters
    ----------
    path:
        Root directory to walk.  Must exist and be a directory.
    kind:
        EntryKind.FOLDERS (0) — collect subdirectory names.
        EntryKind.FILES   (1) — collect file names.
    name_seed:
        Substring filter.  Empty string matches everything (query-only; safe
        here because this function is non-destructive).
    case_sensitive:
        When False the match is lowercased on both sides.  Default True
        (preserves legacy behaviour).

    Returns
    -------
    list[MatchEntry]
        Ordered as os.walk yields (top-down, breadth-first per directory).
        Each entry carries the resolved absolute Path and its EntryKind.

    Raises
    ------
    ValueError
        If *path* does not exist or is not a directory.
    """
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))
    results: list[MatchEntry] = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        current = Path(dirpath)
        if kind == EntryKind.FOLDERS:
            for name in dirnames:
                if _matches(name, name_seed, case_sensitive):
                    results.append(MatchEntry(path=current / name, kind=EntryKind.FOLDERS))
        else:
            for name in filenames:
                if _matches(name, name_seed, case_sensitive):
                    results.append(MatchEntry(path=current / name, kind=EntryKind.FILES))

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
            try:
                fp.write(str(entry.path) + "\n")
            except OSError:
                # Write a blank line as a placeholder so the index row count
                # matches the match count; do not silently swallow all errors.
                fp.write("\n")

    return out_path


def remove_entries(
    path: str | Path,
    kind: EntryKind | int,
    name_seed: str,
    *,
    case_sensitive: bool = True,
    dry_run: bool = True,
    confirm: bool = False,
) -> RemovalReport:
    """
    Walk *path*, filter by *name_seed*, and remove matched entries.

    Safety guards (applied before any mutation):
    1. *name_seed* must be non-empty and non-whitespace — EmptySeedError otherwise.
    2. *dry_run=True* (the default) returns what WOULD be removed without
       touching the filesystem.
    3. *confirm=True* is required alongside *dry_run=False* to actually remove.

    Removal strategy:
    - When *send2trash* is installed, matched items are moved to the OS recycle
      bin / trash (recoverable).
    - When *send2trash* is not installed, files are removed via os.remove() and
      directories via shutil.rmtree().  This is permanent — prefer installing
      send2trash for production use.

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
        Must be True when dry_run=False.  Acts as an explicit opt-in token.

    Returns
    -------
    RemovalReport
        .matched  — all paths that matched the filter
        .removed  — paths successfully removed (empty on dry_run)
        .failed   — [(path, error_message), ...] for any removal error
        .dry_run  — mirrors the dry_run parameter

    Raises
    ------
    EmptySeedError
        If name_seed is blank or whitespace-only.
    ValueError
        If dry_run=False but confirm=False, or if *path* is not a directory.
    """
    _guard_destructive_seed(name_seed, "remove_entries")
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))

    if not dry_run and not confirm:
        raise ValueError(
            "remove_entries() requires confirm=True when dry_run=False.  "
            "Set both dry_run=False and confirm=True to actually remove entries."
        )

    matches = list_entries(root_path, kind, name_seed, case_sensitive=case_sensitive)
    matched_paths = [e.path for e in matches]
    report = RemovalReport(matched=matched_paths, dry_run=dry_run)

    if dry_run:
        return report

    # Live removal path
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
        except Exception as exc:  # noqa: BLE001
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

    matches = list_entries(root_path, kind, name_seed, case_sensitive=case_sensitive)
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
                    except Exception as exc:  # noqa: BLE001
                        report.failed.append((fl, str(exc)))
            report.archives.append(archive_path)
            # Delete originals (compression is the recovery mechanism)
            for fl in matched_paths:
                if not any(f == fl for f, _ in report.failed):
                    try:
                        os.remove(fl)
                    except Exception as exc:  # noqa: BLE001
                        report.failed.append((fl, f"post-compress delete failed: {exc}"))
        except Exception as exc:  # noqa: BLE001
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
                        except Exception as exc:  # noqa: BLE001
                            report.failed.append((item_path, str(exc)))
                report.archives.append(archive_path)
                # Delete original folder
                try:
                    shutil.rmtree(fd, ignore_errors=False)
                except Exception as exc:  # noqa: BLE001
                    report.failed.append((fd, f"post-compress delete failed: {exc}"))
            except Exception as exc:  # noqa: BLE001
                report.failed.append((fd, str(exc)))

    return report
