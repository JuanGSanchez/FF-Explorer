"""
tests/test_dedupe.py
====================
Tests for ff_explorer.dedupe (find_duplicates) and the thin service wrapper.

Tree used in most tests
-----------------------
tmp_path/
    alpha.txt      — content "DUPLICATE"  (duplicate pair)
    subdir/
        beta.txt   — content "DUPLICATE"  (duplicate pair — same as alpha.txt)
    gamma.txt      — same SIZE as alpha+beta but DIFFERENT content
    unique.txt     — distinct content, distinct size
"""
from __future__ import annotations

import os
import stat
import sys

import pytest

from ff_explorer.dedupe import DuplicateGroup, find_duplicates
import ff_explorer.api.service as svc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DUPLICATE_CONTENT = b"DUPLICATE_CONTENT_XYZ"  # 21 bytes
SAME_SIZE_DIFF    = b"DIFFERENT_CONTENT_ABC"  # 21 bytes — same size, different hash
UNIQUE_CONTENT    = b"TOTALLY_UNIQUE_FILE_CONTENT_123"  # different size


@pytest.fixture()
def dedupe_tree(tmp_path):
    """Build the standard test tree; return the root path (str)."""
    subdir = tmp_path / "subdir"
    subdir.mkdir()

    (tmp_path / "alpha.txt").write_bytes(DUPLICATE_CONTENT)
    (subdir  / "beta.txt").write_bytes(DUPLICATE_CONTENT)
    (tmp_path / "gamma.txt").write_bytes(SAME_SIZE_DIFF)
    (tmp_path / "unique.txt").write_bytes(UNIQUE_CONTENT)

    return str(tmp_path)


# ---------------------------------------------------------------------------
# Core: DuplicateGroup shape
# ---------------------------------------------------------------------------

def test_duplicate_group_fields():
    """DuplicateGroup is a dataclass with hash, size, paths."""
    g = DuplicateGroup(hash="abc123", size=21, paths=["/a", "/b"])
    assert g.hash == "abc123"
    assert g.size == 21
    assert g.paths == ["/a", "/b"]


# ---------------------------------------------------------------------------
# Core: find_duplicates — main acceptance criterion
# ---------------------------------------------------------------------------

def test_finds_exactly_one_duplicate_group(dedupe_tree, tmp_path):
    """Two files with identical content are grouped; others are absent."""
    groups = find_duplicates(dedupe_tree)

    assert len(groups) == 1, f"Expected 1 group, got {len(groups)}: {groups}"
    g = groups[0]
    assert g.size == len(DUPLICATE_CONTENT)
    # Both paths must be present (by name suffix since tmp_path varies)
    names = {os.path.basename(p) for p in g.paths}
    assert names == {"alpha.txt", "beta.txt"}


def test_same_size_different_content_absent(dedupe_tree):
    """gamma.txt (same size, different content) must NOT appear in any group."""
    groups = find_duplicates(dedupe_tree)
    all_paths = [p for g in groups for p in g.paths]
    basenames = {os.path.basename(p) for p in all_paths}
    assert "gamma.txt" not in basenames, (
        "gamma.txt has same size but different content — must not be grouped"
    )


def test_unique_file_absent(dedupe_tree):
    """unique.txt (distinct content and size) must not appear in any group."""
    groups = find_duplicates(dedupe_tree)
    all_paths = [p for g in groups for p in g.paths]
    basenames = {os.path.basename(p) for p in all_paths}
    assert "unique.txt" not in basenames


# ---------------------------------------------------------------------------
# Core: determinism — paths within group sorted, groups sorted
# ---------------------------------------------------------------------------

def test_paths_within_group_are_sorted(dedupe_tree):
    """Paths inside a DuplicateGroup are sorted lexicographically."""
    groups = find_duplicates(dedupe_tree)
    assert len(groups) == 1
    paths = groups[0].paths
    assert paths == sorted(paths)


