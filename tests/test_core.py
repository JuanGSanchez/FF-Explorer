"""
Test suite for ff_explorer.core — pure query and guarded destructive ops.

MUST-ASSERT safety contract coverage:
  1. Blank/whitespace seed -> EmptySeedError on remove_entries + compress_entries.
  2. dry_run=True (default) deletes nothing.
  3. dry_run=False without confirm=True raises ValueError; nothing removed.
  4. dry_run=False + confirm=True routes through send2trash (not os.remove).
  5. case_sensitive flag toggles matching correctly.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import patch, call

import pytest

from ff_explorer.core import (
    EntryKind,
    MatchEntry,
    RemovalReport,
    CompressionReport,
    FFExplorerError,
    EmptySeedError,
    list_entries,
    entry_metadata,
    save_listing,
    remove_entries,
    compress_entries,
)


# ===========================================================================
# Enums / data-types
# ===========================================================================

class TestEntryKind:
    def test_folders_value(self):
        assert EntryKind.FOLDERS == 0

    def test_files_value(self):
        assert EntryKind.FILES == 1

    def test_int_conversion(self):
        assert EntryKind(0) is EntryKind.FOLDERS
        assert EntryKind(1) is EntryKind.FILES


class TestMatchEntry:
    def test_str_returns_path(self, tmp_path):
        entry = MatchEntry(path=tmp_path / "x.txt", kind=EntryKind.FILES)
        assert str(entry) == str(tmp_path / "x.txt")

    def test_frozen(self, tmp_path):
        entry = MatchEntry(path=tmp_path / "x.txt", kind=EntryKind.FILES)
        with pytest.raises((AttributeError, TypeError)):
            entry.path = tmp_path / "y.txt"  # type: ignore[misc]


class TestRemovalReport:
    def test_would_affect_alias(self):
        paths = [Path("/a"), Path("/b")]
        r = RemovalReport(matched=paths)
        assert r.would_affect is r.matched

    def test_dry_run_default(self):
        r = RemovalReport()
        assert r.dry_run is True


class TestCompressionReport:
    def test_would_affect_alias(self):
        paths = [Path("/a")]
        r = CompressionReport(matched=paths)
        assert r.would_affect is r.matched

    def test_dry_run_default(self):
        r = CompressionReport()
        assert r.dry_run is True


# ===========================================================================
# Typed errors
# ===========================================================================

class TestErrors:
    def test_empty_seed_error_is_ff_explorer_error(self):
        exc = EmptySeedError("test_op")
        assert isinstance(exc, FFExplorerError)

    def test_empty_seed_error_message(self):
        exc = EmptySeedError("remove_entries")
        assert "remove_entries()" in str(exc)
        assert exc.operation == "remove_entries"


# ===========================================================================
# list_entries — pure query
# ===========================================================================

class TestListEntries:
    def test_files_no_seed_returns_all_files(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FILES)
        names = {e.path.name for e in results}
        assert names == {"alpha.txt", "beta.log", "gamma.txt", "delta.txt", "epsilon.log", "zeta.TXT"}

    def test_files_seed_filters(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FILES, "alpha")
        assert len(results) == 1
        assert results[0].path.name == "alpha.txt"

    def test_folders_kind_returns_dirs(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FOLDERS)
        names = {e.path.name for e in results}
        assert names == {"sub", "sub2"}
        for e in results:
            assert e.kind == EntryKind.FOLDERS

    def test_no_match_returns_empty(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FILES, "nonexistent_xyz")
        assert results == []

    def test_returns_match_entries(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FILES, "txt")
        for e in results:
            assert isinstance(e, MatchEntry)
            assert e.kind == EntryKind.FILES

    def test_seed_as_substring(self, simple_tree):
        # "et" matches "beta.log" and "epsilon.log" (both contain 'e')
        results = list_entries(simple_tree, EntryKind.FILES, "log")
        names = {e.path.name for e in results}
        assert "beta.log" in names
        assert "epsilon.log" in names

    def test_case_sensitive_default(self, simple_tree):
        # "txt" should NOT match "zeta.TXT" with default case_sensitive=True
        results = list_entries(simple_tree, EntryKind.FILES, ".txt")
        names = {e.path.name for e in results}
        assert "zeta.TXT" not in names
        assert "alpha.txt" in names

    def test_case_insensitive(self, simple_tree):
        # ".txt" should match "zeta.TXT" when case_sensitive=False
        results = list_entries(simple_tree, EntryKind.FILES, ".txt", case_sensitive=False)
        names = {e.path.name for e in results}
        assert "zeta.TXT" in names
        assert "alpha.txt" in names

    def test_integer_kind(self, simple_tree):
        # Accept raw int (0=FOLDERS, 1=FILES)
        results = list_entries(simple_tree, 1, "txt")
        assert all(e.kind == EntryKind.FILES for e in results)

    def test_invalid_path_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError, match="must be an existing directory"):
            list_entries(str(tmp_path / "no_such_dir"), EntryKind.FILES)

    def test_file_path_raises_value_error(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("x")
        with pytest.raises(ValueError):
            list_entries(f, EntryKind.FILES)

    def test_paths_are_absolute(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FILES, "alpha")
        assert results[0].path.is_absolute()

    def test_recursive_walk(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FILES, "delta")
        assert len(results) == 1
        assert results[0].path.parent.name == "sub"

    def test_folder_seed_filter(self, simple_tree):
        results = list_entries(simple_tree, EntryKind.FOLDERS, "sub2")
        assert len(results) == 1
        assert results[0].path.name == "sub2"


# ===========================================================================
# entry_metadata
# ===========================================================================

class TestEntryMetadata:
    def test_file_metadata_keys(self, tmp_path):
        f = tmp_path / "note.txt"
        f.write_text("hello")
        meta = entry_metadata(f)
        assert set(meta.keys()) == {"path", "type", "size_bytes", "mtime", "exists"}

    def test_file_type(self, tmp_path):
        f = tmp_path / "note.txt"
        f.write_text("hello world")
        meta = entry_metadata(f)
        assert meta["type"] == "file"
        assert meta["exists"] is True

    def test_file_size(self, tmp_path):
        f = tmp_path / "sized.txt"
        content = "hello world"
        f.write_bytes(content.encode("utf-8"))
        meta = entry_metadata(f)
        assert meta["size_bytes"] == len(content.encode("utf-8"))

    def test_directory_type(self, tmp_path):
        meta = entry_metadata(tmp_path)
        assert meta["type"] == "directory"
        assert meta["exists"] is True

    def test_path_is_string(self, tmp_path):
        f = tmp_path / "p.txt"
        f.write_text("x")
        meta = entry_metadata(f)
        assert isinstance(meta["path"], str)

    def test_mtime_is_float(self, tmp_path):
        f = tmp_path / "m.txt"
        f.write_text("x")
        meta = entry_metadata(f)
        assert isinstance(meta["mtime"], float)

    def test_nonexistent_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            entry_metadata(tmp_path / "ghost.txt")

    def test_accepts_string_path(self, tmp_path):
        f = tmp_path / "s.txt"
        f.write_text("x")
        meta = entry_metadata(str(f))
        assert meta["type"] == "file"


# ===========================================================================
# save_listing
# ===========================================================================

class TestSaveListing:
    def test_creates_txt_file(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "txt")
        assert out.exists()
        assert out.suffix == ".txt"

    def test_file_is_inside_root(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "txt")
        assert out.parent.resolve() == simple_tree.resolve()

    def test_listing_contains_matched_paths(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "alpha")
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        assert "alpha.txt" in lines[0]

    def test_empty_seed_lists_all_files(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "")
        lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        # Should list all 6 files (alpha, beta, gamma, delta, epsilon, zeta)
        assert len(lines) == 6

    def test_filename_contains_seed(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "log")
        assert "log" in out.name

    def test_filename_for_empty_seed_no_separator(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "")
        # No trailing hyphen — filename is "directory-fl.txt"
        assert out.name == "directory-fl.txt"

    def test_folders_mode_prefix(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FOLDERS, "")
        assert out.name == "directory-fd.txt"

    def test_returns_path_object(self, simple_tree):
        out = save_listing(simple_tree, EntryKind.FILES, "txt")
        assert isinstance(out, Path)

    def test_invalid_path_raises(self, tmp_path):
        with pytest.raises(ValueError):
            save_listing(str(tmp_path / "no_dir"), EntryKind.FILES)

    def test_case_sensitive_listing(self, simple_tree):
        # With case_sensitive=True, ".txt" should not match "zeta.TXT"
        out = save_listing(simple_tree, EntryKind.FILES, ".txt", case_sensitive=True)
        content = out.read_text(encoding="utf-8")
        assert "zeta.TXT" not in content


# ===========================================================================
# remove_entries — safety contract (MUST-ASSERT items 1–4)
# ===========================================================================

class TestRemoveEntriesSafety:

    # MUST-ASSERT 1: blank/whitespace seed -> EmptySeedError
    def test_blank_seed_raises_empty_seed_error(self, file_tree):
        with pytest.raises(EmptySeedError):
            remove_entries(file_tree, EntryKind.FILES, "")

    def test_whitespace_seed_raises_empty_seed_error(self, file_tree):
        with pytest.raises(EmptySeedError):
            remove_entries(file_tree, EntryKind.FILES, "   ")

    def test_tab_seed_raises_empty_seed_error(self, file_tree):
        with pytest.raises(EmptySeedError):
            remove_entries(file_tree, EntryKind.FILES, "\t")

    def test_blank_seed_nothing_deleted(self, file_tree):
        """Files must all still exist after EmptySeedError."""
        before = set(file_tree.rglob("*"))
        with pytest.raises(EmptySeedError):
            remove_entries(file_tree, EntryKind.FILES, "")
        after = set(file_tree.rglob("*"))
        assert before == after

    # MUST-ASSERT 2: dry_run=True (default) deletes nothing
    def test_dry_run_default_returns_preview(self, file_tree):
        report = remove_entries(file_tree, EntryKind.FILES, "delete")
        assert report.dry_run is True
        assert len(report.matched) > 0
        assert len(report.removed) == 0

    def test_dry_run_default_files_still_exist(self, file_tree):
        remove_entries(file_tree, EntryKind.FILES, "delete")
        assert (file_tree / "delete_me.txt").exists()
        assert (file_tree / "delete_also.txt").exists()

    def test_explicit_dry_run_true_nothing_removed(self, file_tree):
        report = remove_entries(file_tree, EntryKind.FILES, "delete",
                                dry_run=True, confirm=False)
        assert report.dry_run is True
        assert report.removed == []
        assert (file_tree / "delete_me.txt").exists()

    # MUST-ASSERT 3: dry_run=False without confirm=True raises ValueError
    def test_dry_run_false_no_confirm_raises(self, file_tree):
        with pytest.raises(ValueError, match="confirm=True"):
            remove_entries(file_tree, EntryKind.FILES, "delete",
                           dry_run=False, confirm=False)

    def test_dry_run_false_no_confirm_nothing_removed(self, file_tree):
        with pytest.raises(ValueError):
            remove_entries(file_tree, EntryKind.FILES, "delete",
                           dry_run=False, confirm=False)
        # Files must still exist
        assert (file_tree / "delete_me.txt").exists()
        assert (file_tree / "delete_also.txt").exists()

    # MUST-ASSERT 4: dry_run=False + confirm=True routes through send2trash
    def test_live_remove_calls_send2trash(self, file_tree):
        """Patch send2trash at the core import site and verify it's called."""
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(
                file_tree, EntryKind.FILES, "delete_me",
                dry_run=False, confirm=True,
            )
        assert mock_trash.called
        called_paths = [c.args[0] for c in mock_trash.call_args_list]
        # All matched paths were sent to trash
        for p in report.matched:
            assert str(p) in called_paths

    def test_live_remove_no_os_remove_called(self, file_tree):
        """When send2trash is available, os.remove must NOT be called."""
        with patch("ff_explorer.core._send2trash"), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True), \
             patch("ff_explorer.core.os.remove") as mock_os_rm:
            remove_entries(file_tree, EntryKind.FILES, "delete_me",
                           dry_run=False, confirm=True)
        mock_os_rm.assert_not_called()

    def test_live_remove_report_contains_removed(self, file_tree):
        with patch("ff_explorer.core._send2trash"), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(
                file_tree, EntryKind.FILES, "delete_me",
                dry_run=False, confirm=True,
            )
        assert len(report.removed) > 0
        assert report.dry_run is False

    def test_live_remove_without_send2trash_uses_os_remove(self, file_tree):
        """Fallback path: when send2trash is unavailable, os.remove is called."""
        with patch("ff_explorer.core._SEND2TRASH_AVAILABLE", False), \
             patch("ff_explorer.core.os.remove") as mock_rm:
            # Create an actual file to match
            target = file_tree / "delete_me.txt"
            report = remove_entries(
                file_tree, EntryKind.FILES, "delete_me",
                dry_run=False, confirm=True,
            )
        # os.remove was called for the matched file
        assert mock_rm.called


