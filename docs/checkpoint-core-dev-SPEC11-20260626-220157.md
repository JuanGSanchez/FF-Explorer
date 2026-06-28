# Checkpoint: SPEC-11 Structured Logging — core-dev
Date: 2026-06-26T22:01:57Z
Item: SPEC-11 (structured logging for headless core + shared facade)
Status: IN PROGRESS (implementation not yet written)

## Acceptance criterion
- Module loggers via `logging.getLogger(__name__)` in core.py, service.py, content_search.py, dedupe.py, rename.py, presets.py
- NullHandler in ff_explorer/__init__.py
- `configure_logging(level, *, stream=None)` helper in core.py honoring FF_EXPLORER_LOG_LEVEL / FF_EXPLORER_LOG_FILE
- All suppression sites emit logger.warning/debug before continuing
- Tests: caplog assertion for suppressed skip, configure_logging env var

## Suppression sites to instrument
1. core.py:459 — _build_ignore_spec OSError reading ignore file → logger.debug
2. core.py:580 — _enumerate_archive_members bad archive → logger.warning
3. core.py:863 — list_entries folder stat OSError → logger.debug
4. core.py:882 — list_entries file stat OSError → logger.debug
5. core.py:1130 — remove_entries versioning OSError → logger.warning
6. core.py:1145 — remove_entries live removal OSError → logger.warning
7. core.py:1231 — compress_entries per-file write OSError → logger.warning
8. core.py:1239,1241,1264 — compress_entries delete/folder errors → logger.warning
9. core.py:1337 — largest_entries stat OSError → logger.debug
10. content_search.py:112 — OSError reading file → logger.debug
11. dedupe.py:124 — OSError stat → logger.debug
12. dedupe.py:182 — OSError hashing → logger.debug
13. presets.py:150 — json/OSError loading → logger.warning
14. presets.py:208 — TypeError/KeyError malformed entry → logger.warning
15. rename.py:488 — OSError on undo rename → logger.warning

## Files to change
- ff_explorer/__init__.py — add NullHandler
- ff_explorer/core.py — add logger, logging import, configure_logging helper, instrument sites 1-9
- ff_explorer/content_search.py — add logger, instrument site 10
- ff_explorer/dedupe.py — add logger, instrument sites 11-12
- ff_explorer/presets.py — add logger, instrument sites 13-14
- ff_explorer/rename.py — add logger, instrument site 15
- ff_explorer/api/service.py — add logger (no suppression sites there, but required by spec)
- tests/test_logging.py — new test file

## Invariants
- C1: no GUI/transport imports added to core
- Gate stays ≥90%
- No control flow changes; only logging calls added before continue/pass/return
