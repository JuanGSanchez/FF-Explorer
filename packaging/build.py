#!/usr/bin/env python3
"""
build.py — Cross-platform reproducible build runner for FFExplorer.

Equivalent to build_windows.bat / build_posix.sh but callable with any Python
interpreter on any OS — useful for CI pipelines and environments where .bat or
.sh are inconvenient.

Usage
-----
    # From the repo root:
    python packaging/build.py

    # With explicit options:
    python packaging/build.py --log-level INFO --no-icon-convert

Prerequisites
-------------
    pip install "pyinstaller~=6.20.0" "PySide6~=6.11.1"
    pip install Pillow   # only needed for the automatic PNG->ICO step

IMPORTANT — interpreter note
-----------------------------
This repo targets Python 3.13 (campaign ceiling; FastMCP caps at 3.13).
On machines where the bare `python` resolves to an older interpreter, invoke
this script explicitly:

    py -3.13 packaging/build.py

Or use build_windows.bat which unconditionally calls `py -3.13 -m PyInstaller`.

Output
------
    packaging/bin/FFExplorer/FFExplorer.exe   (Windows)
    packaging/bin/FFExplorer/FFExplorer       (Linux)
    packaging/bin/FFExplorer.app/             (macOS)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent          # packaging/
REPO_ROOT = SCRIPT_DIR.parent              # repo root
SPEC = SCRIPT_DIR / "FFExplorer.spec"
BIN_DIR = SCRIPT_DIR / "bin"
WORK_DIR = SCRIPT_DIR / "work"
PNG_SRC = REPO_ROOT / "Logo FFE.png"
ICO_DEST = REPO_ROOT / "Logo FFE.ico"


def ensure_ico(skip: bool = False) -> bool:
    """Try to produce Logo FFE.ico from Logo FFE.png.  Returns True if .ico exists."""
    if ICO_DEST.exists():
        return True
    if skip:
        print("[build] Skipping PNG->ICO conversion (--no-icon-convert).")
        return False
    print("[build] Logo FFE.ico not found — running scripts/png_to_ico.py ...")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "scripts" / "png_to_ico.py"),
         str(PNG_SRC), str(ICO_DEST)],
        check=False,
    )
    if result.returncode != 0:
        print("[build] WARNING: PNG->ICO conversion failed. Building without icon.")
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the FFExplorer PyInstaller bundle.")
    ap.add_argument("--log-level", default="WARN",
                    choices=["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"],
                    help="PyInstaller log level (default: WARN)")
    ap.add_argument("--no-icon-convert", action="store_true",
                    help="Skip automatic PNG->ICO conversion.")
    args = ap.parse_args()

    print(f"[build] Repo root : {REPO_ROOT}")
    print(f"[build] Spec file : {SPEC}")

    ensure_ico(skip=args.no_icon_convert)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC),
        "--noconfirm",
        "--distpath", str(BIN_DIR),
        "--workpath", str(WORK_DIR),
        "--log-level", args.log_level,
    ]
    print(f"[build] Running: {' '.join(cmd)}")

    # Run from repo root so relative paths in the spec resolve correctly
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    if result.returncode != 0:
        print("[build] ERROR: PyInstaller exited with an error.", file=sys.stderr)
        sys.exit(1)

    exe = BIN_DIR / "FFExplorer" / ("FFExplorer.exe" if sys.platform == "win32" else "FFExplorer")
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\n[build] Build complete.")
        print(f"[build] Executable : {exe}  ({size_mb:.1f} MB)")
    else:
        print(f"\n[build] Build complete. Bundle at: {BIN_DIR / 'FFExplorer'}")


if __name__ == "__main__":
    main()
