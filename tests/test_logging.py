"""
tests/test_logging.py
=====================
SPEC-11: Structured logging for ff_explorer headless core and shared facade.

Acceptance criteria verified here:
  (a) Suppressed-skip sites emit a log record at the expected level
      (WARNING or DEBUG) — verified with pytest caplog.
  (b) configure_logging() honours FF_EXPLORER_LOG_LEVEL env var.
  (c) ff_explorer package logger carries a NullHandler at import time
      (library best-practice — no "No handlers" noise).
  (d) configure_logging() rejects an unknown level name with ValueError.
  (e) configure_logging() accepts an explicit stream (not stderr).

All tests are deterministic and offline (no network, no real GUI).
"""
from __future__ import annotations

import io
import logging
import os
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# (c) NullHandler on package logger at import time
# ---------------------------------------------------------------------------

class TestNullHandler:
    def test_package_logger_has_null_handler(self):
        """ff_explorer package logger must carry a NullHandler so that library
        consumers that don't configure logging never see 'No handlers' noise."""
        import ff_explorer  # noqa: F401 — ensures __init__ has run
        pkg_logger = logging.getLogger("ff_explorer")
        handler_types = [type(h) for h in pkg_logger.handlers]
        assert logging.NullHandler in handler_types, (
            f"Expected NullHandler in ff_explorer logger handlers, got {handler_types}"
        )


# ---------------------------------------------------------------------------
# (a) Suppressed-skip sites — WARNING / DEBUG records emitted via caplog
# ---------------------------------------------------------------------------

class TestArchiveSkipLogged:
    """_enumerate_archive_members: malformed archive → WARNING in ff_explorer.core."""

    def test_bad_zip_emits_warning(self, tmp_path, caplog):
        """A truncated/invalid ZIP file must emit a WARNING record and return
        an empty list (skip gracefully), not raise."""
        from ff_explorer.core import list_entries, EntryKind

        # Create a file with .zip extension but invalid content
        bad_zip = tmp_path / "corrupt.zip"
        bad_zip.write_bytes(b"this is not a valid zip file at all")

        with caplog.at_level(logging.WARNING, logger="ff_explorer.core"):
            results = list_entries(
                tmp_path, EntryKind.FILES, "anything",
                search_archives=True,
            )

        # The corrupt archive must be skipped — no crash
        archive_results = [r for r in results if "!" in str(r.path)]
        assert archive_results == [], "Corrupt archive should yield no members"

        # A WARNING must have been emitted mentioning the archive path
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "corrupt.zip" in r.message
        ]
        assert warning_records, (
            "Expected a WARNING log record mentioning 'corrupt.zip' "
            f"for unreadable archive; got records: {[r.message for r in caplog.records]}"
        )


class TestIgnoreFileSkipLogged:
    """_build_ignore_spec: unreadable ignore file → DEBUG record."""

    def test_unreadable_ignore_file_emits_debug(self, tmp_path, caplog):
        """When an ignore file cannot be read (OSError), a DEBUG record is
        emitted and the walk continues normally."""
        from ff_explorer.core import list_entries, EntryKind

        # Create a real file so the walk finds something
        (tmp_path / "hello.txt").write_text("hi")

        # Patch read_text on Path to raise OSError only for ignore-file names
        _IGNORE_NAMES = {".gitignore", ".ignore"}
        original_read_text = Path.read_text

        def patched_read_text(self, *args, **kwargs):
            if self.name in _IGNORE_NAMES:
                raise OSError("permission denied (mocked)")
            return original_read_text(self, *args, **kwargs)

        with caplog.at_level(logging.DEBUG, logger="ff_explorer.core"):
            with patch.object(Path, "read_text", patched_read_text):
                results = list_entries(
                    tmp_path, EntryKind.FILES, "hello",
                    respect_ignore=True,
                )

        # Walk must still return the file (skip is of the ignore file, not the target)
        names = [r.path.name for r in results]
        assert "hello.txt" in names

        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "ignore" in r.message.lower()
        ]
        assert debug_records, (
            "Expected a DEBUG log record about unreadable ignore file; "
            f"got: {[r.message for r in caplog.records]}"
        )


