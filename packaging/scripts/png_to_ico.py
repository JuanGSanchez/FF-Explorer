#!/usr/bin/env python3
"""
png_to_ico.py — Convert a PNG file to a multi-resolution ICO file.

PyInstaller's --icon flag on Windows requires a .ico file.  The repo ships
Logo FFE.png; this script produces Logo FFE.ico for use as the EXE
taskbar/window icon.

Usage
-----
    python packaging/scripts/png_to_ico.py [src_png] [dest_ico]

    src_png  : path to source PNG  (default: Logo FFE.png in repo root)
    dest_ico : path to write .ico  (default: Logo FFE.ico in repo root)

Dependencies
------------
Requires Pillow:   pip install Pillow
(Pillow is a dev-only / build-time dependency — not bundled in the exe.)

The script exits with code 0 on success, 1 on failure.

ICO sizes generated: 16, 32, 48, 64, 128, 256 px
(Windows Explorer and taskbar use 16/32/48; 256 is used for large icon views.)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Resolve default paths relative to the repo root (two levels above this script)
_REPO_ROOT = Path(__file__).parent.parent.parent


def convert(src: Path, dest: Path) -> None:
    """Convert *src* PNG to a multi-resolution *dest* ICO."""
    try:
        from PIL import Image
    except ImportError:
        print(
            "ERROR: Pillow is not installed.  Run:\n"
            "    pip install Pillow\n"
            "then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not src.exists():
        print(f"ERROR: source PNG not found: {src}", file=sys.stderr)
        sys.exit(1)

    img = Image.open(src).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), format="ICO", sizes=sizes)
    print(f"Created {dest}  ({', '.join(f'{s[0]}x{s[1]}' for s in sizes)} px)")


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO_ROOT / "Logo FFE.png"
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else _REPO_ROOT / "Logo FFE.ico"
    convert(src, dest)


if __name__ == "__main__":
    main()
