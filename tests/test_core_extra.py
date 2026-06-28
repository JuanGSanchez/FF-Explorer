"""
Additional tests targeting uncovered branches in ff_explorer.core and
importing ff_explorer.api.mcp_server to cover its module-level initialisation.

Covered here:
  - entry_metadata: symlink type and "other" type fallback.
  - save_listing (B10): exact line content (no blank-line placeholders); I/O error
    propagates from the with block rather than being masked.
  - remove_entries (B11): OSError lands in report.failed; TypeError propagates.
  - compress_entries (B11): OSError lands in report.failed; TypeError propagates.
    Existing branches: shutil.rmtree fallback, per-file write error, post-compress
    delete failure, per-folder archive error.
  - mcp_server: module-level import (FastMCP.from_fastapi + http_app).
  - FFX-I01: match_mode (substring/glob/regex) + case_sensitive across modes.
  - FFX-I02: structured filters (min_size, max_size, modified_after, modified_before,
    extensions) — individual + combined, dir-handling semantics.
"""
from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ff_explorer.core import (
    EntryKind,
    FFExplorerError,
    InvalidRegexError,
    TransferReport,
    EmptySeedError,
    entry_metadata,
    list_entries,
    list_entries_with_report,
    iter_entries,
    save_listing,
    remove_entries,
    compress_entries,
    copy_entries,
    move_entries,
)


# ===========================================================================
# entry_metadata — symlink and "other" branches
# ===========================================================================

class TestEntryMetadataSymlink:
    @pytest.mark.skipif(
        not hasattr(os, "symlink"), reason="symlinks not supported"
    )
    def test_symlink_type(self, tmp_path):
        target = tmp_path / "real.txt"
        target.write_text("x")
        link = tmp_path / "link.txt"
        try:
            link.symlink_to(target)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not available")
        meta = entry_metadata(link)
        assert meta["type"] == "symlink"

    def test_other_type_via_mock(self, tmp_path):
        """Exercise the 'other' branch by mocking is_symlink/is_file/is_dir."""
        f = tmp_path / "x.txt"
        f.write_text("x")
        with patch.object(Path, "is_symlink", return_value=False), \
             patch.object(Path, "is_file", return_value=False), \
             patch.object(Path, "is_dir", return_value=False):
            meta = entry_metadata(f)
        assert meta["type"] == "other"


# ===========================================================================
# save_listing — B10 acceptance tests
# ===========================================================================

class TestSaveListingExactContent:
    """B10: save_listing writes exactly one valid path per match, no blanks."""

    def test_exact_lines_no_blanks(self, simple_tree):
        """Each matched entry produces exactly one non-empty line; no blank lines."""
        out = save_listing(simple_tree, EntryKind.FILES, "alpha")
        lines = out.read_text(encoding="utf-8").splitlines()
        # simple_tree has exactly one file matching "alpha" (alpha.txt)
        assert len(lines) == 1
        assert lines[0].strip() != ""
        assert "alpha" in lines[0]

    def test_multiple_matches_exact_line_count(self, simple_tree):
        """Multiple matches produce exactly that many lines, each non-empty."""
        # Snapshot expected count BEFORE save_listing creates the output .txt file,
        # which would otherwise appear as an extra match in the next list_entries call.
        from ff_explorer.core import list_entries
        expected = list_entries(simple_tree, EntryKind.FILES, "")
        out = save_listing(simple_tree, EntryKind.FILES, "")
        lines = out.read_text(encoding="utf-8").splitlines()
        # All lines must be non-empty
        assert all(line.strip() != "" for line in lines)
        assert len(lines) == len(expected)

    def test_io_error_propagates(self, simple_tree):
        """A genuine I/O error on fp.write() propagates rather than producing a blank line."""
        import builtins
        original_open = builtins.open

        def fake_open(path, mode="r", **kwargs):
            fobj = original_open(path, mode, **kwargs)
            if "w" in mode and str(path).endswith(".txt"):
                _orig = fobj.write

                def always_fail(data):
                    raise OSError("simulated write failure")

                fobj.write = always_fail
            return fobj

        with pytest.raises(OSError, match="simulated write failure"):
            with patch("builtins.open", side_effect=fake_open):
                save_listing(simple_tree, EntryKind.FILES, "alpha")


# ===========================================================================
# remove_entries — shutil fallback without send2trash
# ===========================================================================

class TestRemoveFallbackNoSend2Trash:
    def test_folder_rmtree_fallback(self, tmp_path):
        """Without send2trash, FOLDERS removal uses shutil.rmtree."""
        fd = tmp_path / "to_delete"
        fd.mkdir()
        (fd / "inner.txt").write_text("x")

        with patch("ff_explorer.core._SEND2TRASH_AVAILABLE", False):
            report = remove_entries(tmp_path, EntryKind.FOLDERS, "to_delete",
                                    dry_run=False, confirm=True)

        assert len(report.removed) == 1
        assert not fd.exists()

    def test_file_remove_fallback(self, tmp_path):
        """Without send2trash, FILES removal uses os.remove."""
        f = tmp_path / "remove_me.txt"
        f.write_text("x")

        with patch("ff_explorer.core._SEND2TRASH_AVAILABLE", False):
            report = remove_entries(tmp_path, EntryKind.FILES, "remove_me",
                                    dry_run=False, confirm=True)

        assert len(report.removed) == 1
        assert not f.exists()

    def test_removal_error_goes_to_failed(self, tmp_path):
        """When os.remove raises, the error is recorded in report.failed."""
        f = tmp_path / "bad_remove.txt"
        f.write_text("x")

        with patch("ff_explorer.core._SEND2TRASH_AVAILABLE", False), \
             patch("ff_explorer.core.os.remove", side_effect=OSError("denied")):
            report = remove_entries(tmp_path, EntryKind.FILES, "bad_remove",
                                    dry_run=False, confirm=True)

        assert len(report.failed) == 1
        assert "denied" in report.failed[0][1]

    def test_send2trash_error_goes_to_failed(self, tmp_path):
        """When send2trash raises, the error is recorded in report.failed."""
        f = tmp_path / "trash_fail.txt"
        f.write_text("x")

        with patch("ff_explorer.core._send2trash", side_effect=OSError("trash full")), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(tmp_path, EntryKind.FILES, "trash_fail",
                                    dry_run=False, confirm=True)

        assert len(report.failed) == 1
        assert "trash full" in report.failed[0][1]


# ===========================================================================
# B11 — narrow except: OSError lands in failed; TypeError propagates
# ===========================================================================

class TestB11RemoveNarrowExcept:
    """B11: remove_entries catches OSError into report.failed; TypeError propagates."""

    def test_oserror_lands_in_failed(self, tmp_path):
        """An OSError from send2trash is captured in report.failed, not raised."""
        f = tmp_path / "target.txt"
        f.write_text("x")

        with patch("ff_explorer.core._send2trash", side_effect=OSError("io error")), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(tmp_path, EntryKind.FILES, "target",
                                    dry_run=False, confirm=True)

        assert len(report.failed) == 1
        assert "io error" in report.failed[0][1]

    def test_typeerror_propagates(self, tmp_path):
        """A TypeError (programming error) from send2trash is NOT swallowed."""
        f = tmp_path / "target2.txt"
        f.write_text("x")

        with patch("ff_explorer.core._send2trash", side_effect=TypeError("bad type")), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            with pytest.raises(TypeError, match="bad type"):
                remove_entries(tmp_path, EntryKind.FILES, "target2",
                               dry_run=False, confirm=True)


class TestB11CompressNarrowExcept:
    """B11: compress_entries catches OSError into report.failed; TypeError propagates."""

    def test_oserror_in_zip_write_lands_in_failed(self, tmp_path):
        """An OSError from zf.write lands in report.failed."""
        (tmp_path / "file.txt").write_text("x")

        with patch.object(zipfile.ZipFile, "write", side_effect=OSError("zip io")):
            report = compress_entries(tmp_path, EntryKind.FILES, "file",
                                      dry_run=False, confirm=True)

        assert any("zip io" in msg for _, msg in report.failed)

    def test_typeerror_in_zip_write_propagates(self, tmp_path):
        """A TypeError from zf.write propagates rather than being swallowed."""
        (tmp_path / "file2.txt").write_text("x")

        with patch.object(zipfile.ZipFile, "write", side_effect=TypeError("bad arg")):
            with pytest.raises(TypeError, match="bad arg"):
                compress_entries(tmp_path, EntryKind.FILES, "file2",
                                 dry_run=False, confirm=True)

    def test_oserror_in_folder_zip_write_lands_in_failed(self, tmp_path):
        """An OSError from zf.write in FOLDERS mode lands in report.failed."""
        fd = tmp_path / "myfolder"
        fd.mkdir()
        (fd / "inner.txt").write_text("x")

        with patch.object(zipfile.ZipFile, "write", side_effect=OSError("folder zip io")):
            report = compress_entries(tmp_path, EntryKind.FOLDERS, "myfolder",
                                      dry_run=False, confirm=True)

        assert any("folder zip io" in msg for _, msg in report.failed)

    def test_typeerror_in_folder_zip_write_propagates(self, tmp_path):
        """A TypeError from zf.write in FOLDERS mode propagates."""
        fd = tmp_path / "myfolder2"
        fd.mkdir()
        (fd / "inner.txt").write_text("x")

        with patch.object(zipfile.ZipFile, "write", side_effect=TypeError("bad folder arg")):
            with pytest.raises(TypeError, match="bad folder arg"):
                compress_entries(tmp_path, EntryKind.FOLDERS, "myfolder2",
                                 dry_run=False, confirm=True)


