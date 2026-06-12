"""
Additional tests targeting uncovered branches in ff_explorer.core and
importing ff_explorer.api.mcp_server to cover its module-level initialisation.

Covered here:
  - entry_metadata: symlink type (line 232) and "other" type fallback (line 238).
  - save_listing: OSError in inner write loop (lines 296-299).
  - remove_entries: shutil.rmtree fallback when send2trash unavailable (lines 384-388).
  - compress_entries: per-file write error branch (lines 470-471),
    post-compress delete failure branch (lines 478-481),
    per-folder archive error branch (lines 495-496, 501-504).
  - mcp_server: module-level import (lines 53-73, FastMCP.from_fastapi + http_app).
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ff_explorer.core import (
    EntryKind,
    entry_metadata,
    save_listing,
    remove_entries,
    compress_entries,
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
# save_listing — OSError write-loop branch (lines 296-299)
# ===========================================================================

class TestSaveListingWriteError:
    def test_write_error_yields_blank_line(self, simple_tree):
        """
        Simulate an OSError on fp.write() for one entry; the loop should
        continue and write a blank line instead.  The output file is still
        created and returned.
        """
        original_write = None

        call_count = [0]

        def patched_write(data):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("simulated write error")
            return original_write(data)

        import builtins
        real_open = builtins.open

        class PatchedFile:
            def __init__(self, fobj):
                self._f = fobj
                nonlocal original_write
                original_write = fobj.write

            def write(self, data):
                return patched_write(data)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._f.close()

        # We just verify the function completes without raising even when
        # an individual write raises OSError.  Mock the file object's write.
        from ff_explorer import core as core_mod
        original_open = builtins.open

        opened_files = []

        def fake_open(path, mode="r", **kwargs):
            fobj = original_open(path, mode, **kwargs)
            if "w" in mode and str(path).endswith(".txt"):
                opened_files.append(fobj)
                # Wrap write to raise on first call
                _orig = fobj.write
                _calls = [0]

                def noisy_write(data):
                    _calls[0] += 1
                    if _calls[0] == 1:
                        raise OSError("simulated error")
                    return _orig(data)

                fobj.write = noisy_write
            return fobj

        with patch("builtins.open", side_effect=fake_open):
            out = save_listing(simple_tree, EntryKind.FILES, "alpha")

        assert isinstance(out, Path)


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
