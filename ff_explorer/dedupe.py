"""
ff_explorer.dedupe
==================
Headless, stdlib-only duplicate-file detection by content hash.

Algorithm
---------
1. Walk *path* recursively, collecting file sizes.
2. Files smaller than *min_size* are skipped (default 1 — skips 0-byte files;
   empty files are trivially "identical" and the default excludes them to
   avoid misleading results).
3. Bucket files by (integer) size; any bucket with only one file cannot
   contain a duplicate — those files are never hashed (limits I/O).
4. Within each multi-file size bucket, hash file contents in 64 KiB chunks
   using *algo* (``"blake2b"`` by default, ``"sha256"`` also supported).
5. Collect all paths that share the same hash; return only groups of ≥ 2.

Unreadable files (OSError on open/read) are silently skipped; the walk
continues and the result is never aborted.

No tkinter / PySide6 / fastapi / fastmcp imports — headless, stdlib only.
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field

__all__ = [
    "DuplicateGroup",
    "find_duplicates",
]

_CHUNK = 65_536  # 64 KiB read chunks
_SUPPORTED_ALGOS = frozenset({"blake2b", "sha256"})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DuplicateGroup:
    """A group of files with identical content.

    Attributes
    ----------
    hash:
        Hex digest of the shared content hash.
    size:
        File size in bytes (all members share the same size).
    paths:
        Sorted list of absolute file paths that are byte-for-byte identical.
    """
    hash: str
    size: int
    paths: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_duplicates(
    path: str,
    *,
    min_size: int = 1,
    algo: str = "blake2b",
) -> list[DuplicateGroup]:
    """Walk *path* recursively and return groups of duplicate files.

    Parameters
    ----------
    path:
        Root directory to search.  Must be an existing directory; raises
        ``ValueError`` otherwise (matches :func:`ff_explorer.core.list_entries`
        behaviour).
    min_size:
        Minimum file size in bytes (inclusive).  Files strictly smaller than
        this value are skipped.  Default ``1`` excludes 0-byte files, which
        are trivially "equal" but rarely interesting as duplicates.  Pass
        ``0`` to include empty files.
    algo:
        Hash algorithm.  ``"blake2b"`` (default, faster on modern hardware)
        or ``"sha256"``.  ``ValueError`` is raised for any other value.

    Returns
    -------
    list[DuplicateGroup]
        Each group contains two or more files with identical content.
        Groups are sorted by size descending then hash ascending for a
        stable, deterministic output order.  Paths within each group are
        sorted lexicographically.

    Raises
    ------
    ValueError
        If *path* is not an existing directory, or *algo* is not supported.
    OSError
        Not raised — unreadable files are silently skipped.
    """
    if algo not in _SUPPORTED_ALGOS:
        raise ValueError(
            f"Unsupported algo {algo!r}; choose from {sorted(_SUPPORTED_ALGOS)}"
        )

    root = path
    if not os.path.isdir(root):
        raise ValueError(
            f"{root!r} is not an existing directory."
        )

    # ------------------------------------------------------------------
    # Phase 1 — bucket files by size
    # ------------------------------------------------------------------
    size_buckets: dict[int, list[str]] = defaultdict(list)

    for dirpath, _dirnames, filenames in os.walk(root):
        for fname in filenames:
            fpath = os.path.join(dirpath, fname)
            try:
                fsize = os.path.getsize(fpath)
            except OSError:
                continue  # unreadable stat — skip
            if fsize < min_size:
                continue
            size_buckets[fsize].append(fpath)

    # ------------------------------------------------------------------
    # Phase 2 — hash within multi-file buckets
    # ------------------------------------------------------------------
    hash_buckets: dict[str, list[str]] = defaultdict(list)

    for fsize, fpaths in size_buckets.items():
        if len(fpaths) < 2:
            continue  # lone file — cannot be a duplicate; skip hashing

        for fpath in fpaths:
            digest = _hash_file(fpath, algo)
            if digest is None:
                continue  # unreadable file — skip
            bucket_key = f"{fsize}:{digest}"
            hash_buckets[bucket_key].append(fpath)

    # ------------------------------------------------------------------
    # Phase 3 — collect groups of ≥ 2
    # ------------------------------------------------------------------
    groups: list[DuplicateGroup] = []
    for bucket_key, fpaths in hash_buckets.items():
        if len(fpaths) < 2:
            continue
        raw_size, hex_digest = bucket_key.split(":", 1)
        groups.append(
            DuplicateGroup(
                hash=hex_digest,
                size=int(raw_size),
                paths=sorted(fpaths),
            )
        )

    # Stable sort: largest files first (most impactful), then hash for tie-breaking
    groups.sort(key=lambda g: (-g.size, g.hash))
    return groups


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hash_file(path: str, algo: str) -> str | None:
    """Return the hex digest of *path* using *algo*, or ``None`` on OSError."""
    try:
        if algo == "blake2b":
            h = hashlib.blake2b()
        else:
            h = hashlib.new(algo)
        with open(path, "rb") as fh:
            while chunk := fh.read(_CHUNK):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None