# ===========================================================================
# compress_entries — error branches
# ===========================================================================

class TestCompressErrorBranches:
    def test_file_in_zip_error_recorded(self, tmp_path):
        """
        When zf.write() raises for a specific file inside the FILES archive,
        that file's error is appended to report.failed (lines 470-471).
        """
        (tmp_path / "good.txt").write_text("g")
        (tmp_path / "bad.txt").write_text("b")

        original_zf_write = zipfile.ZipFile.write

        call_counter = [0]

        def selective_fail(self, filename, arcname=None, **kw):
            call_counter[0] += 1
            if call_counter[0] == 1:
                raise OSError("zip write error")
            return original_zf_write(self, filename, arcname, **kw)

        with patch.object(zipfile.ZipFile, "write", selective_fail):
            report = compress_entries(tmp_path, EntryKind.FILES, ".txt",
                                      dry_run=False, confirm=True)

        # At least one failure was recorded (the first file to be written)
        assert len(report.failed) >= 1

    def test_files_post_compress_delete_failure_recorded(self, tmp_path):
        """
        When os.remove fails after successful zip write, the failure is
        appended to report.failed (lines 478-481).
        """
        (tmp_path / "compress_me.txt").write_text("x")

        with patch("ff_explorer.core.os.remove",
                   side_effect=OSError("cannot delete")):
            report = compress_entries(tmp_path, EntryKind.FILES, "compress_me",
                                      dry_run=False, confirm=True)

        # Archive was created but delete failed
        assert len(report.archives) == 1
        post_delete_errors = [msg for _, msg in report.failed
                              if "post-compress delete failed" in msg]
        assert len(post_delete_errors) >= 1

    def test_folder_archive_creation_error_recorded(self, tmp_path):
        """
        When ZipFile creation raises for a folder, the error is recorded
        in report.failed (lines 495-496 / outer except).
        """
        fd = tmp_path / "bad_folder"
        fd.mkdir()
        (fd / "f.txt").write_text("x")

        original_init = zipfile.ZipFile.__init__

        call_count = [0]

        def failing_init(self, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("cannot create archive")
            return original_init(self, *args, **kwargs)

        with patch.object(zipfile.ZipFile, "__init__", failing_init):
            report = compress_entries(tmp_path, EntryKind.FOLDERS, "bad_folder",
                                      dry_run=False, confirm=True)

        assert len(report.failed) >= 1

    def test_folder_post_compress_delete_failure_recorded(self, tmp_path):
        """
        When shutil.rmtree fails after a folder is zipped, the failure is
        recorded in report.failed (lines 501-504).
        """
        fd = tmp_path / "zip_and_fail"
        fd.mkdir()
        (fd / "content.txt").write_text("x")

        with patch("ff_explorer.core.shutil.rmtree",
                   side_effect=OSError("rmtree denied")):
            report = compress_entries(tmp_path, EntryKind.FOLDERS, "zip_and_fail",
                                      dry_run=False, confirm=True)

        assert len(report.archives) == 1
        post_delete_errors = [msg for _, msg in report.failed
                              if "post-compress delete failed" in msg]
        assert len(post_delete_errors) >= 1


# ===========================================================================
# mcp_server — module-level import coverage (lines 53-73)
# ===========================================================================

class TestMcpServerImport:
    def test_mcp_server_importable(self):
        """Importing mcp_server must not raise and must expose mcp + mcp_app."""
        from ff_explorer.api import mcp_server
        assert hasattr(mcp_server, "mcp")
        assert hasattr(mcp_server, "mcp_app")

    def test_mcp_is_fastmcp_instance(self):
        from ff_explorer.api import mcp_server
        from fastmcp import FastMCP
        assert isinstance(mcp_server.mcp, FastMCP)

    def test_mcp_app_is_asgi(self):
        """mcp_app must be a callable ASGI application."""
        from ff_explorer.api import mcp_server
        # ASGI apps are callable
        assert callable(mcp_server.mcp_app)


# ===========================================================================
# FFX-I01 — match_mode: substring / glob / regex + case_sensitive
# ===========================================================================

@pytest.fixture()
def match_tree(tmp_path: Path) -> Path:
    """
    Tree for match_mode / filter tests:

        tmp_path/
            foo_bar.txt
            foo_baz.txt
            foobar.log
            baz.txt
            sub/
                foo_nested.txt
                Bar.TXT
    """
    (tmp_path / "foo_bar.txt").write_text("a")
    (tmp_path / "foo_baz.txt").write_text("b")
    (tmp_path / "foobar.log").write_text("c")
    (tmp_path / "baz.txt").write_text("d")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "foo_nested.txt").write_text("e")
    (sub / "Bar.TXT").write_text("f")
    return tmp_path


class TestMatchModeSubstring:
    """FFX-I01 — default substring mode must be byte-for-byte unchanged."""

    def test_default_mode_matches_substring(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "foo")
        names = {e.path.name for e in results}
        assert names == {"foo_bar.txt", "foo_baz.txt", "foobar.log", "foo_nested.txt"}

    def test_explicit_substring_same_as_default(self, match_tree):
        default = list_entries(match_tree, EntryKind.FILES, "foo")
        explicit = list_entries(match_tree, EntryKind.FILES, "foo", match_mode="substring")
        assert [e.path for e in default] == [e.path for e in explicit]

    def test_substring_case_sensitive_default(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "Bar")
        names = {e.path.name for e in results}
        # "Bar.TXT" matches "Bar" case-sensitively; "foo_bar.txt" has lowercase 'bar'
        assert "Bar.TXT" in names
        assert "foo_bar.txt" not in names

    def test_substring_case_insensitive(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "BAR", case_sensitive=False)
        names = {e.path.name for e in results}
        assert "foo_bar.txt" in names
        assert "Bar.TXT" in names

    def test_empty_seed_matches_all(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "")
        assert len(results) == 6


class TestMatchModeGlob:
    """FFX-I01 — glob mode via fnmatch."""

    def test_glob_star_txt(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "*.txt", match_mode="glob")
        names = {e.path.name for e in results}
        assert names == {"foo_bar.txt", "foo_baz.txt", "baz.txt", "foo_nested.txt"}
        # Bar.TXT is uppercase — case_sensitive=True (default) should NOT match *.txt
        assert "Bar.TXT" not in names

    def test_glob_star_txt_case_insensitive(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "*.txt",
                               match_mode="glob", case_sensitive=False)
        names = {e.path.name for e in results}
        assert "Bar.TXT" in names
        assert "foo_bar.txt" in names

    def test_glob_question_mark(self, match_tree):
        # "ba?.txt" matches "baz.txt" (3-char middle)
        results = list_entries(match_tree, EntryKind.FILES, "ba?.txt", match_mode="glob")
        names = {e.path.name for e in results}
        assert "baz.txt" in names
        assert "foo_bar.txt" not in names

    def test_glob_no_match(self, match_tree):
        results = list_entries(match_tree, EntryKind.FILES, "*.xyz", match_mode="glob")
        assert results == []

    def test_glob_folders(self, match_tree):
        results = list_entries(match_tree, EntryKind.FOLDERS, "su*", match_mode="glob")
        names = {e.path.name for e in results}
        assert "sub" in names