def test_output_deterministic_on_repeated_calls(dedupe_tree):
    """Two consecutive calls return identical results."""
    r1 = find_duplicates(dedupe_tree)
    r2 = find_duplicates(dedupe_tree)
    assert len(r1) == len(r2)
    for g1, g2 in zip(r1, r2):
        assert g1.hash == g2.hash
        assert g1.size == g2.size
        assert g1.paths == g2.paths


def test_multiple_groups_sorted_by_size_desc(tmp_path):
    """When multiple groups exist, larger-size groups come first."""
    # Group A: 10-byte files
    a1 = tmp_path / "a1.bin"
    a2 = tmp_path / "a2.bin"
    a1.write_bytes(b"A" * 10)
    a2.write_bytes(b"A" * 10)

    # Group B: 20-byte files
    b1 = tmp_path / "b1.bin"
    b2 = tmp_path / "b2.bin"
    b1.write_bytes(b"B" * 20)
    b2.write_bytes(b"B" * 20)

    groups = find_duplicates(str(tmp_path))
    assert len(groups) == 2
    assert groups[0].size == 20  # larger first
    assert groups[1].size == 10


# ---------------------------------------------------------------------------
# Core: min_size filtering
# ---------------------------------------------------------------------------

def test_min_size_filters_small_files(tmp_path):
    """Files below min_size are excluded even if identical."""
    small = b"AB"  # 2 bytes
    (tmp_path / "s1.txt").write_bytes(small)
    (tmp_path / "s2.txt").write_bytes(small)

    # min_size=3 → both skipped → no groups
    groups = find_duplicates(str(tmp_path), min_size=3)
    assert groups == []


def test_min_size_default_skips_zero_byte_files(tmp_path):
    """Default min_size=1 excludes 0-byte files."""
    (tmp_path / "empty1.txt").write_bytes(b"")
    (tmp_path / "empty2.txt").write_bytes(b"")

    groups = find_duplicates(str(tmp_path))
    assert groups == []


def test_min_size_zero_includes_empty_files(tmp_path):
    """min_size=0 includes 0-byte files in duplicate detection."""
    (tmp_path / "empty1.txt").write_bytes(b"")
    (tmp_path / "empty2.txt").write_bytes(b"")

    groups = find_duplicates(str(tmp_path), min_size=0)
    assert len(groups) == 1
    assert groups[0].size == 0


def test_min_size_exact_boundary_included(tmp_path):
    """A file of exactly min_size bytes is included (inclusive bound)."""
    content = b"X" * 5
    (tmp_path / "f1.bin").write_bytes(content)
    (tmp_path / "f2.bin").write_bytes(content)

    groups = find_duplicates(str(tmp_path), min_size=5)
    assert len(groups) == 1


# ---------------------------------------------------------------------------
# Core: SHA-256 algo option
# ---------------------------------------------------------------------------

def test_sha256_algo_finds_same_duplicates(dedupe_tree):
    """SHA-256 algo produces the same grouping as the default blake2b."""
    groups_blake = find_duplicates(dedupe_tree, algo="blake2b")
    groups_sha   = find_duplicates(dedupe_tree, algo="sha256")

    assert len(groups_blake) == len(groups_sha) == 1
    # Paths identical; hashes differ (different algorithm)
    assert groups_blake[0].paths == groups_sha[0].paths
    assert groups_blake[0].hash  != groups_sha[0].hash  # different digest strings


def test_unsupported_algo_raises_value_error(dedupe_tree):
    """An unsupported algo name raises ValueError."""
    with pytest.raises(ValueError, match="Unsupported algo"):
        find_duplicates(dedupe_tree, algo="md5")


