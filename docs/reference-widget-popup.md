# Reference: FF-Explorer widget-info pop-up solution

Canonical reference pattern for widget-info pop-ups. Source repo: `D:\Documentos\GitHub\FF-Explorer`
(Python / PySide6, branch `enhancement/ff-explorer-20260625`). The other three repos
(Unit-Converter, Map-Visualizer, GABI) replicate this pattern.

> Headline: FF-Explorer does **not** implement a bespoke pop-up widget. It uses Qt's built-in,
> framework-managed **`QToolTip` singleton** as the one centralized info surface, fed by a
> **module-level help-text registry**, and styled in **one** QSS block. That *is* the
> "one centralized component" the goal pattern wants — achieved by leaning on the framework
> singleton plus a registry, not by hand-rolling a popup window.

---

## 1. What the solution is

- **No custom class.** Grep across `ff_explorer/gui/` for `class *Popup`, `class *Tooltip`,
  `class *Info`, `eventFilter`, `QHelpEvent` returns nothing. The mechanism is entirely
  `QWidget.setToolTip(text)` calls + Qt's internal `QToolTip` machinery.
- **Files involved:**
  - `ff_explorer/gui/main_window.py` — owns every `setToolTip(...)` call and the help-text
    constants. Class `MainWindow(QMainWindow)`.
  - `ff_explorer/gui/theme.py` — the single `QToolTip { ... }` QSS styling block
    (`build_stylesheet`, lines ~436-442) plus `Theme.tooltip_bg` / `Theme.tooltip_text` fields
    (lines 118-122, light/dark values at 161-162 and 192-193).
  - `ff_explorer/gui/treemap_view.py` — secondary use (`setToolTip(path)` at lines 120, 143)
    showing full file path on treemap tiles.
  - `ff_explorer/gui/settings_dialog.py` — same pattern on dialog controls.
- **Single vs multiple:** there is exactly ONE info surface app-wide — Qt's `QToolTip` singleton.
  Qt guarantees only one tooltip is visible at a time, positioned at the cursor. Application code
  never instantiates a popup; it only registers text per widget.
- **History:** docstring at `main_window.py:38` — `Hover help — QToolTip on each control
  (replaces the Tkinter Toplevel overlay)`. The legacy Tkinter app DID hand-roll a popup
  (`Toplevel` overlay); the PySide6 port deleted that in favor of the framework singleton. The
  replicas should follow the port, not the legacy overlay.

## 2. How it is centralized

Three centralization points (this is the reusable core):

1. **Framework singleton (the surface).** `QToolTip` is an app-wide singleton owned by Qt. No
   manager object is authored. Instantiated-once-and-reused is free: Qt shows/hides/positions the
   single tooltip in response to hover events on any widget that has tooltip text.

2. **Help-text registry (the data).** Info strings live as module-level constants in
   `main_window.py` (mirroring the legacy `text_man*` / `aux_man`), lines 140-155:
   ```python
   _HELP_PATH    = "Root path in which\nfiles or folders are searched."
   _HELP_SEED    = "List of consecutive characters\ncontained in files/folders' name."
   _HELP_FOLDERS = "Folders search."
   _HELP_FILES   = "Files search."
   _HELP_ACTION  = "Actions to be applied to the resulting directory."
   _HELP_ACTION_DETAIL: dict[int, str] = {   # per-action supplementary text
       1: "\n   Save directory of files/folders found",
       2: "\n   Delete files/folders found",
       3: "\n   For files, compress all in one .zip in root\n   For folders, compress each one in root",
   }
   ```

3. **Single theming point (the look).** `theme.py build_stylesheet()` emits one QSS rule applied
   to the whole app via the application stylesheet:
   ```python
   QToolTip {{
       background-color: {t.tooltip_bg};
       color: {t.tooltip_text};
       border: 1px solid {t.border};
       padding: 2px 4px;
   }}
   ```
   So every tooltip in the app is themed from the active `Theme` (light/dark) in one place.

## 3. How widgets register / provide their info

- **Registration = one call per widget:** `widget.setToolTip(_HELP_X)`. Examples in
  `main_window.py`: `path_label.setToolTip(_HELP_PATH)` (257), `self._seed_edit.setToolTip(_HELP_SEED)`
  (297), `self._radio_folders.setToolTip(_HELP_FOLDERS)` (309). Many controls pass an inline literal
  instead of a named constant (e.g. lines 353, 374, 518, 527) — see Gaps.
- **Trigger = hover.** Pure Qt default: when the cursor rests over a widget that has tooltip text,
  Qt posts a tooltip event and shows the singleton near the cursor. No app code triggers it.
- **Dismiss = automatic.** Qt hides the tooltip on mouse-leave / after its timeout. No app code
  dismisses it.
- **One dynamic case (the registry can be data-driven):** the Action combobox recomputes its
  tooltip when the selection changes —
  ```python
  self._action_combo.currentIndexChanged.connect(self._update_action_tooltip)  # 329
  ...
  def _update_action_tooltip(self) -> None:                                     # 849
      label  = self._action_combo.currentText()
      code   = _ACTION_LABELS.get(label, -1)
      detail = _HELP_ACTION_DETAIL.get(code, "")
      self._action_combo.setToolTip(_HELP_ACTION + detail)
  ```
  Pattern note: tooltip text can be looked up from a registry keyed by widget state, not just a
  static constant.