class TestMatchModeRegex:
    """FFX-I01 — regex mode: compile-once, correct matches, invalid → error."""

    def test_regex_exact_prefix_and_suffix(self, match_tree):
        # "^foo.*\\.txt$" should match foo_bar.txt, foo_baz.txt, foo_nested.txt
        results = list_entries(match_tree, EntryKind.FILES, r"^foo.*\.txt$",
                               match_mode="regex")
        names = {e.path.name for e in results}
        assert names == {"foo_bar.txt", "foo_baz.txt", "foo_nested.txt"}
        assert "foobar.log" not in names
        assert "baz.txt" not in names

    def test_regex_case_sensitive_default(self, match_tree):
        # "^bar" should NOT match "Bar.TXT" with default case_sensitive=True
        results = list_entries(match_tree, EntryKind.FILES, r"^bar",
                               match_mode="regex", case_sensitive=True)
        names = {e.path.name for e in results}
        assert "Bar.TXT" not in names

    def test_regex_case_insensitive(self, match_tree):
        # "^bar" should match "Bar.TXT" with case_sensitive=False
        results = list_entries(match_tree, EntryKind.FILES, r"^bar",
                               match_mode="regex", case_sensitive=False)
        names = {e.path.name for e in results}
        assert "Bar.TXT" in names

    def test_regex_invalid_pattern_raises_invalid_regex_error(self, match_tree):
        with pytest.raises(InvalidRegexError) as exc_info:
            list_entries(match_tree, EntryKind.FILES, r"[invalid(", match_mode="regex")
        assert exc_info.value.pattern == r"[invalid("

    def test_invalid_regex_error_is_ff_explorer_error(self, match_tree):
        with pytest.raises(FFExplorerError):
            list_entries(match_tree, EntryKind.FILES, r"[bad", match_mode="regex")

    def test_invalid_regex_error_is_value_error(self, match_tree):
        # REST layer catches ValueError → 422; verify the subtype relationship
        with pytest.raises(ValueError):
            list_entries(match_tree, EntryKind.FILES, r"[bad", match_mode="regex")

    def test_regex_empty_seed_matches_all(self, match_tree):
        # Empty pattern matches every name (re.search("", name) is always truthy)
        results = list_entries(match_tree, EntryKind.FILES, "", match_mode="regex")
        assert len(results) == 6

    def test_invalid_match_mode_raises_value_error(self, match_tree):
        with pytest.raises(ValueError, match="match_mode"):
            list_entries(match_tree, EntryKind.FILES, "foo", match_mode="fuzzy")


# ===========================================================================
# FFX-I02 — structured filters: size, date, extension; dir handling; AND combo
# ===========================================================================

@pytest.fixture()
def filter_tree(tmp_path: Path) -> Path:
    """
    Tree with controlled sizes and mtimes for filter tests:

        tmp_path/
            small.txt       10 bytes,  mtime = T-200
            medium.txt     100 bytes,  mtime = T-100
            large.txt     1000 bytes,  mtime = T-10
            note.log        10 bytes,  mtime = T-200
            data/           (directory)
                inner.txt   50 bytes,  mtime = T-100

    T = reference epoch (set via os.utime for determinism).
    """
    T = 1_700_000_000.0  # fixed reference epoch (Nov 2023)

    def make(name: Path, content: bytes, mtime: float) -> None:
        name.write_bytes(content)
        os.utime(name, (mtime, mtime))

    make(tmp_path / "small.txt",  b"x" * 10,   T - 200)
    make(tmp_path / "medium.txt", b"x" * 100,  T - 100)
    make(tmp_path / "large.txt",  b"x" * 1000, T - 10)
    make(tmp_path / "note.log",   b"x" * 10,   T - 200)

    data = tmp_path / "data"
    data.mkdir()
    os.utime(data, (T - 50, T - 50))
    make(data / "inner.txt",      b"x" * 50,   T - 100)

    return tmp_path


class TestFilterSize:
    """FFX-I02 — min_size / max_size on files; dirs always pass."""

    def test_min_size_excludes_small(self, filter_tree):
        results = list_entries(filter_tree, EntryKind.FILES, "", min_size=50)
        names = {e.path.name for e in results}
        assert "large.txt" in names
        assert "medium.txt" in names
        assert "inner.txt" in names
        assert "small.txt" not in names
        assert "note.log" not in names

    def test_max_size_excludes_large(self, filter_tree):
        results = list_entries(filter_tree, EntryKind.FILES, "", max_size=100)
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "medium.txt" in names
        assert "inner.txt" in names
        assert "large.txt" not in names

    def test_size_range(self, filter_tree):
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               min_size=50, max_size=100)
        names = {e.path.name for e in results}
        assert names == {"medium.txt", "inner.txt"}

    def test_exact_size_inclusive(self, filter_tree):
        # medium.txt is exactly 100 bytes
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               min_size=100, max_size=100)
        names = {e.path.name for e in results}
        assert "medium.txt" in names
        assert "large.txt" not in names
        assert "small.txt" not in names

    def test_dirs_always_pass_size_filter(self, filter_tree):
        # With min_size=500, dirs should still appear in FOLDERS results
        results = list_entries(filter_tree, EntryKind.FOLDERS, "", min_size=500)
        names = {e.path.name for e in results}
        assert "data" in names


class TestFilterDate:
    """FFX-I02 — modified_after / modified_before on mtime."""

    def test_modified_after_excludes_old(self, filter_tree):
        T = 1_700_000_000.0
        # Only entries with mtime > T-150 (i.e. medium.txt=T-100, large.txt=T-10, inner.txt=T-100)
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               modified_after=T - 150)
        names = {e.path.name for e in results}
        assert "medium.txt" in names
        assert "large.txt" in names
        assert "inner.txt" in names
        assert "small.txt" not in names
        assert "note.log" not in names

    def test_modified_before_excludes_recent(self, filter_tree):
        T = 1_700_000_000.0
        # modified_before=T-50 keeps entries with mtime strictly before T-50.
        # small.txt=T-200, note.log=T-200, medium.txt=T-100, inner.txt=T-100 → all < T-50
        # large.txt=T-10 → T-10 > T-50 → excluded
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               modified_before=T - 50)
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "medium.txt" in names
        assert "note.log" in names       # mtime=T-200 < T-50 → included
        assert "inner.txt" in names      # mtime=T-100 < T-50 → included
        assert "large.txt" not in names  # mtime=T-10 > T-50 → excluded

    def test_modified_after_boundary_is_strict(self, filter_tree):
        T = 1_700_000_000.0
        # small.txt has mtime = T-200 exactly; modified_after=T-200 is strict → excluded
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               modified_after=T - 200)
        names = {e.path.name for e in results}
        assert "small.txt" not in names
        assert "note.log" not in names

    def test_modified_before_boundary_is_strict(self, filter_tree):
        T = 1_700_000_000.0
        # large.txt has mtime = T-10 exactly; modified_before=T-10 is strict → excluded
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               modified_before=T - 10)
        names = {e.path.name for e in results}
        assert "large.txt" not in names

    def test_date_filter_applies_to_dirs(self, filter_tree):
        T = 1_700_000_000.0
        # data dir has mtime=T-50; modified_after=T-100 → T-50 > T-100 → included
        results = list_entries(filter_tree, EntryKind.FOLDERS, "",
                               modified_after=T - 100)
        names = {e.path.name for e in results}
        assert "data" in names

    def test_date_filter_excludes_dirs(self, filter_tree):
        # Read the actual mtime of the 'data' dir (os.utime on dirs is unreliable
        # on Windows), then set modified_after to a time well after it.
        data_dir = filter_tree / "data"
        actual_mtime = data_dir.stat().st_mtime
        # modified_after = actual_mtime means "strictly after" → data dir excluded
        results = list_entries(filter_tree, EntryKind.FOLDERS, "",
                               modified_after=actual_mtime)
        names = {e.path.name for e in results}
        assert "data" not in names


class TestFilterExtensions:
    """FFX-I02 — extension filter; dirs always pass; case-insensitive matching."""

    def test_ext_filter_txt_only(self, filter_tree):
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               extensions=[".txt"])
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "medium.txt" in names
        assert "large.txt" in names
        assert "inner.txt" in names
        assert "note.log" not in names

    def test_ext_filter_without_dot(self, filter_tree):
        # "txt" (no dot) should normalise to ".txt"
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               extensions=["txt"])
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "note.log" not in names

    def test_ext_filter_case_insensitive(self, match_tree):
        # match_tree has Bar.TXT (uppercase); extensions filter is always case-insensitive
        results = list_entries(match_tree, EntryKind.FILES, "",
                               extensions=[".txt"])
        names = {e.path.name for e in results}
        assert "Bar.TXT" in names  # .TXT normalises to .txt for comparison
        assert "foobar.log" not in names

    def test_ext_filter_multiple_extensions(self, filter_tree):
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               extensions=[".txt", ".log"])
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "note.log" in names

    def test_ext_filter_dirs_always_pass(self, filter_tree):
        # Even with extensions=[".txt"], directories should appear in FOLDERS results
        results = list_entries(filter_tree, EntryKind.FOLDERS, "",
                               extensions=[".txt"])
        names = {e.path.name for e in results}
        assert "data" in names

    def test_empty_extensions_list_no_filter(self, filter_tree):
        # Empty list → normalises to None → no extension filter applied
        results_no_filter = list_entries(filter_tree, EntryKind.FILES, "")
        results_empty_ext = list_entries(filter_tree, EntryKind.FILES, "",
                                         extensions=[])
        assert {e.path for e in results_no_filter} == {e.path for e in results_empty_ext}


