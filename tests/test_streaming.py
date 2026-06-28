"""
tests/test_streaming.py
=======================
Tests for SPEC-14 (iter_entries streaming generator) and SPEC-15
(graceful degradation / skip-report via list_entries_with_report).

All tests are deterministic and offline (tmp_path trees, no network,
no real permission changes beyond what pytest/OS supports).
"""
from __future__ import annotations

import inspect
import itertools
import os
import stat
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import patch, MagicMock

import pytest

from ff_explorer.core import (
    EntryKind,
    MatchEntry,
    SkippedEntry,
    ListingResult,
    iter_entries,
    list_entries,
    list_entries_with_report,
)
import ff_explorer.api.service as svc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def flat_tree(tmp_path: Path) -> Path:
    """A simple flat tree: root/alpha.txt, root/beta.txt, root/gamma.log"""
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.txt").write_text("b")
    (tmp_path / "gamma.log").write_text("g")
    return tmp_path


@pytest.fixture()
def nested_tree(tmp_path: Path) -> Path:
    """A two-level tree with files matching 'data'."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "data_root.txt").write_text("root")
    (sub / "data_sub.txt").write_text("sub")
    (sub / "other.txt").write_text("other")
    return tmp_path


# ---------------------------------------------------------------------------
# SPEC-14: iter_entries is a generator / lazy iterator
# ---------------------------------------------------------------------------

class TestIterEntriesIsGenerator:
    """SPEC-14: calling iter_entries() returns a generator, not a list."""

    def test_returns_generator(self, flat_tree: Path) -> None:
        it = iter_entries(flat_tree, EntryKind.FILES, "")
        assert inspect.isgenerator(it), (
            "iter_entries must return a generator object"
        )

    def test_not_a_list(self, flat_tree: Path) -> None:
        result = iter_entries(flat_tree, EntryKind.FILES, "")
        assert not isinstance(result, list), (
            "iter_entries must NOT return a list"
        )

    def test_is_iterator(self, flat_tree: Path) -> None:
        it = iter_entries(flat_tree, EntryKind.FILES, "")
        assert hasattr(it, "__next__"), "iter_entries result must be an iterator"
        assert hasattr(it, "__iter__"), "iter_entries result must be iterable"


class TestIterEntriesLaziness:
    """SPEC-14 streaming: first item available without materialising all."""

    def test_next_works_without_materialising_all(self, nested_tree: Path) -> None:
        """next() on the generator yields the first item only."""
        it = iter_entries(nested_tree, EntryKind.FILES, "")
        first = next(it)
        assert isinstance(first, MatchEntry)

    def test_islice_does_not_consume_all(self, nested_tree: Path) -> None:
        """itertools.islice can take N items without consuming the rest."""
        it = iter_entries(nested_tree, EntryKind.FILES, "")
        first_item = list(itertools.islice(it, 1))
        assert len(first_item) == 1
        assert isinstance(first_item[0], MatchEntry)

    def test_partial_consumption(self, nested_tree: Path) -> None:
        """Can stop mid-walk (generator is truly lazy)."""
        it = iter_entries(nested_tree, EntryKind.FILES, "")
        # take only 1, then close — no exception
        item = next(it)
        it.close()
        assert isinstance(item, MatchEntry)


# ---------------------------------------------------------------------------
# SPEC-14: iter_entries yields identical results to list_entries
# ---------------------------------------------------------------------------

class TestIterEntriesMatchesListEntries:
    """SPEC-14: iterating iter_entries fully produces the same set as list_entries."""

    def test_files_match(self, nested_tree: Path) -> None:
        expected = list_entries(nested_tree, EntryKind.FILES, "")
        actual = list(iter_entries(nested_tree, EntryKind.FILES, ""))
        assert actual == expected

    def test_files_with_seed(self, nested_tree: Path) -> None:
        expected = list_entries(nested_tree, EntryKind.FILES, "data")
        actual = list(iter_entries(nested_tree, EntryKind.FILES, "data"))
        assert actual == expected

    def test_folders_match(self, nested_tree: Path) -> None:
        expected = list_entries(nested_tree, EntryKind.FOLDERS, "")
        actual = list(iter_entries(nested_tree, EntryKind.FOLDERS, ""))
        assert actual == expected

    def test_match_mode_glob(self, flat_tree: Path) -> None:
        expected = list_entries(flat_tree, EntryKind.FILES, "*.txt", match_mode="glob")
        actual = list(iter_entries(flat_tree, EntryKind.FILES, "*.txt", match_mode="glob"))
        assert actual == expected

    def test_match_mode_regex(self, flat_tree: Path) -> None:
        expected = list_entries(flat_tree, EntryKind.FILES, r"^alpha", match_mode="regex")
        actual = list(iter_entries(flat_tree, EntryKind.FILES, r"^alpha", match_mode="regex"))
        assert actual == expected

    def test_empty_tree(self, tmp_path: Path) -> None:
        expected = list_entries(tmp_path, EntryKind.FILES, "")
        actual = list(iter_entries(tmp_path, EntryKind.FILES, ""))
        assert actual == expected


# ---------------------------------------------------------------------------
# SPEC-14: iter_entries raises on bad inputs (same as list_entries)
# ---------------------------------------------------------------------------

class TestIterEntriesRaisesOnBadInput:
    def test_invalid_path(self, tmp_path: Path) -> None:
        bad = tmp_path / "does_not_exist"
        with pytest.raises(ValueError):
            # Must consume the generator to trigger validation
            list(iter_entries(bad, EntryKind.FILES, ""))

    def test_invalid_match_mode(self, flat_tree: Path) -> None:
        with pytest.raises(ValueError):
            list(iter_entries(flat_tree, EntryKind.FILES, "x", match_mode="bad_mode"))

    def test_invalid_regex(self, flat_tree: Path) -> None:
        from ff_explorer.core import InvalidRegexError
        with pytest.raises(InvalidRegexError):
            list(iter_entries(flat_tree, EntryKind.FILES, "[invalid", match_mode="regex"))


# ---------------------------------------------------------------------------
# SPEC-14 dataclasses: SkippedEntry and ListingResult exist and are frozen
# ---------------------------------------------------------------------------

class TestNewDataclasses:
    def test_skipped_entry_frozen(self) -> None:
        s = SkippedEntry(path="/foo", reason="PermissionError")
        assert s.path == "/foo"
        assert s.reason == "PermissionError"
        with pytest.raises((AttributeError, TypeError)):
            s.path = "/bar"  # type: ignore[misc]

    def test_listing_result_frozen(self, flat_tree: Path) -> None:
        result = list_entries_with_report(flat_tree, EntryKind.FILES, "")
        assert isinstance(result, ListingResult)
        with pytest.raises((AttributeError, TypeError)):
            result.entries = []  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SPEC-15: list_entries_with_report on a clean tree
# ---------------------------------------------------------------------------

class TestListEntriesWithReportCleanTree:
    """On a fully readable tree, .entries == list_entries() and .skipped == []."""

    def test_entries_match_list_entries(self, nested_tree: Path) -> None:
        expected = list_entries(nested_tree, EntryKind.FILES, "")
        result = list_entries_with_report(nested_tree, EntryKind.FILES, "")
        assert isinstance(result, ListingResult)
        assert result.entries == expected

    def test_skipped_empty_on_clean_tree(self, nested_tree: Path) -> None:
        result = list_entries_with_report(nested_tree, EntryKind.FILES, "")
        assert result.skipped == []

    def test_folders_clean(self, nested_tree: Path) -> None:
        expected = list_entries(nested_tree, EntryKind.FOLDERS, "")
        result = list_entries_with_report(nested_tree, EntryKind.FOLDERS, "")
        assert result.entries == expected
        assert result.skipped == []


# ---------------------------------------------------------------------------
# SPEC-15: os.walk onerror — permission error entering a subdir
# ---------------------------------------------------------------------------

class TestSkipReportOnerror:
    """SPEC-15: a permission error reported by os.walk onerror is captured."""

    def test_onerror_captured_in_skipped(self, nested_tree: Path) -> None:
        """Simulate os.walk calling onerror for a permission-denied subdir."""
        real_walk = os.walk

        def patched_walk(root, onerror=None, **kwargs):
            # yield the root level normally
            for item in real_walk(root, **kwargs):
                yield item
                break  # only yield root, then inject an error
            # Inject a fake PermissionError as if entering a subdir failed
            if onerror is not None:
                fake_exc = PermissionError(13, "Permission denied", str(nested_tree / "sub"))
                onerror(fake_exc)

        with patch("ff_explorer.core.os.walk", side_effect=patched_walk):
            result = list_entries_with_report(nested_tree, EntryKind.FILES, "")

        assert len(result.skipped) >= 1
        reasons = [s.reason for s in result.skipped]
        assert any("Permission" in r or "PermissionError" in r for r in reasons), (
            f"Expected PermissionError in skip reasons, got: {reasons}"
        )

    def test_walk_completes_despite_onerror(self, nested_tree: Path) -> None:
        """Walk returns readable entries even when onerror is triggered."""
        real_walk = os.walk

        def patched_walk(root, onerror=None, **kwargs):
            for item in real_walk(root, **kwargs):
                yield item
            # inject error AFTER all items yielded — walk still completed
            if onerror is not None:
                fake_exc = PermissionError(13, "Permission denied", "/secret")
                onerror(fake_exc)

        with patch("ff_explorer.core.os.walk", side_effect=patched_walk):
            result = list_entries_with_report(nested_tree, EntryKind.FILES, "")

        # All real entries are still present
        expected = list_entries(nested_tree, EntryKind.FILES, "")
        assert result.entries == expected
        assert len(result.skipped) == 1

    def test_no_exception_escapes(self, nested_tree: Path) -> None:
        """list_entries_with_report never raises on a walk error — it collects it."""
        real_walk = os.walk

        def patched_walk(root, onerror=None, **kwargs):
            yield from real_walk(root, **kwargs)
            if onerror is not None:
                onerror(PermissionError(13, "denied", "/forbidden"))

        with patch("ff_explorer.core.os.walk", side_effect=patched_walk):
            # Must not raise
            result = list_entries_with_report(nested_tree, EntryKind.FILES, "")
        assert isinstance(result, ListingResult)


# ---------------------------------------------------------------------------
# SPEC-15: stat OSError on a file/folder entry — captured in _skipped
# ---------------------------------------------------------------------------

class TestSkipReportStatError:
    """SPEC-15: OSError on entry.stat() populates _skipped when _skipped provided."""

    def test_stat_oserror_on_file_captured(self, flat_tree: Path) -> None:
        """When a file's stat raises OSError, it appears in skipped."""
        original_stat = Path.stat
        # Pick a specific file to raise on — any file directly inside flat_tree.
        target_file = next(flat_tree.iterdir())

        def flaky_stat(self, *args, **kwargs):
            if self == target_file:
                raise PermissionError(13, "Permission denied", str(self))
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            result = list_entries_with_report(
                flat_tree,
                EntryKind.FILES,
                "",
                min_size=0,  # activate needs_stat path
            )

        # The walk completes; the target file is in skipped
        assert len(result.skipped) >= 1
        skipped_paths = [s.path for s in result.skipped]
        assert str(target_file) in skipped_paths

    def test_stat_oserror_on_folder_captured(self, nested_tree: Path) -> None:
        """When a folder's stat raises OSError in FOLDERS mode, it is skipped."""
        original_stat = Path.stat
        # Target the 'sub' directory inside nested_tree.
        target_dir = nested_tree / "sub"

        def flaky_stat(self, *args, **kwargs):
            if self == target_dir:
                raise PermissionError(13, "Permission denied", str(self))
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            result = list_entries_with_report(
                nested_tree,
                EntryKind.FOLDERS,
                "",
                min_size=0,  # activate needs_stat path
            )

        assert len(result.skipped) >= 1
        skipped_paths = [s.path for s in result.skipped]
        assert str(target_dir) in skipped_paths

    def test_stat_error_without_skipped_list_no_crash(self, flat_tree: Path) -> None:
        """When _skipped is None (list_entries), stat OSError is silently logged."""
        original_stat = Path.stat
        target_file = next(flat_tree.iterdir())

        def flaky_stat(self, *args, **kwargs):
            if self == target_file:
                raise PermissionError(13, "Permission denied", str(self))
            return original_stat(self, *args, **kwargs)

        with patch.object(Path, "stat", flaky_stat):
            # list_entries passes _skipped=None — must not crash
            result = list_entries(flat_tree, EntryKind.FILES, "", min_size=0)
        assert isinstance(result, list)
        # The target file is absent from results (skipped silently)
        result_paths = [e.path for e in result]
        assert target_file not in result_paths


