# FF-Explorer — Post-review remediation specifications (2026-06-28)

Stack: Python 3 (≤3.13) / PySide6. A file & folder explorer GUI over a UI-independent core.

## Purpose
This is the **active** specification list, produced by a critical pre-merge review of branch
`enhancement/ff-explorer-20260625` (PR #2 → `main`). The historical, already-delivered product
backlog (SPEC-01…SPEC-22) has been archived to `SPECIFICATIONS-archive-20260625.md`; do not implement
against that file. Every item below is a concrete, acceptance-testable remediation derived from a
finding of that review.

## Review baseline (verified, not claimed)
- Quality gate **GREEN**: `986 passed, 3 skipped`, total coverage **96.95%** (≥90% gate) at review
  time (commit `95219f5`).
- All 22 archived specs are implemented and tested **except** the i18n coverage gap below (SPEC-R03):
  the translation *seam* (`tr()` + the `widget_info` registry routed through it) works and is
  pseudo-locale-tested, but a material fraction of user-facing strings still bypass `tr()`.
- The centralized `widget_info` registry **is** the sole help-info surface. `treemap_view`'s
  `setToolTip(path)` shows *data* (the file's path), not help text, and is explicitly whitelisted by
  the SPEC-09 literal-tooltip lint — **no ad-hoc help popup remains** (no remediation needed; recorded
  as SPEC-R04 “no action”).

### Standing invariants (unchanged — apply to every spec)
- **Headless-core invariant**, **query/action separation**, **no regression**, **cross-platform** —
  exactly as defined in the archived list. None of the remediations below touch the headless core or
  the access layer; they are GUI/text/repo-hygiene only.

### Priority key
- **P1** — merge-blocking hygiene / correctness. Do first.
- **P2** — completes a partially-met acceptance criterion of a delivered spec.
- **P3** — optional polish (none required by this review).

---

## SPEC-R01 — Remove stray subagent scratch files from the tree (P1)
**Finding:** Two subagent in-progress checkpoint notes were committed into `docs/`:
`docs/checkpoint-core-dev-SPEC11-20260626-220157.md` (header: *“Status: IN PROGRESS (implementation
not yet written)”*) and `docs/checkpoint-gui-dev-SPEC02-03-04-20260627T000151.md` (header:
*“Status: IN-PROGRESS”*). They are tracked, unreferenced by any code or doc, and are exactly the
scratch artifacts that must not ship in a merge to `main`.
**Scope — In:** `git rm` both files. **Out:** the legitimate `docs/` docs (AUDIT, BACKLOG,
agent-operating-doc, reference-widget-popup, research-pyside6-best-practices) stay.
**Acceptance criteria:**
- `git ls-files docs/ | grep -i checkpoint` returns nothing.
- `git ls-files | grep -iE 'checkpoint|scratch|subagent|report-2026|WIP'` returns nothing.
- Working tree clean after commit; gate still GREEN.

## SPEC-R02 — Remove dead no-op line in `i18n.py` (P1)
**Finding:** `ff_explorer/gui/i18n.py` (`remove_pseudo_locale`) contains
`_installed.discard(translator) if hasattr(_installed, "discard") else None`. `_installed` is a
`list`, which never has a `discard` attribute, so this expression is always a no-op; the actual
removal is performed by the following two lines (`if translator in _installed: _installed.remove(...)`).
**Scope — In:** delete the dead line; keep the correct `list.remove` removal. **Out:** any behavior
change — removal semantics must be identical.
**Acceptance criteria:**
- The dead `hasattr(_installed, "discard")` line no longer appears in `i18n.py`.
- `remove_pseudo_locale` still removes the translator and clears it from `_installed`
  (existing `tests/test_i18n.py::TestPseudoLocaleRemoval` stays green).
- No new lint/coverage regression.

## SPEC-R03 — Complete SPEC-21 i18n string coverage (P2)
**Finding:** The archived SPEC-21 acceptance criterion *“user-facing strings are wrapped for
translation … switching to a pseudo-locale changes displayed strings”* is only **partially** met. The
seam and the help registry are routed through `tr()`, but the following user-facing strings still pass
raw literals to Qt and therefore never change under a translator:
- `main_window.py` placeholders: `setPlaceholderText` at the extensions, content-query, ignore-globs,
  and batch-rename find/replace fields (5 sites).
- `main_window.py` dialog window titles built with f-strings: **Results** (`Results — N …(s) found`),
  **Properties** (`Properties — <path>`), **Skipped paths** (`Skipped paths (N)`).
- `main_window.py` user-facing message/label text not wrapped: the results summary label
  (`N …(s) found.` + selection hint), the About-box body labels (`Author:/Version:/License:`), the
  `Details:` prefix on the content-search warning, the `Files will be moved to .ffe-versions/ …`
  versioning note, the five `No <label> was found — nothing was …` status messages
  (save/remove/compress/copy/move), the three result toasts (`N …(s) removed/copied to …/moved to …`),
  the scanning-progress status (`Scanning for …(s)…`), and the preview `… and N more …(s).` suffix.
- `settings_dialog.py`: the `Colour warnings:` validation header.
- `treemap_view.py`: **entirely un-internationalized** — the window title `Disk Usage — Largest
  Files`, the five header labels (`Largest files (by size, descending)`, `Size (relative)`,
  `File name`, `Size`) and the `No entries to display.` status string.
**Scope — In:** wrap every string above through the existing `tr()` seam, using the established
`tr("… {token} …").replace("{token}", value)` pattern already used elsewhere in `main_window.py` for
interpolated strings (do **not** introduce a new formatting convention, and preserve mnemonics/`&`
and existing wording verbatim). Add a lightweight lint test (parallel to the existing SPEC-09
literal-tooltip lint) asserting no bare-literal `setPlaceholderText("…")` / `setWindowTitle("…")`
remains in the GUI package, plus an offscreen pseudo-locale assertion that the treemap window title
and a representative dialog title render wrapped (`⟦…⟧`) when the pseudo-locale is installed.
**Out:** translating any catalog (no `.qm` shipped); RTL/layout work; non-user-facing strings
(stylesheet text, glyph separators like `"–"`, format specifiers, debug/log strings).
**Acceptance criteria:**
- Every string enumerated in the finding is wrapped through `tr()`; displayed wording is byte-identical
  to today when no translator is active (zero English-UI regression).
- With the pseudo-locale installed, the treemap window title and the Results/Properties/Skipped dialog
  titles render as `⟦…⟧` (proven by an offscreen test).
- A new lint test fails on any future bare-literal `setPlaceholderText`/`setWindowTitle` in
  `ff_explorer/gui/`.
- Full gate GREEN; coverage stays ≥90% (no drop below the review baseline beyond test additions).

## SPEC-R04 — Sole-info-surface confirmation (P3 — NO ACTION REQUIRED)
**Finding:** Review confirmed the centralized `widget_info` registry + `register_info(...)` is the
only help-info surface in the GUI. The only other `setToolTip` callers (`treemap_view.py`) attach the
*path string itself* as a data tooltip on a tile/label — not help text — and are already whitelisted by
the SPEC-09 lint. No scattered ad-hoc tooltips/popups remain.
**Resolution:** No code change. Recorded explicitly so the review trail shows this area was checked and
found clean, rather than silently omitted.
**Acceptance criteria:** none (informational). The existing SPEC-09 literal-tooltip lint continues to
guard against regressions.

---

## Out of scope for this remediation pass
- No changes to the headless core, the REST/MCP access layer, packaging, or the destructive-op safety
  gate — the review found those areas correct, tested, and merge-ready.
- No threshold or omit changes to the coverage gate.