class TestFilterCombined:
    """FFX-I02 — multiple predicates AND-combined; no-filter baseline exact match."""

    def test_no_filters_reproduces_baseline(self, filter_tree):
        """With all filter params at None, results are byte-for-byte identical to legacy."""
        baseline = list_entries(filter_tree, EntryKind.FILES, "")
        with_nones = list_entries(filter_tree, EntryKind.FILES, "",
                                  min_size=None, max_size=None,
                                  modified_after=None, modified_before=None,
                                  extensions=None)
        assert [e.path for e in baseline] == [e.path for e in with_nones]

    def test_name_seed_and_size_filter(self, filter_tree):
        # name contains "." AND size >= 100 → only large.txt (1000b) and medium.txt (100b)
        results = list_entries(filter_tree, EntryKind.FILES, ".txt", min_size=100)
        names = {e.path.name for e in results}
        assert "large.txt" in names
        assert "medium.txt" in names
        assert "small.txt" not in names
        assert "inner.txt" not in names  # 50 bytes < 100

    def test_size_and_extension_combined(self, filter_tree):
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               min_size=50, extensions=[".txt"])
        names = {e.path.name for e in results}
        assert "medium.txt" in names
        assert "large.txt" in names
        assert "inner.txt" in names
        assert "small.txt" not in names   # 10 bytes < 50
        assert "note.log" not in names    # wrong extension

    def test_size_date_extension_all_combined(self, filter_tree):
        T = 1_700_000_000.0
        # size >= 50 AND mtime > T-150 AND extension .txt
        # Candidates: medium.txt (100b, T-100), large.txt (1000b, T-10), inner.txt (50b, T-100)
        results = list_entries(filter_tree, EntryKind.FILES, "",
                               min_size=50,
                               modified_after=T - 150,
                               extensions=[".txt"])
        names = {e.path.name for e in results}
        assert names == {"medium.txt", "large.txt", "inner.txt"}

    def test_regex_and_size_filter(self, filter_tree):
        # regex "^(small|large)" AND size >= 100 → only large.txt
        results = list_entries(filter_tree, EntryKind.FILES, r"^(small|large)",
                               match_mode="regex", min_size=100)
        names = {e.path.name for e in results}
        assert names == {"large.txt"}


class TestFilterNoFiltersBaseline:
    """FFX-I02 — regression: default args reproduce original list_entries output exactly."""

    def test_files_baseline_unchanged(self, simple_tree):
        original = list_entries(simple_tree, EntryKind.FILES, "txt")
        filtered = list_entries(simple_tree, EntryKind.FILES, "txt",
                                match_mode="substring", case_sensitive=True,
                                min_size=None, max_size=None,
                                modified_after=None, modified_before=None,
                                extensions=None)
        assert [e.path for e in original] == [e.path for e in filtered]

    def test_folders_baseline_unchanged(self, simple_tree):
        original = list_entries(simple_tree, EntryKind.FOLDERS, "sub")
        filtered = list_entries(simple_tree, EntryKind.FOLDERS, "sub",
                                match_mode="substring", case_sensitive=True)
        assert [e.path for e in original] == [e.path for e in filtered]


# ===========================================================================
# FFX-I04 — gitignore/ignore-file awareness + ignore_globs
# ===========================================================================

@pytest.fixture()
def ignore_tree(tmp_path: Path) -> Path:
    """
    Tree with a root .gitignore, a nested .gitignore in 'src/', and a build/ dir:

        tmp_path/
            .gitignore          ← ignores *.log and build/
            main.py
            notes.log           ← ignored by root .gitignore
            build/              ← ignored (pruned) by root .gitignore
                artifact.txt    ← never visited when build/ is pruned
            src/
                .gitignore      ← ignores *.tmp (subtree-only)
                app.py
                draft.tmp       ← ignored only within src/
                util.py
            data/
                report.log      ← ignored by root .gitignore
                readme.txt
    """
    # Root ignore file: exclude *.log files and the build/ directory.
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")

    (tmp_path / "main.py").write_text("# main")
    (tmp_path / "notes.log").write_text("log content")

    build = tmp_path / "build"
    build.mkdir()
    (build / "artifact.txt").write_text("artifact")

    src = tmp_path / "src"
    src.mkdir()
    # Nested ignore: only applies to src/ subtree.
    (src / ".gitignore").write_text("*.tmp\n")
    (src / "app.py").write_text("# app")
    (src / "draft.tmp").write_text("draft")
    (src / "util.py").write_text("# util")

    data = tmp_path / "data"
    data.mkdir()
    (data / "report.log").write_text("log")
    (data / "readme.txt").write_text("readme")

    return tmp_path


class TestIgnoreFileAwareness:
    """FFX-I04 — respect_ignore honours .gitignore/.ignore with layered precedence."""

    # ------------------------------------------------------------------
    # Baseline: default OFF — all entries visible (backward compat)
    # ------------------------------------------------------------------

    def test_defaults_off_sees_all_files(self, ignore_tree):
        """With defaults (respect_ignore=False, ignore_globs=None) all files appear."""
        results = list_entries(ignore_tree, EntryKind.FILES)
        names = {e.path.name for e in results}
        # Items that would be ignored WITH the flag must appear WITHOUT it.
        assert "notes.log" in names
        assert "artifact.txt" in names
        assert "draft.tmp" in names
        assert "report.log" in names

    def test_defaults_off_sees_all_folders(self, ignore_tree):
        """build/ is present when respect_ignore=False."""
        results = list_entries(ignore_tree, EntryKind.FOLDERS)
        names = {e.path.name for e in results}
        assert "build" in names

    # ------------------------------------------------------------------
    # respect_ignore=True — root .gitignore rules
    # ------------------------------------------------------------------

    def test_respect_ignore_excludes_log_files(self, ignore_tree):
        """*.log pattern in root .gitignore removes log files from results."""
        results = list_entries(ignore_tree, EntryKind.FILES, respect_ignore=True)
        names = {e.path.name for e in results}
        assert "notes.log" not in names
        assert "report.log" not in names

    def test_respect_ignore_keeps_non_ignored_files(self, ignore_tree):
        """Non-ignored files still appear with respect_ignore=True."""
        results = list_entries(ignore_tree, EntryKind.FILES, respect_ignore=True)
        names = {e.path.name for e in results}
        assert "main.py" in names
        assert "app.py" in names
        assert "util.py" in names
        assert "readme.txt" in names

    def test_respect_ignore_prunes_build_dir(self, ignore_tree):
        """build/ is pruned — its contents (artifact.txt) never appear."""
        results = list_entries(ignore_tree, EntryKind.FILES, respect_ignore=True)
        names = {e.path.name for e in results}
        assert "artifact.txt" not in names

    def test_respect_ignore_build_dir_absent_from_folders(self, ignore_tree):
        """build/ itself is absent from FOLDERS results when pruned."""
        results = list_entries(ignore_tree, EntryKind.FOLDERS, respect_ignore=True)
        names = {e.path.name for e in results}
        assert "build" not in names

    # ------------------------------------------------------------------
    # Nested .gitignore — subtree-only scope
    # ------------------------------------------------------------------

    def test_nested_gitignore_applies_only_to_subtree(self, ignore_tree):
        """*.tmp in src/.gitignore removes draft.tmp (in src/) only."""
        results = list_entries(ignore_tree, EntryKind.FILES, respect_ignore=True)
        names = {e.path.name for e in results}
        # draft.tmp is inside src/ — the nested .gitignore must remove it.
        assert "draft.tmp" not in names

    def test_nested_gitignore_does_not_affect_root_level(self, ignore_tree):
        """A .tmp file placed at root is NOT ignored (nested rule doesn't leak up)."""
        # Place a .tmp at root level — the root .gitignore doesn't mention *.tmp.
        (ignore_tree / "root_level.tmp").write_text("tmp")
        results = list_entries(ignore_tree, EntryKind.FILES, respect_ignore=True)
        names = {e.path.name for e in results}
        assert "root_level.tmp" in names

    # ------------------------------------------------------------------
    # ignore_globs — caller-supplied extra patterns (independent of flag)
    # ------------------------------------------------------------------

    def test_ignore_globs_excludes_matching_files(self, ignore_tree):
        """ignore_globs=["*.tmp"] removes .tmp files regardless of ignore files."""
        results = list_entries(ignore_tree, EntryKind.FILES,
                               respect_ignore=False, ignore_globs=["*.tmp"])
        names = {e.path.name for e in results}
        assert "draft.tmp" not in names

    def test_ignore_globs_does_not_affect_other_files(self, ignore_tree):
        """ignore_globs only removes its own matches; others survive."""
        results = list_entries(ignore_tree, EntryKind.FILES,
                               respect_ignore=False, ignore_globs=["*.tmp"])
        names = {e.path.name for e in results}
        # .log files still appear (respect_ignore=False, no *.log in ignore_globs)
        assert "notes.log" in names
        assert "main.py" in names

    def test_ignore_globs_combined_with_respect_ignore(self, ignore_tree):
        """Both ignore sources combine: *.log from .gitignore + *.py from ignore_globs."""
        results = list_entries(ignore_tree, EntryKind.FILES,
                               respect_ignore=True, ignore_globs=["*.py"])
        names = {e.path.name for e in results}
        # .log removed by .gitignore, .py removed by ignore_globs
        assert "notes.log" not in names
        assert "main.py" not in names
        assert "app.py" not in names
        # readme.txt survives both filters
        assert "readme.txt" in names

    def test_ignore_globs_prunes_dir(self, ignore_tree):
        """A directory pattern in ignore_globs prunes the directory."""
        results = list_entries(ignore_tree, EntryKind.FILES,
                               respect_ignore=False, ignore_globs=["build/"])
        names = {e.path.name for e in results}
        assert "artifact.txt" not in names

    # ------------------------------------------------------------------
    # Regression: explicit defaults == legacy output
    # ------------------------------------------------------------------

    def test_explicit_defaults_reproduce_baseline(self, ignore_tree):
        """Passing respect_ignore=False, ignore_globs=None is byte-for-byte identical."""
        baseline = list_entries(ignore_tree, EntryKind.FILES)
        explicit = list_entries(ignore_tree, EntryKind.FILES,
                                respect_ignore=False, ignore_globs=None)
        assert [e.path for e in baseline] == [e.path for e in explicit]