# ---------------------------------------------------------------------------
# SPEC-15: broken symlink does not abort the walk
# ---------------------------------------------------------------------------

class TestBrokenSymlink:
    @pytest.mark.skipif(
        sys.platform == "win32" and not os.environ.get("CI"),
        reason="Symlink creation may require elevated privileges on Windows",
    )
    def test_broken_symlink_skipped(self, tmp_path: Path) -> None:
        """A broken symlink should not abort the walk."""
        real_file = tmp_path / "real.txt"
        real_file.write_text("hello")
        broken_link = tmp_path / "broken_link.txt"
        try:
            broken_link.symlink_to(tmp_path / "nonexistent_target.txt")
        except (OSError, NotImplementedError):
            pytest.skip("Cannot create symlinks in this environment")

        # list_entries_with_report must complete without raising
        result = list_entries_with_report(tmp_path, EntryKind.FILES, "")
        assert isinstance(result, ListingResult)
        # real.txt should be in entries
        entry_names = [e.path.name for e in result.entries]
        assert "real.txt" in entry_names

    def test_walk_completes_on_os_walk_symlink_error(self, nested_tree: Path) -> None:
        """Walk completes even if os.walk reports a symlink-related error."""
        real_walk = os.walk

        def patched_walk(root, onerror=None, **kwargs):
            yield from real_walk(root, **kwargs)
            if onerror is not None:
                exc = OSError(40, "Too many levels of symbolic links", "/link")
                onerror(exc)

        with patch("ff_explorer.core.os.walk", side_effect=patched_walk):
            result = list_entries_with_report(nested_tree, EntryKind.FILES, "")

        assert isinstance(result, ListingResult)
        assert len(result.skipped) == 1
        assert "Too many levels" in result.skipped[0].reason or "OSError" in result.skipped[0].reason


