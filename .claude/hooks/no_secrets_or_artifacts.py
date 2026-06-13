#!/usr/bin/env python3
"""PreToolUse hook: block writing secrets or build artifacts (CLAUDE.md invariant 6).

Fires on Edit/Write. BLOCKS (exit 2) if:
  - the target path is a build-artifact path (packaging/bin/, packaging/work/, dist/, build/), or
  - the new content for a tracked source file contains a likely hardcoded secret
    (api key / token / secret / password assigned a non-placeholder literal).

Non-fatal on its own errors (exit 0). Block protocol: exit 2 + reason on stderr.
"""
from __future__ import annotations

import json
import re
import sys

ARTIFACT_RX = re.compile(r"(?:^|[\\/])(?:packaging[\\/](?:bin|work)|dist|build)[\\/]")
# key/secret/token/password = "<non-empty, non-placeholder literal>"
SECRET_RX = re.compile(
    r"""(?ix)
    \b(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)\b
    \s*[:=]\s*
    ['"][^'"\s]{6,}['"]
    """,
)
PLACEHOLDER_RX = re.compile(r"(?i)(your[_-]?|example|placeholder|xxx+|<.*>|changeme|dummy|fake|test)")


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

    if ARTIFACT_RX.search(path):
        sys.stderr.write(
            f"BLOCKED (no-secrets-or-artifacts): '{path}' is a build-artifact path. "
            "Build output (packaging/bin/, packaging/work/, dist/, build/) is never tracked "
            "(CLAUDE.md invariant 6). Let packaging/build.py write it into the git-ignored dir."
        )
        return 2

    text = _candidate_text(tool_input)
    for m in SECRET_RX.finditer(text):
        snippet = m.group(0)
        if not PLACEHOLDER_RX.search(snippet):
            sys.stderr.write(
                "BLOCKED (no-secrets-or-artifacts): a hardcoded secret appears in the new content "
                f"for '{path}'. Read config/env at runtime instead of embedding credentials "
                "(CLAUDE.md invariant 6). If this is a placeholder, make it obviously so."
            )
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
