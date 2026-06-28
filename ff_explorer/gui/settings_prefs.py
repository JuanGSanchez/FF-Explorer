"""
FF Explorer — persisted UI preferences (SPEC-20)
Juan García Sánchez, 2023-2026
License: GPLv3

Persists and restores the durable form defaults across restarts:
  - last root path
  - search mode (folders / files)
  - selected action (combo index)
  - filter-panel option states (match mode, case-sensitive, include_hidden,
    size fields, respect-ignore, search-archives, versioning)

Date filters and the content-query field are intentionally excluded:
date ranges are highly session-specific and the content query is transient.

Persistence pattern mirrors theme.py:
  - Same OS config directory (QStandardPaths AppConfigLocation / fallback
    ~/.config/ff-explorer/).
  - Separate file ``settings.json`` so theme.json stays independent.
  - FFE_PREFS_CONFIG_DIR env-var override for tests (analogous to
    FFE_THEME_CONFIG_DIR in theme.py).
  - Graceful degradation: corrupt or missing file → return defaults, no crash.
  - OSError / json.JSONDecodeError are caught, logged at WARNING level, and
    swallowed; callers always get a usable dict back.

Exports
-------
DEFAULTS        : dict  — canonical default settings (read-only reference)
load_settings() : () → dict
save_settings(d): (dict) → None
_config_path()  : () → Path  (also used by tests for monkeypatching)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical defaults
# ---------------------------------------------------------------------------

#: Canonical default settings dict.  This is the ground-truth for the schema;
#: any key not present in a loaded file is filled from here.
DEFAULTS: dict[str, Any] = {
    "last_root": "",
    "mode": "folders",          # "folders" | "files"
    "action_index": 0,          # index into _ACTION_LABELS order
    "match_mode_index": 0,      # index into _MATCH_MODE_LABELS order
    "case_sensitive": True,
    "min_size": 0,              # KB; 0 = no bound
    "max_size": 0,              # KB; 0 = no bound
    "respect_ignore": False,
    "include_hidden": True,
    "search_archives": False,
    "versioning": False,
}


# ---------------------------------------------------------------------------
# Config path
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    """Return the path to the preferences JSON file.

    Resolution order (mirrors theme.py ``_config_path``):
    1. ``FFE_PREFS_CONFIG_DIR`` env-var (for tests).
    2. ``QStandardPaths.AppConfigLocation`` (platform user-config dir).
    3. ``~/.config/ff-explorer/`` stdlib fallback.
    """
    override = os.environ.get("FFE_PREFS_CONFIG_DIR")
    if override:
        return Path(override) / "settings.json"

    try:
        from PySide6.QtCore import QStandardPaths
        dirs = QStandardPaths.standardLocations(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        if dirs:
            return Path(dirs[0]) / "ff-explorer" / "settings.json"
    except Exception:
        pass

    return Path.home() / ".config" / "ff-explorer" / "settings.json"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_settings() -> dict[str, Any]:
    """Load persisted preferences from the user config file.

    Returns
    -------
    dict
        The persisted settings with any missing keys filled from
        ``DEFAULTS``.  Always returns a usable dict — never raises.
    """
    path = _config_path()
    result: dict[str, Any] = dict(DEFAULTS)

    if not path.exists():
        return result

    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            _logger.warning(
                "settings.json: expected a JSON object, got %s — using defaults",
                type(data).__name__,
            )
            return result
        # Merge: only recognise known keys; fill gaps from DEFAULTS.
        for key, default_val in DEFAULTS.items():
            if key in data and type(data[key]) == type(default_val):  # noqa: E721
                result[key] = data[key]
            elif key in data:
                # Type mismatch — keep default (corrupt value).
                _logger.warning(
                    "settings.json: key %r has unexpected type %s (expected %s)"
                    " — using default",
                    key, type(data[key]).__name__, type(default_val).__name__,
                )
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        _logger.warning(
            "settings.json: failed to load (%s: %s) — using defaults",
            type(exc).__name__, exc,
        )

    return result


def save_settings(settings: dict[str, Any]) -> None:
    """Persist *settings* to the user config file.

    Parameters
    ----------
    settings:
        Dict of preference values (keys from ``DEFAULTS``).  Unknown keys are
        silently ignored.  Always writes only the known schema keys.

    Never raises — OSError is caught and logged at WARNING level.
    """
    path = _config_path()
    # Only persist recognised keys.
    to_write = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_write, indent=2), encoding="utf-8")
    except OSError as exc:
        _logger.warning(
            "settings.json: failed to save (%s: %s)",
            type(exc).__name__, exc,
        )
