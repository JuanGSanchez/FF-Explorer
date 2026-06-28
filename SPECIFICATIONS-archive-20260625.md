> **ARCHIVED — delivered list (2026-06-25).** This is the historical product specification set
> (SPEC-01…SPEC-22). Every spec here was implemented and committed on
> `enhancement/ff-explorer-20260625` (quality gate GREEN, 96.95% coverage). It is retained for
> traceability only and is **not** the active backlog. The active work list lives in the current
> `SPECIFICATIONS.md` (post-review remediation). Do not implement against this file.

# FF-Explorer — Product Specifications

Stack: Python 3 (≤3.13) / PySide6. A file & folder explorer GUI over a UI-independent core.

## How to read this file
This is a prioritized product capability + robustness backlog. It is the **input to the repo's own
SDD pipeline** (`specify → clarify → plan → tasks → implement → analyze → checklist`): each spec
below is written to be picked up, planned, and implemented as a discrete unit. Every spec is concrete
and testable.

### Standing invariants (apply to every spec)
- **Headless-core invariant.** The core (traverse / filter / query / save / remove / compress /
  metadata) MUST remain free of any GUI import (`PySide6`, `tkinter`). The GUI and the access layer
  are clients of the same core. No spec may push UI concerns into the core, and the core must be
  callable from a headless context with no display.
- **Query/action separation.** A pure *query* (traverse+filter → returns the matched list) MUST be
  separable from *actions* (save / remove / compress). Listing must never have side effects.
- **No regression of existing behavior.** The four legacy capabilities (folder/file search by name
  substring; Save / Remove / Compress) must keep working through the GUI.
- **Cross-platform.** New code uses `pathlib` / `os.path`; no hard-coded `'\\'` separators.

### Priority key
- **P1** — foundational / safety-critical / unblocks other work. Do first.
- **P2** — high-value capability or robustness, depends on P1 groundwork.
- **P3** — enhancement / polish / breadth.

### Theme & priority index
| Theme | Specs |
|-------|-------|
| Core / Foundation | SPEC-01 |
| UX / Popup (centralized widget-info) | SPEC-02, SPEC-03, SPEC-04 |
| Access Layer (REST + MCP) | SPEC-05, SPEC-06, SPEC-07 |
| Testing | SPEC-08, SPEC-09 |
| Packaging | SPEC-10 |
| Robustness | SPEC-11, SPEC-12, SPEC-13, SPEC-14, SPEC-15 |
| Features | SPEC-16, SPEC-17, SPEC-18, SPEC-19, SPEC-20, SPEC-21, SPEC-22 |

---

## Core / Foundation

### SPEC-01 Pure-query / action split in the headless core
**Priority:** P1
**Motivation:** The legacy core fused traversal, filtering, and destructive actions in one function
that returned only an int token and never the matched list. A headless caller cannot "list without
acting," tests cannot assert on results, and destructive defaults are unsafe. Every other spec
(access layer, tests, features, safety) depends on this split.
**Scope:**
- In: a stable core API module exposing `list_entries(path, kind, name_seed, *, options)` (pure
  query, no side effects, returns a list of result records), plus discrete action functions
  `save_listing(...)`, `remove_entries(...)`, `compress_entries(...)`, and a `entry_metadata(path)`
  accessor. Each result record carries at minimum: absolute path, name, kind (file/folder).
- Out: GUI wiring beyond pointing the existing Run path at the new functions; new search predicates
  (SPEC-16) and metadata surfacing (SPEC-19) build on this but are specified separately.
**Acceptance criteria:**
- `list_entries` returns a list (possibly empty) and performs zero filesystem mutations (assert no
  file created/removed/zipped, e.g. via a tmp tree snapshot before/after).
- Action functions accept the query result (or equivalent args) and are independently callable.
- The core module imports none of `PySide6`/`tkinter` (assert by static import scan in a test).
- `kind` accepts both folders and files; empty `name_seed` is handled per SPEC-13 (no longer a
  silent "match everything" foot-gun).
- Existing GUI Save/Remove/Compress still produce equivalent outputs for a given input tree.
**Notes/Dependencies:** Foundation for SPEC-05/06/08/13/16/19. Fixes R-6.

