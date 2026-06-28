#!/usr/bin/env python3
"""PreToolUse hook: block reintroducing the legacy Tkinter/.pyw GUI (regression guard).

FF-Explorer migrated off the legacy Tkinter GUI (FF_UI.pyw, removed — FFX-B02)
to PySide6 (ff_explorer/gui/); tkinter and .pyw entry points must never reappear.
Fires on Edit/Write. BLOCKS (exit 2) if the target is a .pyw file OR the new content adds an
`import tkinter` / `from tkinter ...` anywhere in the repo. Otherwise exits 0.

Non-fatal on its own errors (exit 0). Block protocol: exit 2 + reason on stderr.

## Principles Applied
P2 Full Determinism, P4 Consistency (guards the completed Tk->PySide6 migration against
Tk reintroduction), P8 Principles Inheritance, P11 Programmatic Determinism (hook IS the harness).
"""
from __future__ import annotations

import json
import re
import sys

TK_IMPORT_RX = re.compile(r"^\s*(?:import|from)\s+tkinter\b", re.MULTILINE)


def _candidate_text(tool_input: dict) -> str:
    parts = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    for e in tool_input.get("edits", []) or []:
        parts.append(e.get("new_string", ""))
    return "\n".join(p for p in parts if p)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    path = tool_input.get("file_path", "") or ""

    if path.endswith(".pyw"):
        sys.stderr.write(
            f"BLOCKED (tkinter-regression-guard): '{path}' is a .pyw file. The legacy Tkinter GUI "
            "(FF_UI.pyw) was replaced by PySide6 (ff_explorer/gui/) and removed (FFX-B02); "
            ".pyw entry points must not return."
        )
        return 2

    if TK_IMPORT_RX.search(_candidate_text(tool_input)):
        sys.stderr.write(
            f"BLOCKED (tkinter-regression-guard): a tkinter import is being added to '{path}'. "
            "The GUI is PySide6-only now; use ff_explorer/gui/ (gui-dev). tkinter is a regression."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