class TestRemoveEntriesMatching:
    def test_matched_paths_are_correct(self, file_tree):
        report = remove_entries(file_tree, EntryKind.FILES, "delete")
        names = {p.name for p in report.matched}
        assert "delete_me.txt" in names
        assert "delete_also.txt" in names
        assert "keep_me.txt" not in names

    def test_no_match_empty_matched(self, file_tree):
        report = remove_entries(file_tree, EntryKind.FILES, "zzz_no_match")
        assert report.matched == []
        assert report.removed == []

    # MUST-ASSERT 5: case_sensitive flag
    def test_case_insensitive_matching(self, simple_tree):
        # "ALPHA" matches "alpha.txt" only when case_sensitive=False
        report_sensitive = remove_entries(simple_tree, EntryKind.FILES, "ALPHA",
                                          dry_run=True, case_sensitive=True)
        assert report_sensitive.matched == []

        report_insensitive = remove_entries(simple_tree, EntryKind.FILES, "ALPHA",
                                            dry_run=True, case_sensitive=False)
        names = {p.name for p in report_insensitive.matched}
        assert "alpha.txt" in names

    def test_would_affect_is_alias_for_matched(self, file_tree):
        report = remove_entries(file_tree, EntryKind.FILES, "delete")
        assert report.would_affect is report.matched


