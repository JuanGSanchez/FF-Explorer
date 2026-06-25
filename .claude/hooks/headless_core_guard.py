#!/usr/bin/env python3
"""PreToolUse hook: keep ff_explorer/core.py headless (CLAUDE.md invariant 1).

Fires on Edit/Write. Reads the Claude Code hook JSON from stdin, inspects the tool input, and
BLOCKS (exit 2) if new content for the headless core (ff_explorer/core.py) introduces a GUI or
transport import (PySide6/PyQt/tkinter/fastapi/fastmcp/mcp). The shared core must stay importable
headless so both REST and MCP can sit over it. Otherwise exits 0 (allow).

Non-fatal on its own errors: any parse/IO failure exits 0 so the hook never wedges the session.
Block protocol: exit code 2 + reason on stderr (Claude Code feeds stderr back to the model).

## Principles Applied
P2 Full Determinism, P8 Principles Inheritance, P9 Role Separation (enforces the UI-independent
core boundary — CLAUDE.md invariant 1), P11 Programmatic Determinism (hook IS the harness).
"""
from __future__ import annotations

import json
import re
import sys

CORE_RX = re.compile(r"ff_explorer[\\/]core\.py$")
FORBIDDEN_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(PySide\d?|PyQt\d?|tkinter|fastapi|fastmcp|mcp)\b",
    re.MULTILINE,
)


def _candidate_text(tool_input: dict) -> str:
    # Write: full content; Edit: the replacement; MultiEdit: all replacements.
    parts = [tool_input.get("content", ""), tool_input.get("new_string", "")]
    for e in tool_input.get("edits", []) or []:
        parts.append(e.get("new_string", ""))
    return "\n".join(p for p in parts if p)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # never wedge the session on a parse error
    tool_input = data.get("tool_input", {}) or {}
    path = tool_input.get("file_path", "") or ""
    if not CORE_RX.search(path):
        return 0
    m = FORBIDDEN_IMPORT.search(_candidate_text(tool_input))
    if m:
        sys.stderr.write(
            f"BLOCKED (headless-core-guard): '{m.group(1)}' import into the headless core '{path}'. "
            "ff_explorer/core.py must stay GUI/transport-free so REST+MCP both sit over one core "
            "(CLAUDE.md invariant 1). Put GUI logic in ff_explorer/gui/ (gui-dev) or transport in "
            "ff_explorer/api/ (access-dev)."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
