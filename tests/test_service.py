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

    def test_invalid_regex_error_exported(self):
        from ff_explorer.core import InvalidRegexError
        assert service.InvalidRegexError is InvalidRegexError


# ===========================================================================
# Service passthrough — FFX-I01 match_mode + case_sensitive
# ===========================================================================

class TestServiceListEntriesMatchMode:
    """Verify service.list_entries forwards match_mode and case_sensitive to core."""

    def test_glob_mode_passthrough(self, svc_tree):
        results = service.list_entries(str(svc_tree), 1, "*.txt", match_mode="glob")
        names = {e.path.name for e in results}
        assert "file_a.txt" in names
        assert "file_b.log" not in names

    def test_regex_mode_passthrough(self, svc_tree):
        results = service.list_entries(str(svc_tree), 1, r"^file_a",
                                       match_mode="regex")
        names = {e.path.name for e in results}
        assert names == {"file_a.txt"}

    def test_invalid_regex_raises_through_service(self, svc_tree):
        from ff_explorer.core import InvalidRegexError
        with pytest.raises(InvalidRegexError):
            service.list_entries(str(svc_tree), 1, r"[bad", match_mode="regex")

    def test_invalid_regex_is_value_error_via_service(self, svc_tree):
        with pytest.raises(ValueError):
            service.list_entries(str(svc_tree), 1, r"[bad", match_mode="regex")

    def test_case_insensitive_passthrough(self, svc_tree):
        results = service.list_entries(str(svc_tree), 1, "FILE_C",
                                       case_sensitive=False)
        names = {e.path.name for e in results}
        assert "file_c.txt" in names


# ===========================================================================
# Service passthrough — FFX-I02 structured filters
# ===========================================================================

@pytest.fixture()
def sized_svc_tree(tmp_path: Path) -> Path:
    """Tree with controlled sizes for service filter tests."""
    T = 1_700_000_000.0
    import os

    def make(name: Path, content: bytes, mtime: float) -> None:
        name.write_bytes(content)
        os.utime(name, (mtime, mtime))

    make(tmp_path / "big.txt",   b"x" * 500, T - 10)
    make(tmp_path / "small.txt", b"x" * 5,   T - 200)
    make(tmp_path / "data.log",  b"x" * 50,  T - 100)
    return tmp_path


class TestServiceListEntriesFilters:
    """Verify service.list_entries forwards structured filter params to core."""

    def test_min_size_passthrough(self, sized_svc_tree):
        results = service.list_entries(str(sized_svc_tree), 1, "", min_size=50)
        names = {e.path.name for e in results}
        assert "big.txt" in names
        assert "data.log" in names
        assert "small.txt" not in names

    def test_max_size_passthrough(self, sized_svc_tree):
        results = service.list_entries(str(sized_svc_tree), 1, "", max_size=50)
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "data.log" in names
        assert "big.txt" not in names

    def test_modified_after_passthrough(self, sized_svc_tree):
        T = 1_700_000_000.0
        results = service.list_entries(str(sized_svc_tree), 1, "",
                                       modified_after=T - 50)
        names = {e.path.name for e in results}
        assert "big.txt" in names
        assert "small.txt" not in names
        assert "data.log" not in names

    def test_modified_before_passthrough(self, sized_svc_tree):
        T = 1_700_000_000.0
        results = service.list_entries(str(sized_svc_tree), 1, "",
                                       modified_before=T - 50)
        names = {e.path.name for e in results}
        assert "small.txt" in names
        assert "big.txt" not in names

    def test_extensions_passthrough(self, sized_svc_tree):
        results = service.list_entries(str(sized_svc_tree), 1, "",
                                       extensions=[".txt"])
        names = {e.path.name for e in results}
        assert "big.txt" in names
        assert "small.txt" in names
        assert "data.log" not in names

    def test_combined_filters_passthrough(self, sized_svc_tree):
        T = 1_700_000_000.0
        results = service.list_entries(str(sized_svc_tree), 1, "",
                                       min_size=50,
                                       modified_after=T - 50,
                                       extensions=[".txt"])
        names = {e.path.name for e in results}
        assert names == {"big.txt"}

    def test_no_filters_same_as_baseline(self, sized_svc_tree):
        baseline = service.list_entries(str(sized_svc_tree), 1, "")
        with_nones = service.list_entries(str(sized_svc_tree), 1, "",
                                          min_size=None, max_size=None,
                                          modified_after=None, modified_before=None,
                                          extensions=None)
        assert {e.path for e in baseline} == {e.path for e in with_nones}


# ===========================================================================
# FFX-I04 — service passthrough for respect_ignore / ignore_globs
# ===========================================================================

