"""
Tests for ff_explorer.index — FFX-I10 real-time name indexing.

All filesystem-event simulation uses direct calls to NameIndex mutators
(add_path / remove_path / move_path) so tests are deterministic and do NOT
require a running watchdog observer or real filesystem-event timing.

Acceptance criteria verified:
1. build() + query() returns names present in the tree.
2. simulated add_path → query reflects the new entry.
3. simulated remove_path → entry gone from query results.
4. simulated move_path → old path gone, new path present.
5. IndexManager.is_indexed / get_index lifecycle.
6. Disabled root (not indexed) → list_entries falls back to live walk.
7. Query consistency: index path and walk path return same name set for a
   plain query with no advanced filters.
8. case_sensitive and match_mode variations (glob, regex, substring).
9. Empty name_seed matches all indexed entries.
10. Invalid regex raises InvalidRegexError from core.
11. start_index → stop_index lifecycle clears the index.
12. start_index on non-existent root raises ValueError.
13. Calling start_index twice returns existing index (no rebuild).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ff_explorer.index import NameIndex, IndexManager
from ff_explorer.core import (
    EntryKind,
    InvalidRegexError,
    list_entries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _names(paths: list[Path]) -> set[str]:
    """Return the set of filenames from a list of paths."""
    return {p.name for p in paths}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def index_tree(tmp_path: Path) -> Path:
    """
    A small tree for index tests:

        tmp_path/
            alpha.txt
            beta.log
            gamma.txt
            sub/
                delta.txt
                epsilon.log
    """
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.log").write_text("b")
    (tmp_path / "gamma.txt").write_text("g")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "delta.txt").write_text("d")
    (sub / "epsilon.log").write_text("e")
    return tmp_path


@pytest.fixture()
def built_index(index_tree: Path) -> NameIndex:
    """Return a NameIndex that has been built on index_tree."""
    idx = NameIndex(index_tree)
    idx.build()
    return idx


# ---------------------------------------------------------------------------
# NameIndex — build and basic query
# ---------------------------------------------------------------------------

class TestNameIndexBuild:
    def test_build_finds_all_files(self, index_tree: Path, built_index: NameIndex):
        result = built_index.query("", case_sensitive=False)
        names = _names(result)
        assert "alpha.txt" in names
        assert "beta.log" in names
        assert "gamma.txt" in names
        assert "delta.txt" in names
        assert "epsilon.log" in names

    def test_build_finds_subdirectory(self, index_tree: Path, built_index: NameIndex):
        result = built_index.query("sub", case_sensitive=False)
        names = _names(result)
        assert "sub" in names

    def test_query_substring_match(self, built_index: NameIndex):
        result = built_index.query("alpha", case_sensitive=True)
        names = _names(result)
        assert "alpha.txt" in names
        assert "beta.log" not in names

    def test_query_empty_seed_matches_all(self, built_index: NameIndex):
        result = built_index.query("", case_sensitive=False)
        # Must include all files + sub dir
        names = _names(result)
        assert "alpha.txt" in names
        assert "epsilon.log" in names
        assert "sub" in names

    def test_query_no_match_returns_empty(self, built_index: NameIndex):
        result = built_index.query("zzznomatch", case_sensitive=False)
        assert result == []

    def test_query_case_insensitive(self, built_index: NameIndex):
        result = built_index.query("ALPHA", case_sensitive=False)
        assert _names(result) == {"alpha.txt"}

    def test_query_case_sensitive_miss(self, built_index: NameIndex):
        result = built_index.query("ALPHA", case_sensitive=True)
        assert result == []

    def test_query_case_sensitive_hit(self, built_index: NameIndex):
        result = built_index.query("alpha", case_sensitive=True)
        assert "alpha.txt" in _names(result)


# ---------------------------------------------------------------------------
# NameIndex — match_mode variations
# ---------------------------------------------------------------------------

class TestNameIndexMatchModes:
    def test_glob_mode(self, built_index: NameIndex):
        result = built_index.query("*.txt", case_sensitive=False, match_mode="glob")
        names = _names(result)
        assert "alpha.txt" in names
        assert "gamma.txt" in names
        assert "delta.txt" in names
        assert "beta.log" not in names
        assert "epsilon.log" not in names

    def test_glob_mode_case_insensitive(self, built_index: NameIndex):
        result = built_index.query("*.TXT", case_sensitive=False, match_mode="glob")
        names = _names(result)
        assert "alpha.txt" in names

    def test_regex_mode(self, built_index: NameIndex):
        result = built_index.query(r"^(alpha|gamma)\.txt$",
                                   case_sensitive=True, match_mode="regex")
        names = _names(result)
        assert names == {"alpha.txt", "gamma.txt"}

    def test_regex_mode_case_insensitive(self, built_index: NameIndex):
        result = built_index.query(r"ALPHA\.TXT",
                                   case_sensitive=False, match_mode="regex")
        assert "alpha.txt" in _names(result)

    def test_invalid_regex_raises(self, built_index: NameIndex):
        with pytest.raises(InvalidRegexError):
            built_index.query("[invalid", case_sensitive=False, match_mode="regex")

    def test_invalid_match_mode_raises(self, built_index: NameIndex):
        with pytest.raises(ValueError):
            built_index.query("x", case_sensitive=False, match_mode="badmode")


# ---------------------------------------------------------------------------
# NameIndex — simulated incremental events
# ---------------------------------------------------------------------------

class TestNameIndexIncrementalEvents:
    def test_add_path_appears_in_query(self, built_index: NameIndex, index_tree: Path):
        """Simulated create event: add_path → query reflects the new entry."""
        new_file = index_tree / "new_file.txt"
        new_file.write_text("new")
        built_index.add_path(new_file)

        result = built_index.query("new_file", case_sensitive=False)
        assert new_file.resolve() in result

    def test_remove_path_gone_from_query(self, built_index: NameIndex, index_tree: Path):
        """Simulated delete event: remove_path → entry no longer in results."""
        target = index_tree / "alpha.txt"
        built_index.remove_path(target)

        result = built_index.query("alpha", case_sensitive=False)
        assert target.resolve() not in result

    def test_move_path_old_gone_new_present(self, built_index: NameIndex, index_tree: Path):
        """Simulated rename event: old path gone, new path present."""
        src = index_tree / "beta.log"
        dst = index_tree / "beta_renamed.log"

        built_index.move_path(src, dst)

        old_results = built_index.query("beta.log", case_sensitive=False)
        assert src.resolve() not in old_results

        new_results = built_index.query("beta_renamed", case_sensitive=False)
        assert dst.resolve() in new_results

    def test_add_directory_appears_in_query(self, built_index: NameIndex, index_tree: Path):
        """Directories can be added and queried."""
        new_dir = index_tree / "new_subdir"
        new_dir.mkdir()
        built_index.add_path(new_dir)

        result = built_index.query("new_subdir", case_sensitive=False)
        assert new_dir.resolve() in result

    def test_remove_nonexistent_path_is_noop(self, built_index: NameIndex, index_tree: Path):
        """Removing a path not in the index should not raise."""
        ghost = index_tree / "ghost_file.txt"
        # Should not raise
        built_index.remove_path(ghost)

    def test_multiple_add_same_name_different_path(self, built_index: NameIndex, index_tree: Path):
        """Two files with the same name in different dirs both appear."""
        sub2 = index_tree / "sub2"
        sub2.mkdir()
        extra = sub2 / "alpha.txt"
        extra.write_text("extra")
        built_index.add_path(extra)

        result = built_index.query("alpha.txt", case_sensitive=False)
        resolved = {p.resolve() for p in result}
        assert (index_tree / "alpha.txt").resolve() in resolved
        assert extra.resolve() in resolved


# ---------------------------------------------------------------------------
# IndexManager lifecycle
# ---------------------------------------------------------------------------

class TestIndexManagerLifecycle:
    def test_start_index_creates_index(self, index_tree: Path):
        try:
            idx = IndexManager.start_index(index_tree)
            assert IndexManager.is_indexed(index_tree)
            assert IndexManager.get_index(index_tree) is idx
        finally:
            IndexManager.stop_index(index_tree)

    def test_stop_index_clears_entry(self, index_tree: Path):
        IndexManager.start_index(index_tree)
        IndexManager.stop_index(index_tree)
        assert not IndexManager.is_indexed(index_tree)
        assert IndexManager.get_index(index_tree) is None

    def test_start_index_twice_returns_same(self, index_tree: Path):
        try:
            idx1 = IndexManager.start_index(index_tree)
            idx2 = IndexManager.start_index(index_tree)
            assert idx1 is idx2
        finally:
            IndexManager.stop_index(index_tree)

    def test_stop_index_not_started_is_noop(self, tmp_path: Path):
        # Should not raise even if the root was never indexed.
        IndexManager.stop_index(tmp_path / "nonexistent_root")

    def test_is_indexed_false_when_not_started(self, tmp_path: Path):
        assert not IndexManager.is_indexed(tmp_path / "not_indexed")

    def test_get_index_none_when_not_started(self, tmp_path: Path):
        assert IndexManager.get_index(tmp_path / "not_indexed") is None

    def test_start_index_nonexistent_root_raises(self, tmp_path: Path):
        bad = tmp_path / "does_not_exist"
        with pytest.raises(ValueError, match="existing directory"):
            IndexManager.start_index(bad)

    def test_start_index_builds_queryable_index(self, index_tree: Path):
        try:
            idx = IndexManager.start_index(index_tree)
            result = idx.query("alpha", case_sensitive=False)
            assert "alpha.txt" in _names(result)
        finally:
            IndexManager.stop_index(index_tree)


# ---------------------------------------------------------------------------
# list_entries index routing — integration with core
# ---------------------------------------------------------------------------

class TestListEntriesIndexRouting:
    def test_indexed_root_returns_correct_files(self, index_tree: Path):
        """With indexing enabled, list_entries returns results from the index."""
        try:
            IndexManager.start_index(index_tree)
            results = list_entries(index_tree, EntryKind.FILES, "alpha",
                                   case_sensitive=False)
            paths = {r.path for r in results}
            assert any(p.name == "alpha.txt" for p in paths)
            # Non-matching names must NOT appear
            assert not any(p.name == "beta.log" for p in paths)
        finally:
            IndexManager.stop_index(index_tree)

    def test_indexed_root_returns_correct_folders(self, index_tree: Path):
        """list_entries FOLDERS mode routes through the index correctly."""
        try:
            IndexManager.start_index(index_tree)
            results = list_entries(index_tree, EntryKind.FOLDERS, "sub",
                                   case_sensitive=False)
            names = {r.path.name for r in results}
            assert "sub" in names
        finally:
            IndexManager.stop_index(index_tree)

    def test_unindexed_root_falls_back_to_walk(self, index_tree: Path):
        """With indexing disabled, list_entries uses the live walk baseline."""
        # Ensure NOT indexed
        if IndexManager.is_indexed(index_tree):
            IndexManager.stop_index(index_tree)

        results = list_entries(index_tree, EntryKind.FILES, "alpha",
                               case_sensitive=False)
        assert any(r.path.name == "alpha.txt" for r in results)

    def test_query_consistency_index_vs_walk(self, index_tree: Path):
        """Index path and walk path return the same name set for a plain query."""
        try:
            IndexManager.start_index(index_tree)
            index_results = list_entries(index_tree, EntryKind.FILES, ".txt",
                                         case_sensitive=False)
            index_names = {r.path.name for r in index_results}

            IndexManager.stop_index(index_tree)
            walk_results = list_entries(index_tree, EntryKind.FILES, ".txt",
                                        case_sensitive=False)
            walk_names = {r.path.name for r in walk_results}

            assert index_names == walk_names
        finally:
            if IndexManager.is_indexed(index_tree):
                IndexManager.stop_index(index_tree)

    def test_advanced_filter_falls_back_to_walk(self, index_tree: Path):
        """
        When an advanced filter (size/date/ext) is active, list_entries falls
        back to the live walk even when the root is indexed.
        """
        try:
            IndexManager.start_index(index_tree)
            # min_size triggers needs_stat → fall back to walk
            results = list_entries(index_tree, EntryKind.FILES, "alpha",
                                   case_sensitive=False, min_size=0)
            # Must still return correct results (walk handles it)
            assert any(r.path.name == "alpha.txt" for r in results)
        finally:
            IndexManager.stop_index(index_tree)

    def test_simulated_event_reflected_in_next_query(self, index_tree: Path):
        """
        After a simulated add event on the index, the next list_entries call
        (routed through the index) reflects the change WITHOUT a full re-walk.
        """
        try:
            idx = IndexManager.start_index(index_tree)

            # Simulate creation of a new file
            new_file = index_tree / "freshly_created.txt"
            new_file.write_text("fresh")
            idx.add_path(new_file)  # simulate the watchdog on_created event

            results = list_entries(index_tree, EntryKind.FILES, "freshly_created",
                                   case_sensitive=False)
            assert any(r.path.name == "freshly_created.txt" for r in results)
        finally:
            IndexManager.stop_index(index_tree)

    def test_simulated_remove_reflected_in_next_query(self, index_tree: Path):
        """
        After a simulated remove event, the next query does NOT return the
        deleted entry (no re-walk needed).
        """
        try:
            idx = IndexManager.start_index(index_tree)

            target = index_tree / "alpha.txt"
            idx.remove_path(target)  # simulate the watchdog on_deleted event

            results = list_entries(index_tree, EntryKind.FILES, "alpha",
                                   case_sensitive=False)
            assert not any(r.path.name == "alpha.txt" for r in results)
        finally:
            IndexManager.stop_index(index_tree)

    def test_content_query_falls_back_to_walk(self, index_tree: Path):
        """content_query active → fall back to walk (index does not model content)."""
        try:
            IndexManager.start_index(index_tree)
            # content_query requires a name/type prefilter too (FFX-I09 gate)
            results = list_entries(index_tree, EntryKind.FILES, "alpha",
                                   case_sensitive=False,
                                   content_query="a")
            assert any(r.path.name == "alpha.txt" for r in results)
        finally:
            IndexManager.stop_index(index_tree)

    def test_search_archives_falls_back_to_walk(self, index_tree: Path):
        """search_archives=True → fall back to walk."""
        try:
            IndexManager.start_index(index_tree)
            # No archives in the tree — just verify it doesn't crash
            results = list_entries(index_tree, EntryKind.FILES, "alpha",
                                   case_sensitive=False, search_archives=True)
            assert any(r.path.name == "alpha.txt" for r in results)
        finally:
            IndexManager.stop_index(index_tree)
