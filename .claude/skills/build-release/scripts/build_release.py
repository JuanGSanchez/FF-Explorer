#!/usr/bin/env python3
"""Deterministic FF-Explorer build + verify runner.

Assesses the FFX-B01 icon trap, runs packaging/build.py (PyInstaller into the git-ignored
packaging/bin + packaging/work), confirms the bundle was produced, checks send2trash bundling, and
verifies the tree stays clean. Reports a PASS/FAIL block. No source mutation; the only writes are
into build output dirs (which must be git-ignored per invariant 6).

Usage:
    python .claude/skills/build-release/scripts/build_release.py [--repo <path>]

Exit code: 0 on PASS, 1 on FAIL, 2 on harness error.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def _icon_situation(root: Path) -> tuple[str, bool]:
    """Return (label, can_build): the FFX-B01 icon assessment."""
    ico = root / "Logo FFE.ico"
    png = root / "Logo FFE.png"
    if ico.exists():
        return ("icon present", True)
    try:
        import PIL  # noqa: F401
        pillow = True
    except Exception:
        pillow = False
    if pillow and png.exists():
        return ("generated (Pillow)", True)
    # No icon available. Is the spec guarded against the missing .ico?
    spec = (root / "packaging" / "FFExplorer.spec").read_text(encoding="utf-8", errors="ignore")
    # A guarded spec only references the .ico behind an .exists() check.
    references_ico = "Logo FFE.ico" in spec
    guarded = (".exists()" in spec) or ("if Path" in spec and "icon=" in spec)
    if references_ico and not guarded:
        return ("NO ICON — spec guard required (packaging-builder)", False)
    return ("NO ICON — spec guarded, building iconless", True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    root = Path(args.repo).resolve()

    if not (root / "pyproject.toml").exists() or not (root / "ff_explorer").exists() \
            or not (root / "packaging" / "FFExplorer.spec").exists():
        print(f"HARNESS ERROR: {root} is not the FF-Explorer repo root", file=sys.stderr)
        return 2

    findings: list[str] = []

    # --- FFX-B01 icon assessment (before building) ---
    icon_label, can_build = _icon_situation(root)
    if not can_build:
        findings.append("FFX-B01 · spec references a non-existent .ico unconditionally · packaging-builder")

    build_line = "skipped (icon guard required first)"
    build_ok = can_build

    # --- Executable build ---
    if can_build:
        exe = _run([sys.executable, "packaging/build.py"], root)
        if exe.returncode != 0:
            build_ok = False
            tail = (exe.stderr or exe.stdout)[-200:]
            if "Logo FFE.ico" in (exe.stderr + exe.stdout) or "FileNotFoundError" in (exe.stderr + exe.stdout):
                build_line = "FAIL (PyInstaller FileNotFoundError on 'Logo FFE.ico' — FFX-B01)"
                findings.append("FFX-B01 · build aborted on missing .ico · packaging-builder")
            else:
                build_line = f"FAIL (build.py exit {exe.returncode}: ...{tail.strip()})"
                findings.append("HIGH · exe build · packaging/build.py failed · packaging-builder")
        else:
            bundle = root / "packaging" / "bin" / "FFExplorer"
            if bundle.exists():
                build_line = "OK (exit 0, bundle at packaging/bin/FFExplorer)"
            else:
                build_ok = False
                build_line = "FAIL (build.py exit 0 but no bundle at packaging/bin/FFExplorer)"
                findings.append("HIGH · exe build · no bundle produced · packaging-builder")

    # --- send2trash bundling (invariant 2 runtime dep; FFX-B04 POSIX skew) ---
    spec = (root / "packaging" / "FFExplorer.spec").read_text(encoding="utf-8", errors="ignore")
    s2t_ok = "send2trash" in spec
    posix_backend = ("plat_other" in spec) or ("send2trash.mac" in spec)
    if not s2t_ok:
        s2t_line = "FAIL"
        findings.append("HIGH · send2trash · not declared in spec hiddenimports · packaging-builder")
    elif sys.platform != "win32" and not posix_backend:
        s2t_line = "ISSUE (POSIX backend missing — FFX-B04)"
        findings.append("MED · send2trash · POSIX backend (plat_other/mac) absent · packaging-builder")
    else:
        s2t_line = "OK"

    # --- Clean-tree hygiene (invariant 6) ---
    status = _run(["git", "status", "--porcelain"], root)
    tracked_new = [
        ln[3:] for ln in status.stdout.splitlines()
        if re.search(r"packaging/(bin|work)/|^dist/|^build/", ln[3:]) and not ln.startswith("!!")
    ]
    clean_ok = not tracked_new
    if not clean_ok:
        findings.append(f"HIGH · clean tree · tracked artifact {tracked_new[0]} · packaging-builder")

    overall = can_build and build_ok and s2t_ok and clean_ok

    print(f"BUILD RELEASE: {'PASS' if overall else 'FAIL'}")
    print(f"- Icon trap (FFX-B01): {icon_label}")
    print(f"- Executable build: {build_line}")
    print(f"- send2trash bundled: {s2t_line}")
    print(f"- Clean tree (no tracked artifacts): {'OK' if clean_ok else 'ISSUE ' + tracked_new[0]}")
    print("Findings: " + ("; ".join(findings) if findings else "none"))
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
