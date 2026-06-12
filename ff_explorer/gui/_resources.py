"""
FF Explorer — bundled-asset path resolver

Usage
-----
    from ff_explorer.gui._resources import resource_path
    icon_file = resource_path("Logo FFE.png")

When the app is frozen by PyInstaller (one-file mode), data files are
extracted to a temporary directory whose path is stored in sys._MEIPASS.
When running from source, the base directory is the repository root (the
parent of this file's package hierarchy).
"""

import os
import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """
    Resolve *relative* against the bundle root (sys._MEIPASS when frozen,
    otherwise the project root two levels above this file).

    Parameters
    ----------
    relative:
        A path relative to the project/bundle root, e.g. ``"Logo FFE.png"``.

    Returns
    -------
    Path
        Absolute path suitable for opening files or passing to Qt APIs.
    """
    base: Path
    if hasattr(sys, "_MEIPASS"):
        # PyInstaller one-file/one-dir bundle: data lives in the temp dir
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        # Running from source: go up from ff_explorer/gui/ → ff_explorer/ → project root
        base = Path(__file__).resolve().parent.parent.parent

    return base / relative