---

## UX / Popup — centralized widget-info component

### SPEC-02 Single widget-info registry (eliminate inline tooltip literals)
**Priority:** P1
**Motivation:** Today only the first ~five help texts are named constants; many controls inline
string literals directly in `setToolTip(...)` (`main_window.py` lines ~353, 374, 387, 400, 518, 527).
Info is scattered, untranslatable, and inconsistent. The reference pattern mandates ONE registry.
**Scope:**
- In: a single module-level help-text registry (dict keyed by a stable widget id/key) holding ALL
  user-facing widget info text — including the action-detail map. All `setToolTip` callers read from
  the registry; zero inline literals remain in GUI modules.
- Out: the rendering surface itself (Qt's `QToolTip` singleton stays the surface); translation
  backend (SPEC-21 covers i18n, but the registry must be i18n-ready — see criteria).
**Acceptance criteria:**
- A test greps the GUI package and asserts no `setToolTip("...literal...")` / `setWhatsThis("...")`
  with a string literal — every call references a registry key.
- The registry is the single source for help text; each entry keyed by a stable id.
- Dynamic/state-driven entries (e.g. the Action combobox supplementary text) are looked up from the
  registry by widget state, not hard-coded at the call site.
- Registry values are accessed through one function so an i18n layer can wrap it later without
  touching call sites.
**Notes/Dependencies:** Implements reference gap #1. Precursor to SPEC-03/04/21.

### SPEC-03 `register_info(widget, key)` helper with accessibility + coverage enforcement
**Priority:** P1
**Motivation:** Tooltips are hover-only — invisible to keyboard-only and screen-reader users
(reference gap #2). Nothing guarantees every interactive widget actually has info (gap #3). One
helper must set tooltip + accessible description (+ optional WhatsThis) and be the only sanctioned way
to attach info.
**Scope:**
- In: a single helper `register_info(widget, key)` that, from one registry lookup, sets the tooltip,
  `setAccessibleDescription(...)`, and (where useful) `setWhatsThis(...)`. A coverage check that every
  interactive widget (QLineEdit, QPushButton, QComboBox, QCheckBox, QRadioButton, QSpinBox, QLabel
  acting as a control, etc.) has registered info.
- Out: visual theming (SPEC-04); the registry contents themselves (SPEC-02).
**Acceptance criteria:**
- All info attachment in the GUI goes through `register_info`; direct `setToolTip` calls in GUI
  modules are removed (assertable by grep test).
- For any registered widget, `accessibleDescription()` is non-empty and equals the help text source.
- A coverage test enumerates interactive widgets in the main window (and dialogs) and asserts each
  has a non-empty accessible description / registered key; the test FAILS if a new interactive widget
  is added without info.
- Keyboard-only path: focusing a control and triggering help (see SPEC-04) surfaces its info without
  a mouse hover.
**Notes/Dependencies:** Implements reference gaps #2/#3. Depends on SPEC-02. Enables SPEC-22
accessibility audit.

### SPEC-04 Single dismiss/delay + theming policy; remove per-widget style overrides; keyboard help affordance
**Priority:** P2
**Motivation:** Positioning/timing are left at defaults and a couple of widgets carry inline
`setStyleSheet(...)` (action combo ~325, run button ~336) that can fight the central QToolTip theme
(reference gaps #4/#5/#6). Info should be consistently styled and consistently dismissed, and
reachable without hover.
**Scope:**
- In: one QSS `QToolTip {}` block driven by the active `Theme` (light/dark) as the only tooltip style;
  a single configured show-delay / dismiss policy; a keyboard/focus trigger or a help (`?`) affordance
  that opens WhatsThis mode so info is reachable without hover; removal of per-widget `setStyleSheet`
  overrides that conflict with the theme.
- Out: adding new themes (SPEC-20); registry/accessibility (SPEC-02/03).
**Acceptance criteria:**
- Exactly one `QToolTip { ... }` rule exists in the theme module; switching theme changes tooltip
  colors with no other tooltip-style source (assertable by grepping for `QToolTip` style blocks =1).
- No GUI widget calls `setStyleSheet` for purposes the central theme already covers (grep test on the
  flagged widgets passes — overrides removed or justified).
- A documented, single show-delay/dismiss configuration is applied app-wide.
- Activating the help affordance (e.g. Shift+F1 / `?` button) enters WhatsThis mode and shows the
  focused widget's info via keyboard alone.
- Prefer word-wrapped/rich-text tooltips over manual `\n` line breaks (legacy carryover removed).
**Notes/Dependencies:** Depends on SPEC-02/03. Coordinates with SPEC-20 theming.

---

## Access Layer (REST + MCP over the headless core)

### SPEC-05 Headless service facade over the core
**Priority:** P1
**Motivation:** The REST and MCP surfaces should wrap one stable service facade, not duplicate logic
or touch the GUI. The core's verified zero-UI-import property makes a direct wrap possible once
SPEC-01 lands.
**Scope:**
- In: a service/facade module exposing the operations as plain callables with typed inputs/outputs:
  `list_entries`, `save_listing`, `remove_entries` (guarded), `compress_entries`, `entry_metadata`.
  Centralized input validation/path-safety (SPEC-11/12) applied here so both REST and MCP inherit it.
- Out: transport/protocol specifics (SPEC-06 REST, SPEC-07 MCP); GUI.
**Acceptance criteria:**
- The facade imports no GUI module (assertable static-import test).
- Each operation returns structured data (dataclass/dict), not print output; errors raise typed
  exceptions carrying a machine-readable code + message.
- Destructive operations require an explicit confirm/dry-run flag (delegates to SPEC-13 policy).
- Facade is unit-tested against tmp trees independent of any server.
**Notes/Dependencies:** Depends on SPEC-01. Foundation for SPEC-06/07. Implements R5 surface.

### SPEC-06 REST API exposing file/folder operations
**Priority:** P2
**Motivation:** R5 calls for a REST access layer over the headless core so external tools/scripts can
drive FF-Explorer operations without the GUI.
**Scope:**
- In: an HTTP service (e.g. FastAPI/uvicorn or stdlib-acceptable equivalent compatible with ≤3.13)
  exposing endpoints for list (query), save, remove, compress, metadata. JSON request/response.
  Read endpoints (list/metadata) are side-effect-free; mutating endpoints require explicit confirm.
- Out: authentication beyond a documented local-only binding default; UI; business logic (lives in
  the facade SPEC-05).
**Acceptance criteria:**
- `GET`/list-style endpoint returns the matched entries for `(path, kind, name_seed, options)` and
  performs zero mutations (tmp-tree snapshot unchanged).
- Mutating endpoints reject requests lacking `confirm=true` (or with `dry_run=true` they return the
  would-be effect without mutating).
- Path-safety validation (SPEC-12) rejects traversal/out-of-root and non-existent roots with a 4xx +
  machine-readable error code; internal failures return 5xx without leaking stack traces.
- Endpoints documented (OpenAPI/schema) and covered by API tests using a tmp directory.
- Server binds to localhost by default; binding is configurable.
**Notes/Dependencies:** Depends on SPEC-05. New runtime dep(s) — record in SPEC-10 manifest.
**RESEARCH REQUEST:** confirm a REST framework version compatible with the Python ≤3.13 ceiling and
its current API (orchestrator → The Researcher).

### SPEC-07 MCP server exposing the operations as tools
**Priority:** P2
**Motivation:** R5 calls for an MCP access layer so an agent host can invoke file/folder operations
as MCP tools over the same core.
**Scope:**
- In: an MCP server (FastMCP, pinned to a ≤3.13-compatible build) registering one tool per operation
  (list, save, remove, compress, metadata) backed by the SPEC-05 facade. Tool schemas declare typed
  args; destructive tools advertise + enforce confirm/dry-run.
- Out: REST specifics (SPEC-06); GUI; non-FF tooling.
**Acceptance criteria:**
- Each tool is discoverable with a name, description, and typed input schema.
- The list/metadata tools are side-effect-free; remove/compress tools refuse to mutate without an
  explicit confirm argument and support a dry-run mode that reports the planned effect.
- Tool errors return structured error content (code + message), never an uncaught traceback.
- Tools are exercised by tests that import the server in-process against a tmp tree.
**Notes/Dependencies:** Depends on SPEC-05. Shares validation with SPEC-06. FastMCP has no 3.14 build
— pin ≤3.13.
**RESEARCH REQUEST:** confirm current FastMCP version + tool-registration API for the pinned Python
(orchestrator → The Researcher).

---

## Testing

### SPEC-08 Core + facade pytest suite meeting the coverage gate
**Priority:** P1
**Motivation:** The repo has zero tests today. The SDD pipeline and the campaign coverage gate require
a pytest suite; the highest-value, most deterministic targets are the pure query/filter path and the
action paths against tmp directories.
**Scope:**
- In: a `tests/` suite with pytest covering `list_entries` (folders & files, substring matching, edge
  seeds), `save_listing` (output file content/format), `remove_entries` (tmp-tree deletion + guard
  behavior), `compress_entries` (zip created at the correct path — verifies R-2 fix), and
  `entry_metadata`. Fixtures build temporary trees; no test touches the real filesystem outside tmp.
- Out: GUI rendering tests beyond a smoke test (SPEC-09); network server tests (covered in
  SPEC-06/07 but may live alongside).
**Acceptance criteria:**
- Suite runs green via `pytest` with no external services and no network.
- Coverage meets the campaign coverage gate on the core + facade modules (assert via coverage report).
- A regression test pins the folders-mode compress path bug (R-2): zip lands at the intended location
  with a correct separator.
- A test asserts `list_entries` performs no mutation (snapshot before/after).
- A static-import test asserts core/facade modules import no GUI toolkit.
**Notes/Dependencies:** Depends on SPEC-01 (and benefits from SPEC-05). Drives R3 testing requirement.

### SPEC-09 GUI smoke + accessibility-coverage tests
**Priority:** P2
**Motivation:** The popup/accessibility specs (SPEC-02/03) and basic window construction need
automated guards so future changes don't silently drop info coverage or break startup.
**Scope:**
- In: a headless Qt test (offscreen platform) that constructs the main window, asserts it builds
  without error, and runs the SPEC-03 info-coverage check (every interactive widget has a registry
  key + accessible description). A grep-style test forbidding inline tooltip literals.
- Out: full end-to-end interaction/golden-image testing.
**Acceptance criteria:**
- Window constructs under the offscreen Qt platform in CI with no display.
- Coverage test fails if any interactive widget lacks registered info.
- Literal-tooltip lint test fails on any inline `setToolTip`/`setWhatsThis` string literal.
**Notes/Dependencies:** Depends on SPEC-02/03. Uses `pytest-qt` or `QT_QPA_PLATFORM=offscreen`.

---

## Packaging

### SPEC-10 Project manifest + cross-platform PyInstaller executable
**Priority:** P2
**Motivation:** No `pyproject.toml`, no entry point, no version single-sourcing, no build config exist
today (version is a literal string in the GUI module). R3/packaging requires a real manifest and a
distributable executable.
**Scope:**
- In: a `pyproject.toml` with project metadata, a single-sourced version, pinned Python ≤3.13, declared
  runtime deps (PySide6 + REST/MCP deps from SPEC-06/07), a console/GUI entry point, and a PyInstaller
  `.spec` producing a packaged executable (bundling `Logo FFE.png` and other assets). Build instructions
  documented.
- Out: code-signing / OS store distribution; auto-update.
**Acceptance criteria:**
- `pip install -e .` (or build backend equivalent) installs the app and exposes the declared entry
  point that launches the GUI.
- Version is defined once and read by both the app and packaging metadata (no duplicated literal).
- A PyInstaller build produces a runnable bundle that launches the GUI with the window icon present.
- Build config targets the supported OS set; no Windows-only assumptions in the build (path handling
  per the cross-platform invariant).
**Notes/Dependencies:** Depends on dep set from SPEC-06/07. Addresses R-7 runtime re-pin (≤3.13).
**RESEARCH REQUEST:** confirm current PyInstaller version + PySide6 packaging guidance for ≤3.13
(orchestrator → The Researcher).

---

## Robustness

### SPEC-11 Structured error handling + logging (replace print/messagebox swallowing)
**Priority:** P1
**Motivation:** The legacy core swallows all save errors with a bare `except:` writing a blank line,
and feedback goes only to `print()` (invisible under `.pyw`) / `messagebox` (R-5). Failures are
largely silent.
**Scope:**
- In: typed exceptions from the core/facade with machine-readable codes; structured logging
  (stdlib `logging`) with a configurable level and a log destination; the GUI surfaces failures via a
  user-visible message instead of a swallowed `print`. No bare `except:` blocks.
- Out: external log shipping / telemetry.
**Acceptance criteria:**
- No bare `except:` remains in core/facade (assertable by lint/grep test).
- A simulated failure (e.g. permission error on remove) raises a typed exception with a code and is
  logged at error level; the GUI shows a user-visible error; nothing is silently swallowed.
- `save_listing` never writes a blank line on failure; on error it raises/logs and does not produce a
  misleading partial file.
- Log level and destination are configurable (env or settings).
**Notes/Dependencies:** Depends on SPEC-01. Shared by SPEC-05/06/07.

### SPEC-12 Input validation + path-safety
**Priority:** P1
**Motivation:** A mistaken root path or empty seed can wipe large trees (R-1/R-4). The access layer
especially must reject unsafe paths.
**Scope:**
- In: validation that the root path exists, is a directory, and is readable; path normalization via
  `pathlib`; rejection of traversal/escape attempts in access-layer inputs; explicit handling of empty
  / whitespace seeds (see SPEC-13). Centralized in the facade so GUI + REST + MCP inherit it.
- Out: per-feature semantics (covered by feature specs); auth (out of scope this backlog).
**Acceptance criteria:**
- Non-existent / non-directory / unreadable roots are rejected with a typed error before any
  traversal.
- Access-layer requests with path traversal (`..`, absolute escapes beyond an allowed root) are
  rejected with a machine-readable error.
- All path joins use `pathlib`/`os.path`; a test asserts no hard-coded `'\\'` literal in core/facade
  path construction (fixes R-3).
- Validation is applied uniformly across GUI, REST, and MCP entry points (shared code path).
**Notes/Dependencies:** Depends on SPEC-01/05. Mitigates R-1/R-3/R-4.

### SPEC-13 Destructive-action safety: dry-run, confirmation, recycle-bin option
**Priority:** P1
**Motivation:** Remove and Compress permanently delete with no confirmation or dry-run; an empty seed
matches everything; a mid-delete failure leaves partial state (R-1). This is the single most dangerous
gap.
**Scope:**
- In: a mandatory confirmation step for destructive GUI actions; a `dry_run` mode (returns what WOULD
  be affected without mutating) across GUI/REST/MCP; an option to send removed items to the OS
  recycle bin/trash instead of permanent deletion; explicit guard so an empty/whitespace seed does
  NOT silently select the entire tree (require an explicit "match all" opt-in). Per-item error
  handling so a mid-operation failure reports partial results rather than aborting opaquely.
- Out: undo history beyond recycle-bin; versioned backups.
**Acceptance criteria:**
- A remove/compress invocation without confirmation does not mutate the filesystem (GUI + facade).
- `dry_run=true` returns the exact set of items that would be affected and mutates nothing
  (tmp-tree snapshot unchanged).
- Empty/whitespace seed without an explicit "match all" flag is rejected or returns empty — it must
  NOT delete/compress everything.
- Recycle-bin option, when enabled, moves items to trash (verified via the chosen cross-platform
  trash library) rather than `os.remove`/`rmtree`.
- A simulated mid-delete failure yields a structured partial-result report, not a silent partial
  state.
**Notes/Dependencies:** Depends on SPEC-01/11/12. Mitigates R-1/R-4. New dep (trash library) →
record in SPEC-10. **RESEARCH REQUEST:** confirm a maintained cross-platform send-to-trash library
compatible with ≤3.13.

### SPEC-14 Large-directory performance + non-blocking responsiveness
**Priority:** P2
**Motivation:** Long traversals/actions on big trees would freeze the GUI (no concurrency today).
The app must stay responsive and scale.
**Scope:**
- In: run query/actions off the UI thread (QThread / worker + signals) so the window never blocks;
  progress reporting and a cancel affordance for long operations; streaming/iterator-based traversal
  in the core so memory stays bounded on large trees.
- Out: multi-process parallel scanning; distributed work.
**Acceptance criteria:**
- During a long scan/action the GUI remains responsive (event loop not blocked) and shows progress.
- A long operation can be cancelled cleanly, leaving a consistent state.
- Core traversal can yield results incrementally (generator) so a very large tree does not require
  materializing all results before returning — assertable via a memory/iteration test on a synthetic
  large tree.
- No UI calls happen from the worker thread except via signals.
**Notes/Dependencies:** Depends on SPEC-01. GUI threading is Qt-side; the core stays headless and just
exposes an iterable.

### SPEC-15 Graceful degradation on partial/permission failures
**Priority:** P3
**Motivation:** Real filesystems have unreadable folders, locked files, and broken symlinks; the app
should skip-and-report rather than crash or silently stop.
**Scope:**
- In: per-entry try/skip during traversal with a collected list of skipped paths + reasons surfaced to
  the user/caller; tolerant handling of permission errors, broken symlinks, and long paths.
- Out: auto-elevation / privilege escalation.
**Acceptance criteria:**
- A traversal over a tree containing an unreadable subdir completes, returns the readable results, and
  reports the skipped path with a reason (no crash).
- Broken symlinks do not abort traversal.
- The skip report is available to GUI, REST, and MCP callers.
**Notes/Dependencies:** Depends on SPEC-01/11.

---

## Features (breadth — grounded in the headless core)

### SPEC-16 Advanced search & filter (glob/regex, case-insensitive, type/extension predicates)
**Priority:** P2
**Motivation:** Current search is a case-sensitive substring `in` test only — no glob, regex,
extension, or case options (R-4). This is the core value of an explorer.
**Scope:**
- In: an extended query options object for `list_entries` supporting: substring (default), glob, and
  regex match modes; case-insensitive toggle; extension filter; folders/files/both selector. Invalid
  regex/glob is reported as a typed validation error.
- Out: content (in-file) search (could be a later spec); size/date predicates (SPEC-17).
**Acceptance criteria:**
- Each match mode returns the correct set on a fixture tree (substring, glob `*.txt`, regex).
- Case-insensitive toggle changes results as expected.
- Extension filter restricts results to the given extensions.
- Invalid regex/glob yields a typed validation error, not a crash.
- All modes are exposed through GUI, REST, and MCP (shared options object).
**Notes/Dependencies:** Depends on SPEC-01. Surfaces through SPEC-05/06/07. Mitigates R-4.

### SPEC-17 Size / date / attribute filters
**Priority:** P3
**Motivation:** Explorers filter by size and modification time; the core surfaces none of this today.
**Scope:**
- In: optional predicates on the query: min/max size, modified-before/after, hidden/system attribute
  inclusion. Backed by metadata from SPEC-19.
- Out: content search; tag-based filtering.
**Acceptance criteria:**
- Size and mtime predicates return the correct subset on a fixture tree with controlled sizes/times.
- Predicates compose with SPEC-16 match modes.
- Exposed through GUI + access layer.
**Notes/Dependencies:** Depends on SPEC-16/19.

### SPEC-18 Bulk operations (multi-select, batch save/remove/compress, copy/move)
**Priority:** P3
**Motivation:** Users act on many items at once; the legacy flow applies one action to the whole match
set with no selection granularity, and offers no copy/move.
**Scope:**
- In: result-list multi-selection in the GUI; apply Save/Remove/Compress to the selected subset; add
  Copy and Move actions (to a chosen destination) at the core + facade level.
- Out: drag-and-drop reordering; cloud destinations.
**Acceptance criteria:**
- A user can select a subset of results and apply an action only to that subset.
- Copy and Move are implemented in the core (headless, tested against tmp trees) and exposed via the
  facade.
- All bulk mutations honor the SPEC-13 confirm/dry-run policy.
**Notes/Dependencies:** Depends on SPEC-01/13.

### SPEC-19 File/folder metadata & properties view
**Priority:** P3
**Motivation:** The core surfaces no size/mtime/type/permission metadata (R-6/understanding doc).
Users expect to see properties.
**Scope:**
- In: `entry_metadata(path)` returning size, modified/created times, type, and permission summary; a
  GUI properties panel/dialog showing it for a selected entry; metadata columns in the result list.
- Out: extended OS-specific attributes (ACLs, alternate streams).
**Acceptance criteria:**
- `entry_metadata` returns correct size/mtime/type for fixture files/folders.
- The GUI shows metadata for a selected result.
- Metadata is exposed via the access layer (feeds SPEC-17 filters).
**Notes/Dependencies:** Depends on SPEC-01. Feeds SPEC-17.

### SPEC-20 Theming (light/dark) + persisted preferences
**Priority:** P3
**Motivation:** The theme module already drives tooltip colors light/dark; expose a user-facing theme
switch and persist settings (the app has no persistence today).
**Scope:**
- In: a user-selectable light/dark (and optional system) theme applied app-wide through the existing
  single-theming point; persisted user preferences (theme, last root, default options) in a settings
  file under the OS config dir.
- Out: arbitrary custom user themes/CSS editing.
**Acceptance criteria:**
- Switching theme restyles the whole app, tooltips included, via the single theme stylesheet
  (consistent with SPEC-04).
- Preferences persist across restarts (written to / read from an OS-appropriate config path).
- Corrupt/missing settings file degrades gracefully to defaults.
**Notes/Dependencies:** Coordinates with SPEC-04. Introduces app persistence.

### SPEC-21 Internationalization (i18n) readiness
**Priority:** P3
**Motivation:** All UI/help text is hard-coded English with manual `\n` breaks. The centralized
registry (SPEC-02) makes i18n tractable; the app should be translation-ready.
**Scope:**
- In: route all user-facing strings (including the help registry) through a translation mechanism
  (Qt `tr()` / catalog or a message bundle); extract a base catalog; document how to add a locale.
- Out: shipping multiple completed translations; RTL layout work.
**Acceptance criteria:**
- User-facing strings are wrapped for translation; a base catalog can be extracted by the tooling.
- The help registry resolves through the translation layer (no string literals at call sites).
- Switching to a stub/pseudo-locale changes displayed strings, proving the path works.
**Notes/Dependencies:** Depends on SPEC-02. Complements SPEC-22.

### SPEC-22 Accessibility & keyboard-driven navigation audit
**Priority:** P3
**Motivation:** Beyond tooltips, the app should be operable entirely by keyboard and friendly to
screen readers (reference gap #2 generalizes to the whole UI).
**Scope:**
- In: a logical tab order across all controls; mnemonics/accelerators for primary actions; accessible
  names/roles on interactive widgets (extends SPEC-03); keyboard shortcuts for Run and the main
  actions; visible focus indication.
- Out: full WCAG certification; high-contrast theme authoring (could extend SPEC-20).
**Acceptance criteria:**
- Every primary action is reachable and triggerable by keyboard alone (tab + accelerator/shortcut).
- Interactive widgets expose a non-empty accessible name and role (assertable via Qt accessibility
  introspection in a test).
- Tab order is logical (documented expected order verified in the smoke test).
**Notes/Dependencies:** Depends on SPEC-03. Complements SPEC-21.

---

## Embedded requests for the orchestrator
- **RESEARCH REQUEST (SPEC-06):** current REST framework version/API compatible with Python ≤3.13.
- **RESEARCH REQUEST (SPEC-07):** current FastMCP version + tool-registration API for ≤3.13.
- **RESEARCH REQUEST (SPEC-10):** current PyInstaller + PySide6 packaging guidance for ≤3.13.
- **RESEARCH REQUEST (SPEC-13):** maintained cross-platform send-to-trash library for ≤3.13.

These route through The Researcher before the dependent specs enter `plan`/`implement`.