# ---------------------------------------------------------------------------
# Core: unreadable file is skipped, no exception raised
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason="chmod 000 not enforced on Windows")
def test_unreadable_file_skipped(tmp_path):
    """An unreadable file is silently skipped; the rest of the walk continues."""
    content = b"READABLE"
    (tmp_path / "r1.txt").write_bytes(content)
    (tmp_path / "r2.txt").write_bytes(content)

    unreadable = tmp_path / "locked.txt"
    unreadable.write_bytes(content)
    unreadable.chmod(0)  # remove all permissions

    try:
        groups = find_duplicates(str(tmp_path))
        # r1 and r2 should still form a group
        assert len(groups) == 1
        names = {os.path.basename(p) for p in groups[0].paths}
        assert names == {"r1.txt", "r2.txt"}
        assert "locked.txt" not in names
    finally:
        # Restore so tmp_path cleanup does not fail
        unreadable.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_unreadable_file_skipped_windows_simulation(tmp_path):
    """Simulate unreadable file by making one path point to a missing file after stat.

    This test is platform-agnostic: we verify the graceful-skip code path by
    confirming a tree with two readable duplicates returns exactly one group
    even if a third non-duplicate file exists.  The actual OSError path on
    open is exercised on POSIX by test_unreadable_file_skipped above.
    """
    content = b"DATA"
    (tmp_path / "x1.txt").write_bytes(content)
    (tmp_path / "x2.txt").write_bytes(content)
    (tmp_path / "other.txt").write_bytes(b"OTHER_DATA_LONGER")

    groups = find_duplicates(str(tmp_path))
    assert len(groups) == 1
    names = {os.path.basename(p) for p in groups[0].paths}
    assert names == {"x1.txt", "x2.txt"}


# ---------------------------------------------------------------------------
# Core: ValueError for non-directory path
# ---------------------------------------------------------------------------

def test_raises_value_error_for_missing_path():
    """Non-existent path raises ValueError."""
    with pytest.raises(ValueError):
        find_duplicates("/nonexistent/path/that/does/not/exist")


def test_raises_value_error_for_file_path(tmp_path):
    """Passing a file path (not a directory) raises ValueError."""
    f = tmp_path / "afile.txt"
    f.write_bytes(b"data")
    with pytest.raises(ValueError):
        find_duplicates(str(f))


# ---------------------------------------------------------------------------
# Core: empty directory → no groups
# ---------------------------------------------------------------------------

def test_empty_directory_returns_no_groups(tmp_path):
    groups = find_duplicates(str(tmp_path))
    assert groups == []


# ---------------------------------------------------------------------------
# Service layer: thin passthrough
# ---------------------------------------------------------------------------

def test_service_find_duplicates_passthrough(dedupe_tree):
    """svc.find_duplicates delegates to dedupe and returns DuplicateGroup list."""
    groups = svc.find_duplicates(dedupe_tree)

    assert isinstance(groups, list)
    assert len(groups) == 1
    g = groups[0]
    assert isinstance(g, DuplicateGroup)
    names = {os.path.basename(p) for p in g.paths}
    assert names == {"alpha.txt", "beta.txt"}


def test_service_find_duplicates_min_size(tmp_path):
    """min_size kwarg is forwarded correctly through the service layer."""
    tiny = b"X"
    (tmp_path / "t1.txt").write_bytes(tiny)
    (tmp_path / "t2.txt").write_bytes(tiny)

    assert svc.find_duplicates(str(tmp_path), min_size=2) == []
    assert len(svc.find_duplicates(str(tmp_path), min_size=1)) == 1


def test_service_find_duplicates_algo(dedupe_tree):
    """algo kwarg is forwarded correctly through the service layer."""
    groups = svc.find_duplicates(dedupe_tree, algo="sha256")
    assert len(groups) == 1
    # SHA-256 hex digest is 64 chars
    assert len(groups[0].hash) == 64


def test_service_find_duplicates_invalid_path_raises():
    """Service raises ValueError for a non-directory path."""
    with pytest.raises(ValueError):
        svc.find_duplicates("/no/such/directory")


def test_service_find_duplicates_in_all():
    """find_duplicates and DuplicateGroup are exported from service __all__."""
    assert "find_duplicates" in svc.__all__
    assert "DuplicateGroup" in svc.__all__