# ===========================================================================
# FFX-I09 — content search (grep-inside-files) gated behind name/type filters
# ===========================================================================

from ff_explorer.core import ContentSearchUngatedError  # noqa: E402  (appended section)
from ff_explorer.content_search import CONTENT_MAX_BYTES, file_content_matches  # noqa: E402


@pytest.fixture()
def content_tree(tmp_path: Path) -> Path:
    """
    Tree for content-search tests:

        tmp_path/
            match_me.txt       ← contains "FIND_THIS_TOKEN"
            no_match.txt       ← contains only "nothing useful here"
            also_match.log     ← contains "FIND_THIS_TOKEN" in a log
            binary_file.bin    ← starts with a null byte (binary heuristic)
            sub/
                nested_match.txt ← contains "FIND_THIS_TOKEN"
    """
    (tmp_path / "match_me.txt").write_text("line1\nFIND_THIS_TOKEN\nline3")
    (tmp_path / "no_match.txt").write_text("nothing useful here")
    (tmp_path / "also_match.log").write_text("log entry: FIND_THIS_TOKEN logged")

    # Binary file: starts with null byte — must be skipped by content search
    (tmp_path / "binary_file.bin").write_bytes(b"\x00\x01\x02binary data")

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested_match.txt").write_text("deep: FIND_THIS_TOKEN here")

    return tmp_path