## 4. PySide6 / Qt specifics

- `PySide6.QtWidgets.QWidget.setToolTip(str)` — registers per-widget info; inherited by every
  control (QLineEdit, QPushButton, QComboBox, QCheckBox, QRadioButton, QSpinBox, QDateEdit, QLabel).
- `QToolTip` — the singleton surface (styled, not instantiated). QSS selector `QToolTip { ... }`.
- The tooltip event flow (`QEvent.ToolTip` / `QHelpEvent`) is handled entirely inside Qt — FF
  overrides nothing (no `event()`/`eventFilter` for tooltips).
- Theming via the application stylesheet (`build_stylesheet(theme)` -> `app.setStyleSheet(...)`),
  with `Theme.tooltip_bg` / `Theme.tooltip_text` driving light/dark.
- Newlines in the text use plain `\n`; Qt also supports rich-text/HTML tooltips (unused here).
- Note: a couple of widgets carry inline per-widget `setStyleSheet(...)` (action combo 325, run
  button 336) which can locally clash with the central theme — avoid in replicas.

## 5. The reusable PATTERN (stack-agnostic)

> **One centralized info surface + a widget->info registry + a hover/focus trigger with automatic
> dismiss + a single theming point.**

Components:
1. **One info surface, instantiated once and reused** — prefer the platform's framework-managed
   tooltip singleton over a hand-rolled popup window.
2. **A registration mechanism** — each widget declares its info via a single call/property; the
   text lives in a centralized registry (named constants, a map, or a resource bundle), optionally
   data-driven by widget state.
3. **A trigger/dismiss policy** — show on hover (and, improved, on keyboard focus / a help button);
   auto-dismiss on leave/timeout. Handled by the framework where possible.
4. **A single theming/positioning point** — one style rule themed from the app's active theme.

Portable vs framework-specific:
- **Portable (keep identical across all repos):** the registry-of-texts idea, the one-call
  registration per widget, hover+auto-dismiss policy, single theming point, "never hand-roll N
  popups."
- **Framework-specific bindings:**
  - **PySide6 (Unit-Converter, Map-Visualizer):** identical — `widget.setToolTip(text)`, the
    `QToolTip` singleton, a `_HELP_*` registry, and a `QToolTip {}` QSS block in their theme module.
    Recommend a tiny helper `attach_info(widget, key)` that sets the tooltip AND the accessible
    description from one registry.
  - **Java/Swing (GABI):** direct analogue — `JComponent.setToolTipText(text)` plus the singleton
    `javax.swing.ToolTipManager.sharedInstance()` (controls delay/dismiss globally). Centralize
    texts in a `ResourceBundle`/`Map`, apply look via `UIManager` `ToolTip.background` /
    `ToolTip.foreground` keys (the single theming point). If GABI's UI is Spring/web rather than
    Swing, the analogue is a shared tooltip component / `title`/`aria-describedby` attribute fed by
    one message catalog.

## 6. Gaps / quality notes (mandate the improved version in replicas)

1. **Inconsistent registry.** Only the first five texts are named constants; many controls inline
   string literals in `setToolTip(...)` (e.g. 353, 374, 387, 400, 518, 527). Replicas should put
   ALL info text in ONE registry (dict/bundle) keyed by a stable widget id — no inline literals.
2. **No accessibility.** Tooltips are hover-only. Nothing calls `setWhatsThis()` /
   `setAccessibleDescription()`, so the info is invisible to keyboard-only and screen-reader users.
   Mandate: a single helper that sets tooltip + accessible description (+ optional WhatsThis), and a
   keyboard/focus trigger or a help (`?`) affordance.
3. **No single-instance/coverage enforcement.** Nothing guarantees every interactive widget has
   info. Mandate a `register_info(widget, key)` helper used uniformly, optionally asserted in tests.
4. **Legacy text formatting.** Manual `\n` line breaks are a Tkinter carryover. Prefer
   rich-text/word-wrapped tooltips and let the surface wrap.
5. **Local style overrides.** Inline `setStyleSheet` on some widgets can fight the central
   QToolTip/theme styling — keep all styling in the one theme module.
6. **Positioning/timing left at defaults.** Acceptable, but the improved spec can centralize
   dismiss/delay (trivial in Swing via `ToolTipManager`; tunable in Qt) so behavior is consistent.

---

### File:line index
- `ff_explorer/gui/main_window.py:38` — design note (replaces Tkinter Toplevel overlay)
- `ff_explorer/gui/main_window.py:140-155` — help-text registry constants
- `ff_explorer/gui/main_window.py:257-640` — per-widget `setToolTip(...)` registration calls
- `ff_explorer/gui/main_window.py:329-330, 849-854` — dynamic, state-driven tooltip
- `ff_explorer/gui/theme.py:118-122, 161-162, 192-193` — `tooltip_bg`/`tooltip_text` theme fields
- `ff_explorer/gui/theme.py:436-442` — single `QToolTip {}` QSS styling block
- `ff_explorer/gui/treemap_view.py:120, 143` — secondary tooltip usage (full path on tiles)
