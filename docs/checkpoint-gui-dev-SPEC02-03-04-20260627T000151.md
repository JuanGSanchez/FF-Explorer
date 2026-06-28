# Checkpoint: SPEC-02, SPEC-03, SPEC-04 implementation

**Status**: IN-PROGRESS  
**Date**: 2026-06-27T00:01:51  
**Branch**: enhancement/ff-explorer-20260625

## Plan

### SPEC-02: widget_info.py registry
- Create `ff_explorer/gui/widget_info.py` with:
  - `WIDGET_INFO: dict[str, str]` — all help texts keyed by stable IDs
  - `info_text(key: str) -> str` — single lookup function for i18n wrapper
  - Migrate all `_HELP_*` constants from main_window.py into the registry
  - Migrate all inline `setToolTip("...")` literals from:
    - main_window.py (lines ~353,374,387,400,414,428,435,450,491,500,518,527,536,545,555,564,578,594,607,617,629,640)
    - settings_dialog.py (lines ~99,252,259,264,270)
    - treemap_view.py (lines ~120,143 — these are dynamic PATH tooltips, NOT help-registry entries; exempt but add accessible descriptions)

### SPEC-03: register_info(widget, key) helper
- Add `register_info(widget, key)` in widget_info.py:
  - Sets setToolTip(text), setAccessibleDescription(text), setWhatsThis(text)
  - Sets dynamic property `_ff_info_key` for SPEC-09 coverage enumeration
- Replace ALL direct setToolTip("...literal...") in main_window.py and settings_dialog.py with `register_info(widget, "key")`
- Special case: _update_action_tooltip stays dynamic but sources from registry

### SPEC-04: theme cleanup + keyboard help + style overrides
- Remove per-widget setStyleSheet overrides in main_window.py (lines ~254,266,276,287,294,306,314,325,336)
  - Migrate needed styling to theme.py build_stylesheet() via objectName-based QSS selectors
  - The inline section-label styling (bold 12pt, gray bg) → add QSS selector by objectName
  - Browse/Run/path_edit/radio-buttons inherit from central theme naturally
- Keep theme.py's single `QToolTip {}` block as the only tooltip style source
- Add Shift+F1 keyboard shortcut for QWhatsThis.enterWhatsThisMode()
- Document tooltip timing policy (Qt default = 700ms show delay, 10s dismiss)

### Files to change
1. NEW: `ff_explorer/gui/widget_info.py`
2. EDIT: `ff_explorer/gui/main_window.py` — import + register_info calls + remove setStyleSheet overrides + add QAction/shortcut
3. EDIT: `ff_explorer/gui/settings_dialog.py` — import + register_info calls
4. EDIT: `ff_explorer/gui/treemap_view.py` — add accessible descriptions to path tooltip calls
5. EDIT: `ff_explorer/gui/theme.py` — add objectName-based QSS selectors for migrated styles

### Smoke test assertions to add
- `register_info` sets accessibleDescription == tooltip text
- `info_text(key)` raises KeyError for unknown key, returns correct text for known
- No widget in main_window has setToolTip called with a string literal (checked by register_info usage)
- Shift+F1 action exists in main_window actions
- The `_ff_info_key` property is set on registered widgets
- `_update_action_tooltip` still works (dynamic, sources from registry)

## Acceptance criterion
- ZERO `setToolTip("...literal...")` in main_window.py and settings_dialog.py
- Exactly one `QToolTip {` block in theme.py
- Per-widget setStyleSheet overrides at ~254,266,276,287,294,306,314,325,336 are gone
- `pytest tests/test_gui_smoke.py tests/test_theme.py -q` passes
