"""
FF Explorer — centralized widget-info registry (SPEC-02 / SPEC-03)
Juan García Sánchez, 2023-2026
License: GPLv3

One module-level registry (WIDGET_INFO) holds ALL user-facing help/tooltip
text for every interactive widget in the FF Explorer GUI.  A single helper
(register_info) attaches tooltip + accessible description + WhatsThis to any
widget from one registry lookup.

Design contract
---------------
* ``WIDGET_INFO`` is the single source of truth for widget help text.
  Add new entries here; never inline string literals in setToolTip() calls.
* ``info_text(key)`` is the sole access point — wrapping it is the extension
  seam for a future i18n layer (SPEC-21).
* ``register_info(widget, key)`` is the only sanctioned way to attach info to
  a widget.  It sets tooltip, accessible description, WhatsThis, and a
  ``_ff_info_key`` dynamic property so SPEC-09 coverage tests can enumerate
  every registered widget.

Tooltip timing policy
---------------------
Qt's default tooltip delay is ~700 ms (show) and ~10 s (dismiss).  These
defaults are intentionally left unchanged; the framework manages timing.
The single ``QToolTip {}`` QSS block in ``theme.py`` (build_stylesheet) is
the only tooltip-style override — no per-widget QSS is applied here.

Dynamic tooltips (Action combobox)
-----------------------------------
The Action combobox updates its tooltip text based on the selected action.
The dynamic text is composed from registry keys ``"action"`` (base) and
``"action_detail.<code>"`` (per-action suffix).  The update helper in
MainWindow sources BOTH parts from this registry — no hard-coded strings at
the call site.

treemap_view.py path tooltips
------------------------------
_EntryRow.setToolTip(path) and the inner name_lbl.setToolTip(path) display
the full file path — genuinely dynamic per-tile data, not help-registry text.
Those calls are NOT routed through register_info because the text is data, not
help documentation.  However, accessible descriptions ARE set there (also from
the path variable) to satisfy SPEC-03's accessibility requirement.  The SPEC-09
grep lint targets string literals; ``path`` is a variable, so it passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


# ---------------------------------------------------------------------------
# Registry — single source of truth for all widget help text
# ---------------------------------------------------------------------------

WIDGET_INFO: dict[str, str] = {
    # ---- Main controls ----
    "path": (
        "Root path in which files or folders are searched."
    ),
    "path_browse": (
        "Root path in which files or folders are searched."
    ),
    "seed": (
        "List of consecutive characters contained in files/folders' name."
    ),
    "mode_folders": "Folders search.",
    "mode_files": "Files search.",
    "action": "Actions to be applied to the resulting directory.",

    # Per-action supplementary help text (appended to "action" base text)
    "action_detail.1": "\n   Save directory of files/folders found",
    "action_detail.2": "\n   Delete files/folders found",
    "action_detail.3": (
        "\n   For files, compress all in one .zip in root"
        "\n   For folders, compress each one in root"
    ),

    # ---- Utility buttons ----
    "filters_toggle": (
        "Expand to set match mode, size/date/extension filters."
    ),
    "settings": (
        "Open Settings to configure the application colour theme."
    ),
    "disk_usage": (
        "Show the largest files under the current root path."
    ),
    "find_duplicates": (
        "Find groups of files with identical content under the current root path.\n"
        "Results are shown in a read-only dialog."
    ),
    "batch_rename": (
        "Open the batch rename dialog to define a rule, preview changes,\n"
        "and apply renaming to matched entries."
    ),
    "preset_save": (
        "Save the current search form state as a named preset."
    ),
    "preset_load": (
        "Load a saved preset back into the search form."
    ),
    "live_index": (
        "Build an in-memory name index for the current root and watch for\n"
        "filesystem changes in real time.  Queries use the index instead of\n"
        "walking the tree.  Uncheck to stop and release the observer thread."
    ),

    # ---- Filter panel ----
    "filter_match_mode": (
        "Substring: seed 'in' name (default).\n"
        "Glob: fnmatch pattern (*, ?, […]).\n"
        "Regex: full regular expression."
    ),
    "filter_case_sensitive": (
        "When unchecked, the name match ignores case.\n"
        "For Regex mode, re.IGNORECASE is applied."
    ),
    "filter_min_size": "Minimum file size in KB (0 = no lower bound).",
    "filter_max_size": "Maximum file size in KB (0 = no upper bound).",
    "filter_date_after": (
        "Only include entries modified strictly after this date."
    ),
    "filter_date_after_edit": "Lower bound on modification date.",
    "filter_date_before": (
        "Only include entries modified strictly before this date."
    ),
    "filter_date_before_edit": "Upper bound on modification date.",
    "filter_extensions": (
        "Comma or space-separated extensions to include.\n"
        "Example: .txt, .md\n"
        "Leave empty for no extension filter."
    ),
    "filter_content_query": (
        "Grep-style search inside file contents.\n"
        "Only files whose content matches this query are returned.\n"
        "REQUIRES at least one name/extension/size filter to be set\n"
        "to limit the candidate set (performance gate)."
    ),
    "filter_search_archives": (
        "When checked, open matching ZIP/TAR/GZ archives and search their\n"
        "internal member names against the name seed.\n"
        "Archive-internal results are read-only and cannot be removed/compressed."
    ),
    "filter_respect_ignore": (
        "When checked, .gitignore and .ignore files found during the walk\n"
        "are honoured; matching paths are excluded from results."
    ),
    "filter_ignore_globs": (
        "Extra gitwildmatch glob patterns to exclude (comma or space separated).\n"
        "Applied regardless of the .gitignore checkbox above."
    ),
    "filter_versioning": (
        "When checked, removed entries are moved into a timestamped\n"
        "<root>/.ffe-versions/<YYYYMMDD-HHMMSS>/ directory instead of the\n"
        "recycle bin.  Provides a stronger, auditable recovery trail.\n"
        "Applies only to the 'Remove list' action."
    ),

    # ---- Settings dialog ----
    "settings_swatch": "Click to change colour",
    "settings_reset": "Restore the current template's default colours",
    "settings_apply": "Apply the current colours live without closing",
    "settings_cancel": "Revert to the theme active when the dialog was opened",
    "settings_ok": "Apply and save, then close",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def info_text(key: str) -> str:
    """Return the help text for *key* from the central registry.

    This is the single access point for registry lookups — wrapping it is the
    extension seam for a future i18n layer (SPEC-21).

    Parameters
    ----------
    key:
        A stable widget-id key present in ``WIDGET_INFO``.

    Raises
    ------
    KeyError
        When *key* is not present in the registry.  This is intentional: an
        unknown key means a widget was registered with a typo or missing entry.
    """
    return WIDGET_INFO[key]


def register_info(widget: "QWidget", key: str) -> None:
    """Attach help information to *widget* from the central registry.

    Sets (in order):
    1. ``widget.setToolTip(text)``       — hover tooltip (Qt singleton surface)
    2. ``widget.setAccessibleDescription(text)`` — accessibility / screen reader
    3. ``widget.setWhatsThis(text)``     — Shift+F1 / WhatsThis mode text
    4. ``widget.setProperty("_ff_info_key", key)`` — enumeration hook for SPEC-09

    This is the ONLY sanctioned way to attach help info to a widget.
    Never call ``widget.setToolTip(literal)`` directly in GUI modules.

    Parameters
    ----------
    widget:
        Any QWidget subclass (QLineEdit, QPushButton, QComboBox, etc.).
    key:
        A stable widget-id key in ``WIDGET_INFO``.

    Raises
    ------
    KeyError
        When *key* is not in the registry (programmer error — fail fast).
    """
    text = info_text(key)
    widget.setToolTip(text)
    widget.setAccessibleDescription(text)
    widget.setWhatsThis(text)
    widget.setProperty("_ff_info_key", key)