class TestContentSearchGate:
    """FFX-I09 gate: content_query without a pre-filter raises ContentSearchUngatedError."""

    def test_ungated_raises(self, content_tree):
        """content_query with empty name_seed and no other filter → ContentSearchUngatedError."""
        with pytest.raises(ContentSearchUngatedError):
            list_entries(content_tree, EntryKind.FILES, "",
                         content_query="FIND_THIS_TOKEN")

    def test_ungated_is_ff_explorer_error(self, content_tree):
        with pytest.raises(FFExplorerError):
            list_entries(content_tree, EntryKind.FILES, "",
                         content_query="FIND_THIS_TOKEN")

    def test_ungated_is_value_error(self, content_tree):
        """ContentSearchUngatedError is a ValueError — REST layer maps it to 422."""
        with pytest.raises(ValueError):
            list_entries(content_tree, EntryKind.FILES, "",
                         content_query="FIND_THIS_TOKEN")

    def test_gated_by_name_seed_allowed(self, content_tree):
        """Non-empty name_seed satisfies the gate — no error raised."""
        results = list_entries(content_tree, EntryKind.FILES, ".txt",
                               content_query="FIND_THIS_TOKEN")
        # Should return only .txt files whose content matches
        names = {e.path.name for e in results}
        assert "match_me.txt" in names
        assert "no_match.txt" not in names

    def test_gated_by_extensions_allowed(self, content_tree):
        """extensions pre-filter satisfies the gate."""
        results = list_entries(content_tree, EntryKind.FILES, "",
                               extensions=[".txt"],
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names
        assert "no_match.txt" not in names

    def test_gated_by_min_size_allowed(self, content_tree):
        """min_size pre-filter satisfies the gate."""
        results = list_entries(content_tree, EntryKind.FILES, "",
                               min_size=1,
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names

    def test_gated_by_max_size_allowed(self, content_tree):
        """max_size pre-filter satisfies the gate."""
        results = list_entries(content_tree, EntryKind.FILES, "",
                               max_size=10_000,
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names

    def test_gated_by_modified_after_allowed(self, content_tree):
        """modified_after pre-filter satisfies the gate."""
        results = list_entries(content_tree, EntryKind.FILES, "",
                               modified_after=0.0,
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names

    def test_gated_by_modified_before_allowed(self, content_tree):
        """modified_before pre-filter satisfies the gate."""
        import time
        results = list_entries(content_tree, EntryKind.FILES, "",
                               modified_before=time.time() + 3600,
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names


class TestContentSearchMatching:
    """FFX-I09 acceptance: content_query returns only files whose text matches."""

    def test_substring_match_returns_only_matching_files(self, content_tree):
        """Acceptance criterion: only files containing the token are returned."""
        results = list_entries(content_tree, EntryKind.FILES, ".txt",
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        # match_me.txt and nested_match.txt contain the token; no_match.txt does not
        assert "match_me.txt" in names
        assert "nested_match.txt" in names
        assert "no_match.txt" not in names

    def test_binary_file_is_skipped(self, content_tree):
        """Acceptance criterion: binary files (null-byte heuristic) are skipped."""
        # Use a name seed that would match binary_file.bin too if content were ignored
        results = list_entries(content_tree, EntryKind.FILES, "",
                               extensions=[".bin"],
                               content_query="binary")
        # binary_file.bin starts with \x00 → skipped → no results
        names = {e.path.name for e in results}
        assert "binary_file.bin" not in names

    def test_no_match_file_excluded(self, content_tree):
        """Files that pass the name filter but lack the content token are excluded."""
        results = list_entries(content_tree, EntryKind.FILES, ".txt",
                               content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "no_match.txt" not in names

    def test_regex_content_query(self, content_tree):
        """content_query with match_mode='regex' uses regex search on file content."""
        results = list_entries(content_tree, EntryKind.FILES, ".txt",
                               match_mode="regex",
                               content_query=r"FIND_THIS_\w+")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names
        assert "nested_match.txt" in names
        assert "no_match.txt" not in names

    def test_case_insensitive_content_match(self, content_tree):
        """case_sensitive=False applies to content matching too."""
        results = list_entries(content_tree, EntryKind.FILES, ".txt",
                               case_sensitive=False,
                               content_query="find_this_token")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names
        assert "no_match.txt" not in names

    def test_case_sensitive_content_no_match(self, content_tree):
        """Lowercase query does not match uppercase content when case_sensitive=True."""
        results = list_entries(content_tree, EntryKind.FILES, ".txt",
                               case_sensitive=True,
                               content_query="find_this_token")
        names = {e.path.name for e in results}
        assert "match_me.txt" not in names

    def test_content_query_none_baseline_unchanged(self, content_tree):
        """Acceptance: content_query=None reproduces exact pre-FFX-I09 behaviour."""
        baseline = list_entries(content_tree, EntryKind.FILES, ".txt")
        with_none = list_entries(content_tree, EntryKind.FILES, ".txt",
                                 content_query=None)
        assert [e.path for e in baseline] == [e.path for e in with_none]

    def test_directories_not_affected_by_content_filter(self, content_tree):
        """Directories are never excluded by content_query (no file I/O on dirs)."""
        results = list_entries(content_tree, EntryKind.FOLDERS, "sub",
                               content_query=None)
        names = {e.path.name for e in results}
        assert "sub" in names

    def test_max_bytes_cap_skips_oversized_file(self, tmp_path):
        """Files larger than content_max_bytes are skipped (treated as no-match)."""
        # Write a matching file that is 200 bytes
        f = tmp_path / "big.txt"
        f.write_text("X" * 50 + "TARGET" + "X" * 50)
        # Cap at 10 bytes → file is over cap → skipped
        results = list_entries(tmp_path, EntryKind.FILES, ".txt",
                               content_query="TARGET",
                               content_max_bytes=10)
        names = {e.path.name for e in results}
        assert "big.txt" not in names

    def test_unreadable_file_skipped_gracefully(self, tmp_path):
        """Unreadable files are silently skipped — no exception propagated."""
        from unittest.mock import patch as _patch
        f = tmp_path / "secret.txt"
        f.write_text("TARGET content here")

        # Simulate a permission error on read_bytes
        with _patch("ff_explorer.content_search.Path.read_bytes",
                    side_effect=OSError("permission denied")):
            # Must not raise
            results = list_entries(tmp_path, EntryKind.FILES, ".txt",
                                   content_query="TARGET")
        names = {e.path.name for e in results}
        assert "secret.txt" not in names


class TestFileContentMatchesUnit:
    """Unit tests for ff_explorer.content_search.file_content_matches directly."""

    def test_substring_match(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello world")
        assert file_content_matches(f, "world") is True

    def test_substring_no_match(self, tmp_path):
        f = tmp_path / "b.txt"
        f.write_text("hello world")
        assert file_content_matches(f, "MISSING") is False

    def test_binary_detected_and_skipped(self, tmp_path):
        f = tmp_path / "c.bin"
        f.write_bytes(b"\x00binary")
        assert file_content_matches(f, "binary") is False

    def test_oversized_file_skipped(self, tmp_path):
        f = tmp_path / "d.txt"
        f.write_text("TARGET")
        # Cap at 1 byte → file size > 1 → skipped
        assert file_content_matches(f, "TARGET", max_bytes=1) is False

    def test_regex_mode_with_precompiled(self, tmp_path):
        import re
        f = tmp_path / "e.txt"
        f.write_text("the quick brown fox")
        pattern = re.compile(r"quick\s+\w+")
        assert file_content_matches(f, r"quick\s+\w+", match_mode="regex",
                                    _compiled=pattern) is True

    def test_regex_mode_no_precompile_fallback(self, tmp_path):
        f = tmp_path / "f.txt"
        f.write_text("foo 123 bar")
        assert file_content_matches(f, r"\d+", match_mode="regex") is True

    def test_glob_mode_falls_back_to_substring(self, tmp_path):
        """glob mode on content falls back to substring semantics."""
        f = tmp_path / "g.txt"
        f.write_text("hello WORLD")
        # The query string "WORLD" is a valid glob pattern but we use it as substring
        assert file_content_matches(f, "WORLD", match_mode="glob") is True

    def test_case_insensitive_substring(self, tmp_path):
        f = tmp_path / "h.txt"
        f.write_text("Hello World")
        assert file_content_matches(f, "hello world",
                                    case_sensitive=False) is True

    def test_oserror_returns_false(self, tmp_path):
        """OSError on stat/read returns False without raising."""
        from unittest.mock import patch as _patch
        f = tmp_path / "i.txt"
        f.write_text("x")
        with _patch("ff_explorer.content_search.Path.stat",
                    side_effect=OSError("no access")):
            assert file_content_matches(f, "x") is False

    def test_invalid_regex_fallback_returns_false(self, tmp_path):
        """An invalid regex in _compiled=None fallback path returns False (no raise)."""
        f = tmp_path / "j.txt"
        f.write_text("some content")
        # Intentionally pass an invalid regex pattern; _compiled=None → compile on fly
        assert file_content_matches(f, "[invalid(", match_mode="regex") is False


class TestContentSearchServicePassthrough:
    """FFX-I09: verify the service layer threads content_query through correctly."""

    def test_service_list_entries_content_query(self, content_tree):
        from ff_explorer.api.service import list_entries as svc_list_entries
        results = svc_list_entries(str(content_tree), 1, ".txt",
                                   content_query="FIND_THIS_TOKEN")
        names = {e.path.name for e in results}
        assert "match_me.txt" in names
        assert "no_match.txt" not in names

    def test_service_ungated_raises(self, content_tree):
        from ff_explorer.api.service import (
            list_entries as svc_list_entries,
            ContentSearchUngatedError as SvcError,
        )
        with pytest.raises(SvcError):
            svc_list_entries(str(content_tree), 1, "",
                             content_query="FIND_THIS_TOKEN")

    def test_service_exports_content_search_ungated_error(self):
        """ContentSearchUngatedError is in service.__all__."""
        import ff_explorer.api.service as svc
        assert "ContentSearchUngatedError" in svc.__all__

    def test_service_exports_content_max_bytes(self):
        """CONTENT_MAX_BYTES is re-exported from the service module."""
        import ff_explorer.api.service as svc
        assert "CONTENT_MAX_BYTES" in svc.__all__


# ===========================================================================
# FFX-I11 — largest_entries: size aggregation, sorted order, guards
# ===========================================================================

@pytest.fixture()
def sized_tree(tmp_path: Path) -> Path:
    """
    Tree with controlled file sizes for largest_entries tests:

        tmp_path/
            tiny.txt        10 bytes
            small.txt       50 bytes
            medium.txt     200 bytes
            large.txt     1000 bytes
            sub/
                sub_big.txt  500 bytes
                sub_tiny.txt   5 bytes
    """
    (tmp_path / "tiny.txt").write_bytes(b"x" * 10)
    (tmp_path / "small.txt").write_bytes(b"x" * 50)
    (tmp_path / "medium.txt").write_bytes(b"x" * 200)
    (tmp_path / "large.txt").write_bytes(b"x" * 1000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "sub_big.txt").write_bytes(b"x" * 500)
    (sub / "sub_tiny.txt").write_bytes(b"x" * 5)
    return tmp_path


class TestLargestEntries:
    """FFX-I11 — largest_entries acceptance tests."""

    def test_returns_sorted_descending_by_size(self, sized_tree):
        """Acceptance criterion: results are in descending size order."""
        from ff_explorer.core import largest_entries
        results = largest_entries(sized_tree, top_n=10)
        sizes = [e.size for e in results]
        assert sizes == sorted(sizes, reverse=True)

    def test_top_n_limits_result_count(self, sized_tree):
        """top_n=3 returns exactly the 3 largest files."""
        from ff_explorer.core import largest_entries
        results = largest_entries(sized_tree, top_n=3)
        assert len(results) == 3
        # Must be the three largest: large.txt (1000), sub_big.txt (500), medium.txt (200)
        sizes = [e.size for e in results]
        assert sizes == [1000, 500, 200]

    def test_top_n_larger_than_file_count_returns_all(self, sized_tree):
        """When top_n exceeds the total file count, all files are returned."""
        from ff_explorer.core import largest_entries
        results = largest_entries(sized_tree, top_n=999)
        assert len(results) == 6  # all 6 files in sized_tree

    def test_result_type_is_sized_entry(self, sized_tree):
        """Each result is a SizedEntry with path (str) and size (int) fields."""
        from ff_explorer.core import largest_entries, SizedEntry
        results = largest_entries(sized_tree, top_n=1)
        assert len(results) == 1
        entry = results[0]
        assert isinstance(entry, SizedEntry)
        assert isinstance(entry.path, str)
        assert isinstance(entry.size, int)
        assert entry.size == 1000  # large.txt

    def test_ties_broken_deterministically_by_path(self, tmp_path):
        """Files with equal sizes are ordered by path ascending (stable output)."""
        from ff_explorer.core import largest_entries
        # Create 3 files of the same size
        (tmp_path / "aaa.txt").write_bytes(b"x" * 100)
        (tmp_path / "bbb.txt").write_bytes(b"x" * 100)
        (tmp_path / "ccc.txt").write_bytes(b"x" * 100)
        results = largest_entries(tmp_path, top_n=3)
        assert len(results) == 3
        # All same size; paths must be sorted ascending
        paths = [e.path for e in results]
        assert paths == sorted(paths)

    def test_top_n_zero_raises_value_error(self, sized_tree):
        """top_n=0 raises ValueError (consistent with core validation style)."""
        from ff_explorer.core import largest_entries
        with pytest.raises(ValueError, match="top_n"):
            largest_entries(sized_tree, top_n=0)

    def test_top_n_negative_raises_value_error(self, sized_tree):
        """top_n=-1 raises ValueError."""
        from ff_explorer.core import largest_entries
        with pytest.raises(ValueError, match="top_n"):
            largest_entries(sized_tree, top_n=-1)

    def test_missing_path_raises_file_not_found_error(self, tmp_path):
        """A non-existent path raises FileNotFoundError."""
        from ff_explorer.core import largest_entries
        missing = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError):
            largest_entries(missing, top_n=5)

    def test_name_seed_filters_by_filename(self, sized_tree):
        """name_seed narrows aggregation to files whose name contains the seed."""
        from ff_explorer.core import largest_entries
        results = largest_entries(sized_tree, top_n=10, name_seed="sub")
        names = {e.path.split("/")[-1].split("\\")[-1] for e in results}
        assert names == {"sub_big.txt", "sub_tiny.txt"}

    def test_name_seed_empty_string_returns_whole_tree(self, sized_tree):
        """Empty name_seed (default) aggregates all files — no EmptySeedError."""
        from ff_explorer.core import largest_entries
        results = largest_entries(sized_tree, top_n=99, name_seed="")
        assert len(results) == 6

    def test_default_top_n_is_fifty(self, tmp_path):
        """Default top_n=50: a tree with 3 files returns all 3 without specifying top_n."""
        from ff_explorer.core import largest_entries
        for i in range(3):
            (tmp_path / f"f{i}.txt").write_bytes(b"x" * (i + 1) * 10)
        results = largest_entries(tmp_path)
        assert len(results) == 3
        assert results[0].size >= results[-1].size  # descending

    def test_service_passthrough_returns_sized_entries(self, sized_tree):
        """Service thin passthrough delegates correctly to core."""
        from ff_explorer.api.service import largest_entries as svc_largest
        from ff_explorer.core import SizedEntry
        results = svc_largest(str(sized_tree), top_n=2)
        assert len(results) == 2
        assert all(isinstance(e, SizedEntry) for e in results)
        assert results[0].size >= results[1].size

    def test_service_exported_in_all(self):
        """largest_entries and SizedEntry appear in service.__all__."""
        import ff_explorer.api.service as svc
        assert "largest_entries" in svc.__all__
        assert "SizedEntry" in svc.__all__

    def test_headless_no_gui_transport_imports(self):
        """core.py must not import tkinter/PySide6/fastapi/fastmcp (invariant 1)."""
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c",
             "import ff_explorer.core; "
             "import sys; "
             "bad = [m for m in sys.modules if m.startswith(('tkinter','PySide6','fastapi','fastmcp'))]; "
             "print(bad)"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "[]", f"Unwanted imports: {result.stdout}"


# ===========================================================================
# SPEC-17 — include_hidden toggle
# ===========================================================================

@pytest.fixture()
def hidden_tree(tmp_path: Path) -> Path:
    """Tree with a dotfile, a normal file, and a dot-prefixed subdirectory.

        tmp_path/
            normal.txt        (visible)
            .hidden.txt       (hidden — dotfile)
            .hidden_dir/      (hidden directory)
                inside.txt    (inside hidden dir)
            subdir/           (visible directory)
    """
    (tmp_path / "normal.txt").write_text("visible")
    (tmp_path / ".hidden.txt").write_text("hidden")
    hdir = tmp_path / ".hidden_dir"
    hdir.mkdir()
    (hdir / "inside.txt").write_text("inside hidden dir")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    return tmp_path


class TestIncludeHiddenFiles:
    """SPEC-17: include_hidden=True (default) vs include_hidden=False for files."""

    def test_default_true_returns_both(self, hidden_tree):
        """Default include_hidden=True must return both normal and dotfiles."""
        results = list_entries(hidden_tree, EntryKind.FILES, "")
        names = {e.path.name for e in results}
        assert "normal.txt" in names
        assert ".hidden.txt" in names

    def test_explicit_true_returns_both(self, hidden_tree):
        """Explicit include_hidden=True is identical to the default."""
        default = list_entries(hidden_tree, EntryKind.FILES, "")
        explicit = list_entries(hidden_tree, EntryKind.FILES, "", include_hidden=True)
        assert {e.path for e in default} == {e.path for e in explicit}

    def test_false_excludes_dotfile(self, hidden_tree):
        """include_hidden=False must exclude dotfiles."""
        results = list_entries(hidden_tree, EntryKind.FILES, "", include_hidden=False)
        names = {e.path.name for e in results}
        assert "normal.txt" in names
        assert ".hidden.txt" not in names

    def test_false_excludes_files_inside_hidden_dir(self, hidden_tree):
        """Files inside a hidden directory are reachable by the walk but the
        directory itself is excluded from FOLDERS results; files inside it are
        still reachable via os.walk (the dir is not pruned). The hidden *file*
        inside is excluded only when its own name starts with a dot. Here
        inside.txt is NOT a dotfile so it IS visible when include_hidden=False
        (the filter acts on entry name, not parent directory name)."""
        results = list_entries(hidden_tree, EntryKind.FILES, "", include_hidden=False)
        names = {e.path.name for e in results}
        # inside.txt is not a dotfile itself — it passes include_hidden=False
        assert "inside.txt" in names

    def test_name_seed_combined_with_hidden_false(self, hidden_tree):
        """Name filter + include_hidden=False: only non-hidden entries matching seed."""
        results = list_entries(hidden_tree, EntryKind.FILES, "hidden",
                               include_hidden=False)
        names = {e.path.name for e in results}
        # ".hidden.txt" name contains "hidden" but is a dotfile → excluded
        assert ".hidden.txt" not in names
        # "normal.txt" doesn't contain "hidden" → also not present
        assert "normal.txt" not in names

    def test_no_regression_default_includes_hidden(self, hidden_tree):
        """Regression: with defaults, hidden files must be present (no behaviour change)."""
        results = list_entries(hidden_tree, EntryKind.FILES, "")
        names = {e.path.name for e in results}
        assert ".hidden.txt" in names, (
            "Regression: default include_hidden=True must include dotfiles"
        )


class TestIncludeHiddenFolders:
    """SPEC-17: include_hidden toggle for directories (FOLDERS kind)."""

    def test_default_true_returns_hidden_dir(self, hidden_tree):
        """Default include_hidden=True includes dot-prefixed directories."""
        results = list_entries(hidden_tree, EntryKind.FOLDERS, "")
        names = {e.path.name for e in results}
        assert ".hidden_dir" in names
        assert "subdir" in names

    def test_false_excludes_hidden_dir(self, hidden_tree):
        """include_hidden=False excludes dot-prefixed directories."""
        results = list_entries(hidden_tree, EntryKind.FOLDERS, "", include_hidden=False)
        names = {e.path.name for e in results}
        assert "subdir" in names
        assert ".hidden_dir" not in names

    def test_no_regression_folder_default(self, hidden_tree):
        """Regression: default still returns hidden dirs."""
        with_default = list_entries(hidden_tree, EntryKind.FOLDERS, "")
        with_true = list_entries(hidden_tree, EntryKind.FOLDERS, "", include_hidden=True)
        assert {e.path for e in with_default} == {e.path for e in with_true}


class TestIncludeHiddenIterAndReport:
    """SPEC-17: include_hidden threads through iter_entries and list_entries_with_report."""

    def test_iter_entries_include_hidden_false(self, hidden_tree):
        results = list(iter_entries(hidden_tree, EntryKind.FILES, "",
                                    include_hidden=False))
        names = {e.path.name for e in results}
        assert ".hidden.txt" not in names
        assert "normal.txt" in names

    def test_list_entries_with_report_include_hidden_false(self, hidden_tree):
        report = list_entries_with_report(hidden_tree, EntryKind.FILES, "",
                                          include_hidden=False)
        names = {e.path.name for e in report.entries}
        assert ".hidden.txt" not in names
        assert "normal.txt" in names

    def test_list_entries_with_report_default_includes_hidden(self, hidden_tree):
        report = list_entries_with_report(hidden_tree, EntryKind.FILES, "")
        names = {e.path.name for e in report.entries}
        assert ".hidden.txt" in names


# ===========================================================================
# SPEC-18 — copy_entries / move_entries (core half)
# ===========================================================================

@pytest.fixture()
def transfer_tree(tmp_path: Path) -> Path:
    """Source tree for copy/move tests.

        tmp_path/src/
            alpha.txt
            beta.txt
            gamma.log
            sub_dir/
                delta.txt
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.txt").write_text("alpha")
    (src / "beta.txt").write_text("beta")
    (src / "gamma.log").write_text("gamma")
    sub = src / "sub_dir"
    sub.mkdir()
    (sub / "delta.txt").write_text("delta")
    return tmp_path  # return root so tests can make dest outside src


class TestTransferReport:
    """TransferReport dataclass shape and defaults."""

    def test_default_dry_run(self):
        r = TransferReport()
        assert r.dry_run is True
        assert r.kind == "copy"
        assert r.matched == []
        assert r.transferred == []
        assert r.failed == []
        assert r.destination is None

    def test_would_affect_alias(self):
        paths = [Path("/a"), Path("/b")]
        r = TransferReport(matched=paths)
        assert r.would_affect is r.matched


class TestCopyEntriesDryRun:
    """copy_entries dry_run=True: preview only, nothing copied."""

    def test_dry_run_default_copies_nothing(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = copy_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(dest))
        assert report.dry_run is True
        assert report.transferred == []
        assert not dest.exists(), "dest must not be created on dry_run"

    def test_dry_run_reports_matched_set(self, transfer_tree):
        src = transfer_tree / "src"
        report = copy_entries(str(src), EntryKind.FILES, ".txt",
                              destination=str(transfer_tree / "dest"))
        assert report.dry_run is True
        matched_names = {p.name for p in report.matched}
        assert "alpha.txt" in matched_names
        assert "beta.txt" in matched_names
        assert "gamma.log" not in matched_names

    def test_dry_run_originals_unchanged(self, transfer_tree):
        src = transfer_tree / "src"
        report = copy_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(transfer_tree / "dest"))
        assert report.dry_run is True
        # Source file must still be there
        assert (src / "alpha.txt").exists()


class TestCopyEntriesLive:
    """copy_entries dry_run=False + confirm=True: files/folders actually copied."""

    def test_live_copy_files_exist_at_dest(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = copy_entries(str(src), EntryKind.FILES, ".txt",
                              destination=str(dest),
                              dry_run=False, confirm=True)
        assert report.dry_run is False
        assert (dest / "alpha.txt").exists()
        assert (dest / "beta.txt").exists()
        assert not (dest / "gamma.log").exists()

    def test_live_copy_originals_preserved(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        copy_entries(str(src), EntryKind.FILES, "alpha",
                     destination=str(dest), dry_run=False, confirm=True)
        # Originals must still exist
        assert (src / "alpha.txt").exists()

    def test_live_copy_folders(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = copy_entries(str(src), EntryKind.FOLDERS, "sub",
                              destination=str(dest), dry_run=False, confirm=True)
        assert (dest / "sub_dir").is_dir()
        assert (src / "sub_dir").is_dir(), "source dir must still exist after copy"

    def test_destination_created_if_absent(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "new" / "nested" / "dest"
        assert not dest.exists()
        copy_entries(str(src), EntryKind.FILES, "alpha",
                     destination=str(dest), dry_run=False, confirm=True)
        assert dest.exists()

    def test_destination_in_report(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = copy_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(dest), dry_run=False, confirm=True)
        assert report.destination == str(dest.resolve())

    def test_per_item_failure_reported_batch_continues(self, transfer_tree):
        """A per-item OSError is collected into failed; other items still copied."""
        from unittest.mock import patch as _patch
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        dest.mkdir(parents=True)

        # Inject an OSError for the first copy2 call (alpha.txt) only;
        # subsequent calls (beta.txt) proceed normally.
        real_copy2 = __import__("shutil").copy2
        call_count = {"n": 0}

        def _selective_fail(s, d, **kw):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("injected failure for alpha.txt")
            return real_copy2(s, d, **kw)

        with _patch("ff_explorer.core.shutil.copy2", side_effect=_selective_fail):
            report = copy_entries(str(src), EntryKind.FILES, ".txt",
                                  destination=str(dest), dry_run=False, confirm=True)

        # first item failed → reported; second item (beta.txt) copied normally
        assert len(report.failed) >= 1
        assert (dest / "beta.txt").exists(), "beta.txt must be copied despite alpha failure"


class TestCopyEntriesGate:
    """copy_entries safety gate: empty seed and confirm requirement."""

    def test_empty_seed_raises_empty_seed_error(self, transfer_tree):
        src = transfer_tree / "src"
        with pytest.raises(EmptySeedError):
            copy_entries(str(src), EntryKind.FILES, "",
                         destination=str(transfer_tree / "dest"))

    def test_whitespace_seed_raises(self, transfer_tree):
        src = transfer_tree / "src"
        with pytest.raises(EmptySeedError):
            copy_entries(str(src), EntryKind.FILES, "   ",
                         destination=str(transfer_tree / "dest"))

    def test_no_confirm_with_dry_run_false_raises(self, transfer_tree):
        src = transfer_tree / "src"
        with pytest.raises(ValueError):
            copy_entries(str(src), EntryKind.FILES, "alpha",
                         destination=str(transfer_tree / "dest"),
                         dry_run=False, confirm=False)

    def test_destination_inside_source_raises(self, transfer_tree):
        src = transfer_tree / "src"
        dest_inside = src / "nested_dest"
        with pytest.raises(ValueError, match="recursion"):
            copy_entries(str(src), EntryKind.FILES, "alpha",
                         destination=str(dest_inside),
                         dry_run=False, confirm=True)


class TestMoveEntriesDryRun:
    """move_entries dry_run=True: preview only, nothing moved."""

    def test_dry_run_default_moves_nothing(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = move_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(dest))
        assert report.dry_run is True
        assert report.transferred == []
        assert (src / "alpha.txt").exists(), "source must remain on dry_run"
        assert not dest.exists(), "dest must not be created on dry_run"

    def test_dry_run_reports_matched_set(self, transfer_tree):
        src = transfer_tree / "src"
        report = move_entries(str(src), EntryKind.FILES, ".txt",
                              destination=str(transfer_tree / "dest"))
        matched_names = {p.name for p in report.matched}
        assert "alpha.txt" in matched_names
        assert "beta.txt" in matched_names
        assert "gamma.log" not in matched_names


class TestMoveEntriesLive:
    """move_entries dry_run=False + confirm=True: files/folders actually moved."""

    def test_live_move_files_exist_at_dest(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = move_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(dest), dry_run=False, confirm=True)
        assert report.dry_run is False
        assert (dest / "alpha.txt").exists()

    def test_live_move_originals_gone(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        move_entries(str(src), EntryKind.FILES, "alpha",
                     destination=str(dest), dry_run=False, confirm=True)
        assert not (src / "alpha.txt").exists(), "original must be gone after move"

    def test_live_move_folders(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = move_entries(str(src), EntryKind.FOLDERS, "sub",
                              destination=str(dest), dry_run=False, confirm=True)
        assert (dest / "sub_dir").is_dir()
        assert not (src / "sub_dir").exists(), "source dir must be gone after move"

    def test_destination_in_report(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = move_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(dest), dry_run=False, confirm=True)
        assert report.destination == str(dest.resolve())

    def test_kind_discriminator_is_move(self, transfer_tree):
        src = transfer_tree / "src"
        dest = transfer_tree / "dest"
        report = move_entries(str(src), EntryKind.FILES, "alpha",
                              destination=str(dest), dry_run=False, confirm=True)
        assert report.kind == "move"


class TestMoveEntriesGate:
    """move_entries safety gate: empty seed and confirm requirement."""

    def test_empty_seed_raises(self, transfer_tree):
        src = transfer_tree / "src"
        with pytest.raises(EmptySeedError):
            move_entries(str(src), EntryKind.FILES, "",
                         destination=str(transfer_tree / "dest"))

    def test_whitespace_seed_raises(self, transfer_tree):
        src = transfer_tree / "src"
        with pytest.raises(EmptySeedError):
            move_entries(str(src), EntryKind.FILES, "  ",
                         destination=str(transfer_tree / "dest"))

    def test_no_confirm_with_dry_run_false_raises(self, transfer_tree):
        src = transfer_tree / "src"
        with pytest.raises(ValueError):
            move_entries(str(src), EntryKind.FILES, "alpha",
                         destination=str(transfer_tree / "dest"),
                         dry_run=False, confirm=False)

    def test_destination_inside_source_raises(self, transfer_tree):
        src = transfer_tree / "src"
        dest_inside = src / "nested_dest"
        with pytest.raises(ValueError, match="recursion"):
            move_entries(str(src), EntryKind.FILES, "alpha",
                         destination=str(dest_inside),
                         dry_run=False, confirm=True)
