"""
FF Explorer — real-time name index (FFX-I10)
Juan García Sánchez, 2023-2026
License: GPLv3

Provides an opt-in, per-root, in-memory name index with watchdog-backed
incremental updates so queries can be served without a full tree walk.

Public API
----------
NameIndex
    build()               — one-time walk to populate the index.
    add_path(path)        — add a single path to the index.
    remove_path(path)     — remove a single path from the index.
    move_path(src, dst)   — atomically rename src→dst in the index.
    query(name_seed, *, case_sensitive=False, match_mode="substring")
                          — return list[Path] of matching indexed paths.

IndexManager  (module-level singleton)
    start_index(root)     — build index + start watchdog observer for root.
    stop_index(root)      — stop observer + drop index for root.
    is_indexed(root)      — True when root has an active index.
    get_index(root)       — return NameIndex for root, or None.

Headless invariant: NO tkinter / PySide6 / fastapi / fastmcp imports here.
watchdog is imported lazily inside start_index so the module is importable
without watchdog installed; a clear ImportError is raised only when starting
an observer.
"""

from __future__ import annotations

import os
import re
import fnmatch
import threading
from pathlib import Path
from typing import TYPE_CHECKING

# Reuse core's matching helpers to keep predicate semantics in sync.
# Import only the pure helper functions — no GUI/transport symbols.
from ff_explorer.core import _build_matcher, _matches  # type: ignore[attr-defined]

if TYPE_CHECKING:  # pragma: no cover
    from watchdog.observers import Observer  # noqa: F401 — type hint only


# ---------------------------------------------------------------------------
# NameIndex
# ---------------------------------------------------------------------------

class NameIndex:
    """
    In-memory index: filename → set of absolute Paths.

    All mutators are thread-safe (guarded by an internal RLock).
    Public mutators (add_path, remove_path, move_path) can be called directly
    from tests to simulate filesystem events without running a real observer.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        # Map: lowercased filename → set of resolved absolute Paths
        # We store both the original-case filename in a secondary structure
        # and the actual Path objects so query can return real paths.
        # Primary map: Path.name (original case) → set[Path]
        self._index: dict[str, set[Path]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """
        Walk the root directory once and populate the index.

        Uses a straightforward os.walk (no ignore-file pruning) consistent
        with the conservative fall-back contract: when advanced filters are
        active, list_entries falls back to the full walk anyway.
        """
        new_index: dict[str, set[Path]] = {}
        for dirpath, dirnames, filenames in os.walk(str(self._root)):
            current = Path(dirpath).resolve()
            # Index directories themselves (for FOLDERS queries)
            for dname in dirnames:
                p = (current / dname).resolve()
                new_index.setdefault(dname, set()).add(p)
            # Index files
            for fname in filenames:
                p = (current / fname).resolve()
                new_index.setdefault(fname, set()).add(p)
        with self._lock:
            self._index = new_index

    # ------------------------------------------------------------------
    # Incremental mutators (public — tests call these directly)
    # ------------------------------------------------------------------

    def add_path(self, path: Path | str) -> None:
        """Add *path* to the index (create / moved-in event)."""
        p = Path(path).resolve()
        name = p.name
        with self._lock:
            self._index.setdefault(name, set()).add(p)

    def remove_path(self, path: Path | str) -> None:
        """Remove *path* from the index (delete / moved-out event)."""
        p = Path(path).resolve()
        name = p.name
        with self._lock:
            paths = self._index.get(name)
            if paths is not None:
                paths.discard(p)
                if not paths:
                    del self._index[name]

    def move_path(self, src: Path | str, dst: Path | str) -> None:
        """Rename *src* → *dst* in the index (rename / moved event)."""
        self.remove_path(src)
        self.add_path(dst)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        name_seed: str = "",
        *,
        case_sensitive: bool = False,
        match_mode: str = "substring",
    ) -> list[Path]:
        """
        Return all indexed paths whose filename matches *name_seed*.

        Parameters mirror core's list_entries matching contract:
        - match_mode: "substring" | "glob" | "regex"
        - case_sensitive: controls case for substring and glob modes; for
          regex, it is applied at compile time (re.IGNORECASE when False).
        - Empty name_seed matches all indexed entries.

        Raises
        ------
        InvalidRegexError (from core)
            When match_mode="regex" and name_seed is not a valid pattern.
        ValueError
            When match_mode is not one of the three supported values.
        """
        # Delegate pattern compilation to core to keep semantics in sync.
        compiled_pattern, _ = _build_matcher(name_seed, match_mode, case_sensitive)

        results: list[Path] = []
        with self._lock:
            for name, paths in self._index.items():
                if _matches(name, name_seed, case_sensitive,
                            match_mode, compiled_pattern):
                    results.extend(paths)
        return results


# ---------------------------------------------------------------------------
# IndexManager — module-level singleton
# ---------------------------------------------------------------------------

class _IndexManager:
    """
    Lifecycle manager for per-root NameIndex instances.

    Only indexed roots occupy memory; unregistered roots are not present.
    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # root (resolved Path) → (NameIndex, Observer)
        self._entries: dict[Path, tuple[NameIndex, "Observer"]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_index(self, root: Path | str) -> NameIndex:
        """
        Build an index for *root* and start a watchdog observer.

        If *root* is already indexed, returns the existing index without
        rebuilding.

        Raises
        ------
        ImportError
            When watchdog is not installed in the environment.
        ValueError
            When *root* does not exist or is not a directory.
        """
        # Lazy import — only here, so the rest of index.py is importable
        # without watchdog installed.
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "watchdog is required for real-time indexing; "
                "install it with: pip install 'watchdog>=4,<7'"
            ) from exc

        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise ValueError(f"start_index: root must be an existing directory: {root!r}")

        with self._lock:
            if root_path in self._entries:
                return self._entries[root_path][0]

            index = NameIndex(root_path)
            index.build()

            # Build a concrete handler class from the lazy import.
            _idx = index  # close over local

            class _Handler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory:
                        _idx.add_path(event.src_path)
                    else:
                        _idx.add_path(event.src_path)

                def on_deleted(self, event):
                    _idx.remove_path(event.src_path)

                def on_moved(self, event):
                    _idx.move_path(event.src_path, event.dest_path)

                def on_modified(self, event):
                    # Name hasn't changed on modify; nothing to update.
                    pass

            observer = Observer()
            observer.schedule(_Handler(), str(root_path), recursive=True)
            observer.start()

            self._entries[root_path] = (index, observer)
            return index

    def stop_index(self, root: Path | str) -> None:
        """Stop the observer and drop the index for *root*."""
        root_path = Path(root).resolve()
        with self._lock:
            entry = self._entries.pop(root_path, None)
        if entry is not None:
            index_obj, observer = entry
            observer.stop()
            observer.join()

    def is_indexed(self, root: Path | str) -> bool:
        """Return True when *root* has an active index."""
        root_path = Path(root).resolve()
        with self._lock:
            return root_path in self._entries

    def get_index(self, root: Path | str) -> NameIndex | None:
        """Return the NameIndex for *root*, or None if not indexed."""
        root_path = Path(root).resolve()
        with self._lock:
            entry = self._entries.get(root_path)
            return entry[0] if entry is not None else None


# Module-level singleton — import and use directly.
IndexManager = _IndexManager()
