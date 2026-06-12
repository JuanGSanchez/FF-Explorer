"""
Test suite for ff_explorer.api.service — thin wrapper over core.

This layer is tested for:
  - Correct passthrough of all parameters to the core.
  - Re-export of all expected names.
  - EmptySeedError propagation (not swallowed).
  - dry_run / confirm contract forwarding.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ff_explorer.api import service
from ff_explorer.core import EntryKind, EmptySeedError


@pytest.fixture()
def svc_tree(tmp_path: Path) -> Path:
    (tmp_path / "file_a.txt").write_text("a")
    (tmp_path / "file_b.log").write_text("b")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file_c.txt").write_text("c")
    return tmp_path


class TestServiceListEntries:
    def test_returns_match_entries(self, svc_tree):
        results = service.list_entries(str(svc_tree), 1, "file_a")
        assert len(results) == 1
        assert results[0].path.name == "file_a.txt"

    def test_empty_seed_allowed(self, svc_tree):
        results = service.list_entries(str(svc_tree), 1)
        assert len(results) == 3

    def test_folders_kind(self, svc_tree):
        results = service.list_entries(str(svc_tree), 0)
        names = {e.path.name for e in results}
        assert "sub" in names

    def test_case_insensitive(self, svc_tree):
        results = service.list_entries(str(svc_tree), 1, "FILE_A", case_sensitive=False)
        assert len(results) == 1

    def test_invalid_path_raises(self, tmp_path):
        with pytest.raises(ValueError):
            service.list_entries(str(tmp_path / "ghost"), 1)


class TestServiceEntryMetadata:
    def test_file_type(self, svc_tree):
        meta = service.entry_metadata(str(svc_tree / "file_a.txt"))
        assert meta["type"] == "file"

    def test_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            service.entry_metadata(str(tmp_path / "ghost.txt"))


class TestServiceSaveListing:
    def test_creates_file(self, svc_tree):
        out = service.save_listing(str(svc_tree), 1, "file_a")
        assert isinstance(out, Path)
        assert out.exists()

    def test_invalid_path_raises(self, tmp_path):
        with pytest.raises(ValueError):
            service.save_listing(str(tmp_path / "ghost"), 1)


class TestServiceRemoveEntries:
    def test_blank_seed_raises(self, svc_tree):
        with pytest.raises(EmptySeedError):
            service.remove_entries(str(svc_tree), 1, "")

    def test_dry_run_default(self, svc_tree):
        report = service.remove_entries(str(svc_tree), 1, "file_a")
        assert report.dry_run is True
        assert report.removed == []

    def test_no_confirm_raises(self, svc_tree):
        with pytest.raises(ValueError):
            service.remove_entries(str(svc_tree), 1, "file_a",
                                   dry_run=False, confirm=False)

    def test_live_remove_with_send2trash(self, svc_tree):
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = service.remove_entries(str(svc_tree), 1, "file_a",
                                            dry_run=False, confirm=True)
        assert mock_trash.called
        assert len(report.removed) > 0


class TestServiceCompressEntries:
    def test_blank_seed_raises(self, svc_tree):
        with pytest.raises(EmptySeedError):
            service.compress_entries(str(svc_tree), 1, "")

    def test_dry_run_default(self, svc_tree):
        report = service.compress_entries(str(svc_tree), 1, "file_a")
        assert report.dry_run is True
        assert report.archives == []

    def test_no_confirm_raises(self, svc_tree):
        with pytest.raises(ValueError):
            service.compress_entries(str(svc_tree), 1, "file_a",
                                     dry_run=False, confirm=False)

    def test_live_compress(self, svc_tree):
        report = service.compress_entries(str(svc_tree), 1, "file_a",
                                          dry_run=False, confirm=True)
        assert len(report.archives) == 1
        assert report.archives[0].exists()


class TestServiceExports:
    """Verify __all__ is complete and names are importable."""
    def test_all_names_exported(self):
        for name in service.__all__:
            assert hasattr(service, name), f"service does not export: {name}"

    def test_entry_kind_exported(self):
        assert service.EntryKind is EntryKind

    def test_empty_seed_error_exported(self):
        assert service.EmptySeedError is EmptySeedError