class TestStatSkipLogged:
    """list_entries: OSError on stat → DEBUG record, entry skipped."""

    def test_unreadable_file_stat_emits_debug(self, tmp_path, caplog):
        from ff_explorer.core import list_entries, EntryKind

        f = tmp_path / "target.txt"
        f.write_text("data")

        original_stat = Path.stat

        def patched_stat(self, *args, **kwargs):
            if self.name == "target.txt":
                raise OSError("permission denied (mocked)")
            return original_stat(self, *args, **kwargs)

        with caplog.at_level(logging.DEBUG, logger="ff_explorer.core"):
            with patch.object(Path, "stat", patched_stat):
                # min_size forces stat to be called
                results = list_entries(
                    tmp_path, EntryKind.FILES, "target",
                    min_size=0,
                )

        # Entry must be skipped
        assert results == []

        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "target.txt" in r.message
        ]
        assert debug_records, (
            "Expected a DEBUG record for unreadable file stat; "
            f"got: {[r.message for r in caplog.records]}"
        )


class TestRemoveEntriesFailureLogged:
    """remove_entries: per-item OSError → WARNING in ff_explorer.core."""

    def test_remove_failure_emits_warning(self, tmp_path, caplog):
        from ff_explorer.core import remove_entries, EntryKind

        f = tmp_path / "deleteme.txt"
        f.write_text("bye")

        original_send2trash_available = None

        # Patch send2trash unavailable path and force OSError on os.remove
        with patch("ff_explorer.core._SEND2TRASH_AVAILABLE", False), \
             patch("ff_explorer.core.os.remove", side_effect=OSError("mocked remove fail")), \
             caplog.at_level(logging.WARNING, logger="ff_explorer.core"):
            report = remove_entries(
                tmp_path, EntryKind.FILES, "deleteme",
                dry_run=False, confirm=True,
            )

        assert report.failed, "Expected at least one failure in report"
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "deleteme" in r.message
        ]
        assert warning_records, (
            "Expected a WARNING record for failed remove; "
            f"got: {[r.message for r in caplog.records]}"
        )


class TestLargestEntriesStatSkipLogged:
    """largest_entries: OSError on stat → DEBUG record."""

    def test_unreadable_stat_emits_debug(self, tmp_path, caplog):
        from ff_explorer.core import largest_entries

        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 100)

        original_stat = Path.stat

        def patched_stat(self, *args, **kwargs):
            if self.name == "big.bin":
                raise OSError("permission denied (mocked)")
            return original_stat(self, *args, **kwargs)

        with caplog.at_level(logging.DEBUG, logger="ff_explorer.core"):
            with patch.object(Path, "stat", patched_stat):
                results = largest_entries(tmp_path, top_n=10)

        # File must be absent from results
        paths = [r.path for r in results]
        assert not any("big.bin" in p for p in paths)

        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "big.bin" in r.message
        ]
        assert debug_records, (
            f"Expected a DEBUG record for unreadable stat; got: {[r.message for r in caplog.records]}"
        )


class TestDedupeSkipLogged:
    """dedupe: OSError on stat → DEBUG record."""

    def test_unreadable_stat_emits_debug(self, tmp_path, caplog):
        from ff_explorer.dedupe import find_duplicates

        f = tmp_path / "a.bin"
        f.write_bytes(b"hello")

        with caplog.at_level(logging.DEBUG, logger="ff_explorer.dedupe"):
            with patch("ff_explorer.dedupe.os.path.getsize", side_effect=OSError("mocked")):
                results = find_duplicates(str(tmp_path), min_size=1)

        assert results == []
        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "dedupe" in r.name
        ]
        assert debug_records, (
            f"Expected a DEBUG record from ff_explorer.dedupe; got: {[r.message for r in caplog.records]}"
        )


class TestPresetsLoadFailureLogged:
    """presets._load_raw: corrupt file → WARNING record."""

    def test_corrupt_presets_file_emits_warning(self, tmp_path, caplog):
        import ff_explorer.presets as presets_mod

        corrupt = tmp_path / "presets.json"
        corrupt.write_text("{ this is not valid json !!!")

        with patch.object(presets_mod, "presets_file", return_value=corrupt):
            with caplog.at_level(logging.WARNING, logger="ff_explorer.presets"):
                result = presets_mod.list_presets()

        assert result == []
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "presets" in r.name
        ]
        assert warning_records, (
            f"Expected a WARNING from ff_explorer.presets; got: {[r.message for r in caplog.records]}"
        )