# ===========================================================================
# compress_entries — safety contract (mirrors remove_entries)
# ===========================================================================

class TestCompressEntriesSafety:

    # MUST-ASSERT 1: blank/whitespace seed -> EmptySeedError
    def test_blank_seed_raises(self, file_tree):
        with pytest.raises(EmptySeedError):
            compress_entries(file_tree, EntryKind.FILES, "")

    def test_whitespace_seed_raises(self, file_tree):
        with pytest.raises(EmptySeedError):
            compress_entries(file_tree, EntryKind.FILES, "  ")

    def test_blank_seed_nothing_created(self, file_tree):
        before = set(file_tree.rglob("*"))
        with pytest.raises(EmptySeedError):
            compress_entries(file_tree, EntryKind.FILES, "")
        after = set(file_tree.rglob("*"))
        assert before == after

    # MUST-ASSERT 2: dry_run=True (default) creates nothing
    def test_dry_run_default_returns_preview(self, file_tree):
        report = compress_entries(file_tree, EntryKind.FILES, "delete")
        assert report.dry_run is True
        assert len(report.matched) > 0
        assert report.archives == []

    def test_dry_run_default_no_zip_created(self, file_tree):
        compress_entries(file_tree, EntryKind.FILES, "delete")
        zips = list(file_tree.glob("*.zip"))
        assert zips == []

    # MUST-ASSERT 3: dry_run=False without confirm raises ValueError
    def test_dry_run_false_no_confirm_raises(self, file_tree):
        with pytest.raises(ValueError, match="confirm=True"):
            compress_entries(file_tree, EntryKind.FILES, "delete",
                             dry_run=False, confirm=False)

    def test_dry_run_false_no_confirm_nothing_created(self, file_tree):
        with pytest.raises(ValueError):
            compress_entries(file_tree, EntryKind.FILES, "delete",
                             dry_run=False, confirm=False)
        assert list(file_tree.glob("*.zip")) == []


