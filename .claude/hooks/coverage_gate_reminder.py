#!/usr/bin/env python3
"""PostToolUse hook: remind to run the core coverage gate after touching core or tests.

Fires AFTER Edit/Write. Non-blocking: if the edited file is under ff_explorer/core.py, ff_explorer/api/,
or tests/, it emits a reminder (exit 0 with JSON additionalContext) to run the gate before claiming
done. It never blocks and never fails the session — a reminder only (CLAUDE.md invariant 3: the
>=90% core coverage gate, gui/* + __init__.py + api/main.py omitted).
"""
from __future__ import annotations

import json
import re
import sys

TARGET_RX = re.compile(r"ff_explorer[\\/]core\.py|ff_explorer[\\/]api[\\/]|(?:^|[\\/])tests[\\/]")
# pyproject addopts inject --cov; running bare `pytest` is the real gate.
GATE_CMD = "pytest  (addopts inject --cov=ff_explorer --cov-fail-under=90 --cov-report=term-missing)"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    path = (data.get("tool_input", {}) or {}).get("file_path", "") or ""
    if TARGET_RX.search(path):
        # PostToolUse additionalContext is surfaced to the model without blocking.
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"Coverage-gate reminder: you edited '{path}'. Before claiming done, run the "
                    f"core gate and READ the result: {GATE_CMD} (must exit 0; do not lower the "
                    "threshold or widen the omit to pass — CLAUDE.md invariant 3)."
                ),
            }
        }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