# ---------------------------------------------------------------------------
# SPEC-15: service passthrough
# ---------------------------------------------------------------------------

class TestServicePassthrough:
    """Service layer exposes iter_entries and list_entries_with_report correctly."""

    def test_service_iter_entries_is_in_all(self) -> None:
        assert "iter_entries" in svc.__all__

    def test_service_list_entries_with_report_is_in_all(self) -> None:
        assert "list_entries_with_report" in svc.__all__

    def test_service_skipped_entry_in_all(self) -> None:
        assert "SkippedEntry" in svc.__all__

    def test_service_listing_result_in_all(self) -> None:
        assert "ListingResult" in svc.__all__

    def test_service_iter_entries_returns_generator(self, flat_tree: Path) -> None:
        it = svc.iter_entries(str(flat_tree), 1, "")
        assert inspect.isgenerator(it)

    def test_service_list_entries_with_report_returns_listing_result(
        self, nested_tree: Path
    ) -> None:
        result = svc.list_entries_with_report(str(nested_tree), 1, "")
        assert isinstance(result, ListingResult)
        assert result.skipped == []

    def test_service_iter_entries_matches_list_entries(self, nested_tree: Path) -> None:
        expected = svc.list_entries(str(nested_tree), 1, "data")
        actual = list(svc.iter_entries(str(nested_tree), 1, "data"))
        assert actual == expected

    def test_service_list_entries_with_report_entries_match(
        self, nested_tree: Path
    ) -> None:
        expected = svc.list_entries(str(nested_tree), 1, "")
        result = svc.list_entries_with_report(str(nested_tree), 1, "")
        assert result.entries == expected


# ---------------------------------------------------------------------------
# Package __init__ re-exports
# ---------------------------------------------------------------------------

class TestPackageExports:
    def test_iter_entries_exported(self) -> None:
        import ff_explorer
        assert hasattr(ff_explorer, "iter_entries")
        assert "iter_entries" in ff_explorer.__all__

    def test_list_entries_with_report_exported(self) -> None:
        import ff_explorer
        assert hasattr(ff_explorer, "list_entries_with_report")
        assert "list_entries_with_report" in ff_explorer.__all__

    def test_skipped_entry_exported(self) -> None:
        import ff_explorer
        assert hasattr(ff_explorer, "SkippedEntry")
        assert "SkippedEntry" in ff_explorer.__all__

    def test_listing_result_exported(self) -> None:
        import ff_explorer
        assert hasattr(ff_explorer, "ListingResult")
        assert "ListingResult" in ff_explorer.__all__