class TestServiceIgnorePassthrough:
    """Verify service.list_entries forwards respect_ignore and ignore_globs to core."""

    @pytest.fixture()
    def ignore_svc_tree(self, tmp_path: Path) -> Path:
        """Small tree: root .gitignore ignores *.log; one .log and one .txt file."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "keep.txt").write_text("keep")
        (tmp_path / "drop.log").write_text("drop")
        return tmp_path

    def test_respect_ignore_via_service_excludes_log(self, ignore_svc_tree):
        """service.list_entries with respect_ignore=True omits .gitignore-matched files."""
        results = service.list_entries(str(ignore_svc_tree), 1, "",
                                       respect_ignore=True)
        names = {e.path.name for e in results}
        assert "drop.log" not in names
        assert "keep.txt" in names

    def test_ignore_globs_via_service(self, ignore_svc_tree):
        """service.list_entries with ignore_globs=["*.txt"] omits .txt files."""
        results = service.list_entries(str(ignore_svc_tree), 1, "",
                                       respect_ignore=False,
                                       ignore_globs=["*.txt"])
        names = {e.path.name for e in results}
        assert "keep.txt" not in names
        assert "drop.log" in names

    def test_service_defaults_unchanged(self, ignore_svc_tree):
        """With defaults, service output is identical to no-ignore call."""
        baseline = service.list_entries(str(ignore_svc_tree), 1, "")
        explicit = service.list_entries(str(ignore_svc_tree), 1, "",
                                        respect_ignore=False, ignore_globs=None)
        assert {e.path for e in baseline} == {e.path for e in explicit}
        # Both must contain the .log file (ignore is OFF)
        names = {e.path.name for e in baseline}
        assert "drop.log" in names


# ===========================================================================
# SPEC-17 — service passthrough for include_hidden
# ===========================================================================

@pytest.fixture()
def hidden_svc_tree(tmp_path: Path) -> Path:
    """Tree with a dotfile and a normal file for include_hidden tests."""
    (tmp_path / "visible.txt").write_text("v")
    (tmp_path / ".dotfile.txt").write_text("h")
    return tmp_path


class TestServiceIncludeHidden:
    """Verify service.list_entries forwards include_hidden to core."""

    def test_default_true_includes_dotfile(self, hidden_svc_tree):
        results = service.list_entries(str(hidden_svc_tree), 1, "")
        names = {e.path.name for e in results}
        assert ".dotfile.txt" in names
        assert "visible.txt" in names

    def test_false_excludes_dotfile(self, hidden_svc_tree):
        results = service.list_entries(str(hidden_svc_tree), 1, "",
                                       include_hidden=False)
        names = {e.path.name for e in results}
        assert "visible.txt" in names
        assert ".dotfile.txt" not in names

    def test_explicit_true_same_as_default(self, hidden_svc_tree):
        default = service.list_entries(str(hidden_svc_tree), 1, "")
        explicit = service.list_entries(str(hidden_svc_tree), 1, "",
                                        include_hidden=True)
        assert {e.path for e in default} == {e.path for e in explicit}

    def test_iter_entries_include_hidden_false(self, hidden_svc_tree):
        results = list(service.iter_entries(str(hidden_svc_tree), 1, "",
                                            include_hidden=False))
        names = {e.path.name for e in results}
        assert ".dotfile.txt" not in names
        assert "visible.txt" in names

    def test_list_entries_with_report_include_hidden_false(self, hidden_svc_tree):
        result = service.list_entries_with_report(str(hidden_svc_tree), 1, "",
                                                  include_hidden=False)
        names = {e.path.name for e in result.entries}
        assert ".dotfile.txt" not in names
        assert "visible.txt" in names


# ===========================================================================
# SPEC-18 — service passthroughs for copy_entries / move_entries
# ===========================================================================

@pytest.fixture()
def transfer_svc_tree(tmp_path: Path) -> Path:
    """Source + dest root for transfer service tests."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.txt").write_text("alpha")
    (src / "beta.txt").write_text("beta")
    (src / "gamma.log").write_text("gamma")
    return tmp_path


class TestServiceCopyEntries:
    """service.copy_entries passthroughs and gate forwarding."""

    def test_dry_run_default_copies_nothing(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        dest = transfer_svc_tree / "dest"
        report = service.copy_entries(str(src), 1, "alpha",
                                      destination=str(dest))
        assert report.dry_run is True
        assert report.transferred == []
        assert not dest.exists()

    def test_dry_run_matched_set_correct(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        report = service.copy_entries(str(src), 1, ".txt",
                                      destination=str(transfer_svc_tree / "dest"))
        matched_names = {p.name for p in report.matched}
        assert "alpha.txt" in matched_names
        assert "gamma.log" not in matched_names

    def test_live_copy_files_at_dest(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        dest = transfer_svc_tree / "dest"
        report = service.copy_entries(str(src), 1, "alpha",
                                      destination=str(dest),
                                      dry_run=False, confirm=True)
        assert (dest / "alpha.txt").exists()
        assert (src / "alpha.txt").exists()  # original preserved

    def test_empty_seed_raises(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        from ff_explorer.core import EmptySeedError
        with pytest.raises(EmptySeedError):
            service.copy_entries(str(src), 1, "",
                                 destination=str(transfer_svc_tree / "dest"))

    def test_no_confirm_raises(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        with pytest.raises(ValueError):
            service.copy_entries(str(src), 1, "alpha",
                                 destination=str(transfer_svc_tree / "dest"),
                                 dry_run=False, confirm=False)

    def test_transfer_report_in_all(self):
        assert "TransferReport" in service.__all__
        assert "copy_entries" in service.__all__
        assert "move_entries" in service.__all__


class TestServiceMoveEntries:
    """service.move_entries passthroughs and gate forwarding."""

    def test_dry_run_default_moves_nothing(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        dest = transfer_svc_tree / "dest"
        report = service.move_entries(str(src), 1, "alpha",
                                      destination=str(dest))
        assert report.dry_run is True
        assert report.transferred == []
        assert (src / "alpha.txt").exists()

    def test_live_move_original_gone(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        dest = transfer_svc_tree / "dest"
        service.move_entries(str(src), 1, "alpha",
                             destination=str(dest), dry_run=False, confirm=True)
        assert not (src / "alpha.txt").exists()
        assert (dest / "alpha.txt").exists()

    def test_empty_seed_raises(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        from ff_explorer.core import EmptySeedError
        with pytest.raises(EmptySeedError):
            service.move_entries(str(src), 1, "",
                                 destination=str(transfer_svc_tree / "dest"))

    def test_no_confirm_raises(self, transfer_svc_tree):
        src = transfer_svc_tree / "src"
        with pytest.raises(ValueError):
            service.move_entries(str(src), 1, "alpha",
                                 destination=str(transfer_svc_tree / "dest"),
                                 dry_run=False, confirm=False)
