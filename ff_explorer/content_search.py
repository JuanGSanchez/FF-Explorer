"""
ff_explorer.content_search
==========================
Headless helper for FFX-I09: grep-style content search of text files.

Public API
----------
    CONTENT_MAX_BYTES   — default cap (10 MiB) for files considered by the scan.
    file_content_matches(path, content_query, match_mode, case_sensitive,
                         max_bytes) -> bool

No tkinter / PySide6 / fastapi / fastmcp imports — headless-core invariant (C1).
"""
from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default maximum file size (bytes) scanned for content search.
#: Files larger than this are skipped (treated as no-match).
CONTENT_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MiB

#: Number of bytes read for the binary/null-byte heuristic check.
_BINARY_SNIFF_BYTES: int = 8192


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_binary_chunk(chunk: bytes) -> bool:
    """Return True when *chunk* contains a null byte (binary-file heuristic)."""
    return b"\x00" in chunk


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def file_content_matches(
    path: "str | Path",
    content_query: str,
    match_mode: str = "substring",
    case_sensitive: bool = True,
    max_bytes: int = CONTENT_MAX_BYTES,
    *,
    _compiled: "re.Pattern[str] | None" = None,
) -> bool:
    """Return True when the text content of *path* matches *content_query*.

    The function is safe to call on any file:

    * Files larger than *max_bytes* are skipped (returns ``False``).
    * Files containing a null byte in the first ``_BINARY_SNIFF_BYTES`` bytes
      are treated as binary and skipped (returns ``False``).
    * Files that cannot be read (permission denied, OS error, UnicodeDecodeError
      after replacement) return ``False`` — never raise.

    Parameters
    ----------
    path:
        Absolute path to the candidate file.
    content_query:
        The pattern or substring to search for inside the file.
    match_mode:
        ``"substring"`` — ``query in text`` containment test (default).
        ``"glob"``       — treated as substring for content (line-by-line
                           fnmatch is not meaningful; falls back to substring).
        ``"regex"``      — pre-compiled pattern search (provide *_compiled*);
                           falls back to ``re.search`` if *_compiled* is None.
    case_sensitive:
        Controls case sensitivity for substring and glob/fallback modes.
        For ``"regex"`` mode, case is governed by *_compiled*'s flags.
    max_bytes:
        Maximum file size in bytes to consider.  Files larger than this cap
        are skipped.  Default is :data:`CONTENT_MAX_BYTES` (10 MiB).
    _compiled:
        Pre-compiled ``re.Pattern`` for ``"regex"`` mode.  When provided,
        it is used directly (avoiding a re-compile per file).  When ``None``
        and ``match_mode == "regex"``, the pattern is compiled on-the-fly
        (callers should prefer passing a pre-compiled pattern for efficiency).

    Returns
    -------
    bool
        ``True`` when the file's text content contains a match; ``False``
        otherwise or when the file is binary/oversized/unreadable.
    """
    p = Path(path)

    try:
        # Size guard — skip files larger than max_bytes
        size = p.stat().st_size
        if size > max_bytes:
            return False

        # Read the binary content once
        raw: bytes = p.read_bytes()

        # Binary heuristic: check for null bytes in the first sniff window
        sniff = raw[:_BINARY_SNIFF_BYTES]
        if _is_binary_chunk(sniff):
            return False

        # Decode as UTF-8 with replacement for non-UTF-8 text files
        text = raw.decode("utf-8", errors="replace")

    except OSError:
        # Permission denied, file disappeared, or other I/O error — no-match
        return False

    # Apply the match
    if match_mode == "regex":
        if _compiled is not None:
            return _compiled.search(text) is not None
        # Fallback: compile on the fly (caller should prefer pre-compiling)
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            return re.search(content_query, text, flags) is not None
        except re.error:
            return False

    # "glob" and "substring" — both use substring containment for content
    # (fnmatch on full file text is not semantically meaningful; substring is
    # the sensible interpretation for content matching of either mode)
    if not case_sensitive:
        return content_query.lower() in text.lower()
    return content_query in text
