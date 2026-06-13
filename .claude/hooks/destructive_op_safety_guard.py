#!/usr/bin/env python3
"""PreToolUse hook: protect the destructive-op safety invariant (CLAUDE.md invariant 2).

FF-Explorer-specific. The core's remove/compress paths and the API boundary enforce a hard safety
gate; weakening it is the exact regression the campaign exists to prevent. Fires on Edit/Write to
the core (ff_explorer/core.py) and the access layer (ff_explorer/api/*). BLOCKS (exit 2) when the
new content visibly weakens any of the three legs of the invariant:

  (a) Recycle-bin routing for removes: removing/replacing the send2trash route (deletes must go to
      the OS recycle bin, recoverable) — e.g. swapping send2trash for os.remove/os.unlink/
      shutil.rmtree/Path.unlink on the remove path.
  (b) dry_run + confirm gate: flipping the safe defaults so a destructive op runs without
      dry_run=false AND confirm=true — e.g. defaulting dry_run=False or confirm=True.
  (c) Non-empty seed: weakening the empty-seed rejection — e.g. dropping name_seed min_length=1 /
      EmptySeedError, or setting min_length=0.

This is a guard against ACCIDENTAL weakening, not a proof of correctness; the reviewer agent and
the test gate remain the authority. Pattern-matches the new content only — it does not parse the
AST. False positives are intentional (fail-closed on the safety surface); narrow the edit or route
it through access-dev/core-dev with the reviewer if the block is wrong.

Non-fatal on its own errors (exit 0). Block protocol: exit 2 + reason on stderr.
"""
from __future__ import annotations

import json
import re
import sys

# Only police the modules that own the destructive surface.
GUARDED_RX = re.compile(r"ff_explorer[\\/](?:core\.py|api[\\/])")

# (a) recycle-bin route weakened: a raw permanent-delete call appears on the destructive path.
RAW_DELETE_RX = re.compile(
    r"\b(?:os\.remove|os\.unlink|shutil\.rmtree)\s*\(|\.unlink\s*\(",
)
# (b) safe defaults flipped: dry_run defaulting False, or confirm defaulting True.
# Tolerate an optional PEP-style annotation (`: <type>`) and arbitrary whitespace around `=`,
# so the FastAPI/Pydantic form `dry_run: bool = False` is caught as well as the bare form.
DRY_RUN_DEFAULT_FALSE_RX = re.compile(r"\bdry_run\b\s*(?::\s*[^=]+?\s*)?=\s*False\b")
CONFIRM_DEFAULT_TRUE_RX = re.compile(r"\bconfirm\b\s*(?::\s*[^=]+?\s*)?=\s*True\b")
# (c) empty-seed rejection weakened.
MIN_LENGTH_ZERO_RX = re.compile(r"\bmin_length\b\s*=\s*0\b")


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
    if not GUARDED_RX.search(path):
        return 0

    text = _candidate_text(tool_input)

    if RAW_DELETE_RX.search(text):
        sys.stderr.write(
            f"BLOCKED (destructive-op-safety-guard): a permanent-delete call (os.remove/os.unlink/"
            f"shutil.rmtree/.unlink) is appearing in '{path}'. Live removes MUST route to the OS "
            "recycle bin via send2trash (recoverable) — CLAUDE.md invariant 2. (compress is the one "
            "exception: it permanently deletes originals AFTER the zip succeeds.) If this is a "
            "legitimate non-remove use, route it through core-dev/access-dev with reviewer sign-off."
        )
        return 2

    if DRY_RUN_DEFAULT_FALSE_RX.search(text):
        sys.stderr.write(
            f"BLOCKED (destructive-op-safety-guard): 'dry_run' is being defaulted to False in "
            f"'{path}'. Destructive ops MUST preview by default (dry_run=true) and mutate only with "
            "dry_run=false AND confirm=true together — CLAUDE.md invariant 2. Keep dry_run defaulting True."
        )
        return 2

    if CONFIRM_DEFAULT_TRUE_RX.search(text):
        sys.stderr.write(
            f"BLOCKED (destructive-op-safety-guard): 'confirm' is being defaulted to True in '{path}'. "
            "A live destructive run requires an EXPLICIT confirm=true alongside dry_run=false — never a "
            "defaulted-on confirm (CLAUDE.md invariant 2). Keep confirm defaulting False."
        )
        return 2

    if MIN_LENGTH_ZERO_RX.search(text):
        sys.stderr.write(
            f"BLOCKED (destructive-op-safety-guard): 'min_length=0' on the seed in '{path}' weakens "
            "the empty-seed rejection. An empty/whitespace name_seed matches everything under the path "
            "and MUST be rejected (EmptySeedError / name_seed min_length=1) — CLAUDE.md invariant 2."
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