class TestCompressEntriesHappyPath:
    """Live compress (dry_run=False, confirm=True) — FILES mode."""

    def test_files_zip_created(self, file_tree):
        report = compress_entries(
            file_tree, EntryKind.FILES, "delete",
            dry_run=False, confirm=True,
        )
        assert len(report.archives) == 1
        archive = report.archives[0]
        assert archive.name == "Compressed_data.zip"
        assert archive.exists()

    def test_files_zip_contains_matched_entries(self, file_tree):
        report = compress_entries(
            file_tree, EntryKind.FILES, "delete",
            dry_run=False, confirm=True,
        )
        archive = report.archives[0]
        with zipfile.ZipFile(archive) as zf:
            names_in_zip = set(zf.namelist())
        matched_names = {p.name for p in report.matched}
        for name in matched_names:
            assert name in names_in_zip

    def test_files_originals_deleted_after_compress(self, file_tree):
        compress_entries(
            file_tree, EntryKind.FILES, "delete_me",
            dry_run=False, confirm=True,
        )
        assert not (file_tree / "delete_me.txt").exists()

    def test_unmatched_files_preserved(self, file_tree):
        compress_entries(
            file_tree, EntryKind.FILES, "delete",
            dry_run=False, confirm=True,
        )
        assert (file_tree / "keep_me.txt").exists()

    def test_report_dry_run_is_false(self, file_tree):
        report = compress_entries(
            file_tree, EntryKind.FILES, "delete",
            dry_run=False, confirm=True,
        )
        assert report.dry_run is False

    def test_folders_mode_one_zip_per_folder(self, folder_tree):
        report = compress_entries(
            folder_tree, EntryKind.FOLDERS, "archive",
            dry_run=False, confirm=True,
        )
        assert len(report.archives) == 2
        zip_names = {a.name for a in report.archives}
        assert "archive_one.zip" in zip_names
        assert "archive_two.zip" in zip_names

    def test_folders_mode_originals_removed(self, folder_tree):
        compress_entries(
            folder_tree, EntryKind.FOLDERS, "archive",
            dry_run=False, confirm=True,
        )
        assert not (folder_tree / "archive_one").exists()
        assert not (folder_tree / "archive_two").exists()
        # unmatched folder survives
        assert (folder_tree / "other_dir").exists()

    def test_folders_mode_zip_contains_files(self, folder_tree):
        report = compress_entries(
            folder_tree, EntryKind.FOLDERS, "archive_one",
            dry_run=False, confirm=True,
        )
        archive = report.archives[0]
        with zipfile.ZipFile(archive) as zf:
            assert "file_a.txt" in zf.namelist()

    # Case-sensitivity in compress
    def test_case_insensitive_compress_preview(self, file_tree):
        report_sens = compress_entries(file_tree, EntryKind.FILES, "DELETE",
                                       dry_run=True, case_sensitive=True)
        assert report_sens.matched == []

        report_insens = compress_entries(file_tree, EntryKind.FILES, "DELETE",
                                         dry_run=True, case_sensitive=False)
        assert len(report_insens.matched) > 0


# ===========================================================================
# Internal helper coverage (normalise + guard called via public API paths)
# ===========================================================================

class TestInternalGuards:
    def test_normalise_path_rejects_file_as_root(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("x")
        with pytest.raises(ValueError):
            list_entries(f, EntryKind.FILES)

    def test_normalise_path_rejects_nonexistent(self, tmp_path):
        with pytest.raises(ValueError):
            list_entries(tmp_path / "ghost", EntryKind.FILES)

    def test_guard_destructive_seed_empty_string(self, file_tree):
        with pytest.raises(EmptySeedError) as exc_info:
            remove_entries(file_tree, EntryKind.FILES, "")
        assert "remove_entries" in exc_info.value.operation

    def test_guard_destructive_seed_whitespace_compress(self, file_tree):
        with pytest.raises(EmptySeedError) as exc_info:
            compress_entries(file_tree, EntryKind.FILES, "  ")
        assert "compress_entries" in exc_info.value.operation
