"""
ff_explorer.presets
===================
Headless JSON-backed preset store for saved searches and bookmarks.

A **preset** is a named bundle of query/action parameters that can be persisted,
listed, retrieved by name, and executed via :func:`ff_explorer.api.service.run_preset`.

Storage
-------
All presets live in a single ``presets.json`` file inside a per-user config directory
resolved in priority order:

1. ``$FFE_PRESETS_DIR`` (env var, used by tests to isolate the store).
2. ``%APPDATA%/ff-explorer`` on Windows.
3. ``$XDG_CONFIG_HOME/ff-explorer`` on POSIX (falls back to ``~/.config/ff-explorer``
   when ``$XDG_CONFIG_HOME`` is unset).

No third-party library (``platformdirs``) is required.

Headless purity
---------------
This module imports nothing from tkinter, PySide6, FastAPI, or FastMCP.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

__all__ = [
    "Preset",
    "save_preset",
    "list_presets",
    "get_preset",
    "delete_preset",
    "presets_file",
]

_VALID_OPERATIONS = frozenset({"list", "remove", "compress"})


@dataclass
class Preset:
    """A saved query/action bundle.

    Fields
    ------
    name:
        Unique identifier for the preset.  Used as the look-up key.
    path:
        Root directory to walk when the preset is run.
    kind:
        ``0`` — FOLDERS, ``1`` — FILES  (mirrors ``EntryKind``).
    name_seed:
        Pattern/substring filter (may be empty for list-only presets).
    case_sensitive:
        Case-sensitive name matching.
    match_mode:
        ``"substring"`` | ``"glob"`` | ``"regex"``.
    min_size:
        Minimum file size in bytes (inclusive); ``None`` = no bound.
    max_size:
        Maximum file size in bytes (inclusive); ``None`` = no bound.
    modified_after:
        Epoch float lower bound on mtime; ``None`` = no bound.
    modified_before:
        Epoch float upper bound on mtime; ``None`` = no bound.
    extensions:
        List of extension strings (e.g. ``[".txt", "log"]``); ``None`` = no filter.
    respect_ignore:
        Honour ``.gitignore`` / ``.ignore`` files during the walk.
    ignore_globs:
        Extra gitwildmatch glob patterns; ``None`` = no extra exclusions.
    operation:
        ``"list"`` (default) | ``"remove"`` | ``"compress"``.  Destructive
        operations are still subject to the ``dry_run``/``confirm`` gate at
        runtime.
    """

    name: str
    path: str
    kind: int = 1
    name_seed: str = ""
    case_sensitive: bool = True
    match_mode: str = "substring"
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    modified_after: Optional[float] = None
    modified_before: Optional[float] = None
    extensions: Optional[list[str]] = None
    respect_ignore: bool = False
    ignore_globs: Optional[list[str]] = None
    operation: str = "list"


# ---------------------------------------------------------------------------
# Config-dir resolution
# ---------------------------------------------------------------------------

def _config_dir() -> Path:
    """Return the config directory path (not necessarily existing yet)."""
    env_override = os.environ.get("FFE_PRESETS_DIR")
    if env_override:
        return Path(env_override)

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "ff-explorer"
        # Fallback when APPDATA is unset (unusual).
        return Path.home() / "AppData" / "Roaming" / "ff-explorer"

    # POSIX
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ff-explorer"
    return Path.home() / ".config" / "ff-explorer"


def presets_file() -> Path:
    """Return the path to ``presets.json`` (file may not exist yet)."""
    return _config_dir() / "presets.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_raw() -> dict[str, dict]:
    """Load the raw preset dict from disk.

    Returns an empty dict if the file is absent, empty, or corrupt —
    mirroring the tolerant behaviour used elsewhere in the project.
    """
    fp = presets_file()
    if not fp.exists():
        return {}
    try:
        text = fp.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        data = json.loads(text)
        if not isinstance(data, dict):
            return {}
        return data
    except (json.JSONDecodeError, OSError):
        return {}


def _save_raw(data: dict[str, dict]) -> None:
    """Persist the raw preset dict to disk, creating the directory if needed."""
    fp = presets_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _dict_to_preset(d: dict) -> Preset:
    """Reconstruct a :class:`Preset` from a plain dict, ignoring unknown keys."""
    known = {f for f in Preset.__dataclass_fields__}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in d.items() if k in known}
    return Preset(**filtered)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_preset(preset: Preset) -> None:
    """Upsert *preset* into the JSON store (keyed by ``preset.name``).

    Parameters
    ----------
    preset:
        The preset to save.  ``preset.name`` must be non-empty.

    Raises
    ------
    ValueError
        If ``preset.name`` is empty/whitespace, or ``preset.operation`` is not
        one of ``"list"``, ``"remove"``, ``"compress"``.
    """
    if not preset.name or not preset.name.strip():
        raise ValueError("Preset name must be non-empty.")
    if preset.operation not in _VALID_OPERATIONS:
        raise ValueError(
            f"Invalid operation {preset.operation!r}; "
            f"must be one of {sorted(_VALID_OPERATIONS)}."
        )
    data = _load_raw()
    data[preset.name] = asdict(preset)
    _save_raw(data)


def list_presets() -> list[Preset]:
    """Return all stored presets in insertion order.

    Returns an empty list if the store file is absent, empty, or corrupt.
    """
    data = _load_raw()
    result: list[Preset] = []
    for raw in data.values():
        try:
            result.append(_dict_to_preset(raw))
        except (TypeError, KeyError):
            # Skip malformed entries rather than crashing.
            pass
    return result


def get_preset(name: str) -> Preset:
    """Return the preset identified by *name*.

    Raises
    ------
    KeyError
        If no preset with that name exists.
    """
    data = _load_raw()
    if name not in data:
        raise KeyError(f"No preset named {name!r}.")
    return _dict_to_preset(data[name])


def delete_preset(name: str) -> None:
    """Remove the preset identified by *name* from the store.

    Raises
    ------
    KeyError
        If no preset with that name exists.
    """
    data = _load_raw()
    if name not in data:
        raise KeyError(f"No preset named {name!r}.")
    del data[name]
    _save_raw(data)