class TestReplayUndoFailureLogged:
    """replay_undo: OSError on rename → WARNING record (best-effort)."""

    def test_undo_rename_failure_emits_warning(self, tmp_path, caplog):
        import json
        from ff_explorer.rename import replay_undo

        # Write a valid undo file mapping a nonexistent new path to old path
        new_p = str(tmp_path / "new_name.txt")
        old_p = str(tmp_path / "old_name.txt")
        undo_file = tmp_path / "undo.json"
        undo_file.write_text(json.dumps({new_p: old_p}), encoding="utf-8")

        # new_p does not exist — rename will raise OSError
        with caplog.at_level(logging.WARNING, logger="ff_explorer.rename"):
            results = replay_undo(str(undo_file))

        # best-effort: pair is still returned even though rename failed
        assert results == [(new_p, old_p)]
        warning_records = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "rename" in r.name
        ]
        assert warning_records, (
            f"Expected a WARNING from ff_explorer.rename; got: {[r.message for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# (b) configure_logging — env var FF_EXPLORER_LOG_LEVEL honoured
# ---------------------------------------------------------------------------

class TestConfigureLogging:
    """configure_logging() in ff_explorer.core."""

    def _fresh_pkg_logger(self):
        """Return the ff_explorer logger with all handlers stripped (test isolation)."""
        pkg = logging.getLogger("ff_explorer")
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)
        return pkg

    def test_explicit_level_sets_logger(self):
        from ff_explorer.core import configure_logging
        pkg = self._fresh_pkg_logger()
        stream = io.StringIO()
        configure_logging("DEBUG", stream=stream)
        assert pkg.level == logging.DEBUG
        # Cleanup
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)

    def test_env_var_log_level_honoured(self, monkeypatch):
        """FF_EXPLORER_LOG_LEVEL env var overrides the default WARNING level."""
        from ff_explorer.core import configure_logging
        pkg = self._fresh_pkg_logger()
        monkeypatch.setenv("FF_EXPLORER_LOG_LEVEL", "DEBUG")
        stream = io.StringIO()
        configure_logging(stream=stream)  # level=None → read from env
        assert pkg.level == logging.DEBUG
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)

    def test_env_var_absent_defaults_to_warning(self, monkeypatch):
        """When FF_EXPLORER_LOG_LEVEL is absent, default is WARNING."""
        from ff_explorer.core import configure_logging
        pkg = self._fresh_pkg_logger()
        monkeypatch.delenv("FF_EXPLORER_LOG_LEVEL", raising=False)
        stream = io.StringIO()
        configure_logging(stream=stream)
        assert pkg.level == logging.WARNING
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)

    def test_unknown_level_raises_value_error(self):
        """configure_logging("BOGUS") must raise ValueError, not silently pass."""
        from ff_explorer.core import configure_logging
        with pytest.raises(ValueError, match="BOGUS"):
            configure_logging("BOGUS", stream=io.StringIO())

    def test_log_record_reaches_stream(self):
        """After configure_logging, a WARNING emitted by core code reaches the stream."""
        from ff_explorer.core import configure_logging, logger as core_logger
        pkg = self._fresh_pkg_logger()
        stream = io.StringIO()
        configure_logging("WARNING", stream=stream)
        core_logger.warning("SPEC11-test-sentinel")
        output = stream.getvalue()
        assert "SPEC11-test-sentinel" in output, (
            f"Expected sentinel in stream output; got: {output!r}"
        )
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)

    def test_integer_level_accepted(self):
        """configure_logging accepts an integer level (e.g. logging.INFO)."""
        from ff_explorer.core import configure_logging
        pkg = self._fresh_pkg_logger()
        stream = io.StringIO()
        configure_logging(logging.INFO, stream=stream)
        assert pkg.level == logging.INFO
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)

    def test_ff_explorer_log_file_env_var(self, tmp_path, monkeypatch):
        """FF_EXPLORER_LOG_FILE causes a FileHandler to be attached."""
        from ff_explorer.core import configure_logging
        pkg = self._fresh_pkg_logger()
        log_path = tmp_path / "ff_explorer_test.log"
        monkeypatch.setenv("FF_EXPLORER_LOG_FILE", str(log_path))
        monkeypatch.delenv("FF_EXPLORER_LOG_LEVEL", raising=False)
        configure_logging("WARNING")  # stream=None → picks up env var file
        # Find the FileHandler
        file_handlers = [h for h in pkg.handlers if isinstance(h, logging.FileHandler)]
        assert file_handlers, "Expected a FileHandler when FF_EXPLORER_LOG_FILE is set"
        # Emit a record and verify it appears in the file
        from ff_explorer.core import logger as core_logger
        core_logger.warning("file-handler-sentinel")
        for h in pkg.handlers:
            h.flush()
            if hasattr(h, "close"):
                h.close()
        pkg.handlers.clear()
        pkg.setLevel(logging.NOTSET)
        content = log_path.read_text(encoding="utf-8")
        assert "file-handler-sentinel" in content, (
            f"Expected sentinel in log file; got: {content!r}"
        )
