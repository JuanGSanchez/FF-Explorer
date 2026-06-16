---
name: build-release
description: >
  Builds the FF-Explorer PyInstaller executable deterministically, guarding the FFX-B01 icon trap
  (the spec references a `Logo FFE.ico` that is not in the repo and only exists if Pillow generates
  it — an unguarded `.ico` reference aborts the build with FileNotFoundError). Runs the build,
  verifies the bundle was produced (with or without the icon), confirms send2trash is bundled, and
  checks the tree stays clean (no artifact tracked). Use when asked to "build the executable",
  "build a release", "make the FFExplorer build", or to verify the build before tagging. Pairs with
  the packaging-builder agent.
version: 0.1.0
principles_applied:
  inherited:
    - P1 — Source-of-Truth Grounding
    - P2 — Full Determinism
    - P4 — Consistency
    - P5 — Context Budget Discipline
    - P6 — Self-Containment
    - P7 — Reference Hygiene
  custom:
    - id: C1
      name: Icon-Trap Guard (FFX-B01)
      requires: >
        The skill must not let an unguarded `.ico` reference abort the build. It pre-checks the
        icon situation and reports whether the build can complete with no icon, generates the icon
        when Pillow is available, and never edits the spec itself (that is packaging-builder's job).
      rationale: FFX-B01 is the CRITICAL out-of-the-box build failure; a build skill that ignores it
        reports a false PASS or a confusing FileNotFoundError.
---
# Build Release

Deterministic PyInstaller build + verify pipeline for FF-Explorer, reporting buildability, the FFX-B01 icon situation, send2trash bundling, and clean-tree hygiene.

## Workflow

### Step 1: Locate the repo root and confirm prerequisites
Confirm the root holds `pyproject.toml`, `packaging/FFExplorer.spec`, and `packaging/build.py`. Confirm the `ff_explorer` package is present. A missing piece is a HARNESS error — STOP.

### Step 2: Assess the FFX-B01 icon trap BEFORE building (C1)
Determine the icon situation so the build does not abort with `FileNotFoundError`:
- If `Logo FFE.ico` exists at the repo root → the icon will embed.
- Else if Pillow is importable AND `Logo FFE.png` exists → `build.py` `ensure_ico()` will generate it.
- Else → the build must proceed WITHOUT an icon. If the spec still references the `.ico`
  unconditionally (`icon=str(...'Logo FFE.ico')` not guarded by an `.exists()` check — FFX-B01),
  PyInstaller will raise `FileNotFoundError`. Report this as the FFX-B01 fix being required and do
  NOT claim a clean build. Never edit the spec here — route the guard fix to packaging-builder.

### Step 3: Build the executable
Run `scripts/build_release.py --repo <root>`. It invokes `python packaging/build.py` (which runs `ensure_ico` then PyInstaller into the git-ignored `packaging/bin/` + `packaging/work/`), then confirms the bundle exists. READ the output. A non-zero exit means the build failed — report the cause (distinguish an FFX-B01 icon abort from a genuine PyInstaller error) and stop.

### Step 4: Verify send2trash is bundled
Confirm the spec declares the `send2trash` hidden import (the recycle-bin route depends on it at runtime — invariant 2). Note: FFX-B04 tracks the Windows-skew (`send2trash.win` only); flag if the POSIX backend (`send2trash.plat_other`/`.mac`) is absent on a non-Windows build. Never edit the spec.

### Step 5: Verify clean tree
Run the hygiene check (`git status --porcelain`): build output (`packaging/bin/`, `packaging/work/`, `dist/`, `build/`) must stay untracked/ignored (invariant 6). A newly tracked artifact is a FAIL.

### Step 6: Report
Report each stage PASS/FAIL with proving evidence (icon situation, build exit code, bundle present, send2trash bundled, clean-tree status). Do not claim a stage passed without reading its output.

## Output Format

```
BUILD RELEASE: PASS | FAIL
- Icon trap (FFX-B01): icon present | generated (Pillow) | NO ICON — spec guard required (packaging-builder)
- Executable build: OK (exit 0, bundle at packaging/bin/FFExplorer) | FAIL <detail>
- send2trash bundled: OK | ISSUE (POSIX backend missing — FFX-B04) | FAIL
- Clean tree (no tracked artifacts): OK | ISSUE <path>
Findings: <stage · evidence · owning agent> (or "none")
```

## Examples

### Example 1
**Input:** "Build the FFExplorer executable and verify it." (no `.ico`, no Pillow)
**Output:**
```
BUILD RELEASE: FAIL
- Icon trap (FFX-B01): NO ICON — spec guard required (packaging-builder)
- Executable build: FAIL (PyInstaller FileNotFoundError on 'Logo FFE.ico')
- send2trash bundled: OK
- Clean tree (no tracked artifacts): OK
Findings: FFX-B01 · spec references a non-existent .ico unconditionally · packaging-builder
```

### Example 2
**Input:** "Build the executable." (`.ico` present)
**Output:**
```
BUILD RELEASE: PASS
- Icon trap (FFX-B01): icon present
- Executable build: OK (exit 0, bundle at packaging/bin/FFExplorer)
- send2trash bundled: OK
- Clean tree (no tracked artifacts): OK
Findings: none
```

## Scripts

- `scripts/build_release.py` — assesses the FFX-B01 icon situation, runs `packaging/build.py`, confirms the bundle, checks send2trash bundling, and verifies tree hygiene. Run when: building a release. Expected output: the report block; exit 0 on PASS, 1 on FAIL, 2 on harness error. Deterministic given the source tree (PyInstaller binary bytes vary, but the verified properties — bundle present, send2trash declared, clean tree — are stable). Never mutates source.

## Self-Containment Index

This skill package contains everything needed for its complete usage:
- SKILL.md (this file): workflow, output format, examples
- scripts/build_release.py: deterministic build + verify runner

External dependencies (must be available in the execution environment):
- Python 3.13 (campaign ceiling; FastMCP caps at 3.13) with PyInstaller + PySide6 installed (`pip install "ff-explorer[dev]"` or per packaging/build.py prerequisites).
- Pillow (optional) — only to generate `Logo FFE.ico` from `Logo FFE.png`; the build proceeds without it once the spec guards the icon (FFX-B01).
- git: clean-tree hygiene check.

## Sources
- `CLAUDE.md` (invariants 2, 4, 6; build commands), `docs/BACKLOG.md` (FFX-B01 icon trap, FFX-B04 send2trash skew), `packaging/FFExplorer.spec`, `packaging/build.py` (`ensure_ico`, `--no-icon-convert`), `packaging/scripts/png_to_ico.py`.
- references/claude.md §SKILL: frontmatter, description rules, body structure.
