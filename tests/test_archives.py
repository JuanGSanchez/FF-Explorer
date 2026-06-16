"""
Tests for FFX-I05 — Archive transparency: search inside ZIP/TAR/GZ.

Acceptance criteria verified:
  A1. search_archives=True → a member whose name matches the seed appears with
      the ``<archive_path>!<member/name>`` identifier and ``in_archive=True``.
  A2. search_archives=False (default) → zero archive-internal entries in results
      (byte-for-byte baseline preserved).
  A3. A malformed/truncated archive is skipped without raising; walk continues.
  A4. remove_entries dry-run over the same tree never lists an archive-internal
      member in matched / would_affect.
  A5. compress_entries dry-run over the same tree never lists an archive-internal
      member in matched / would_affect.
  A6. service.list_entries threads search_archives through to the core.
  A7. .tar.gz / .tgz members are found when search_archives=True.
  A8. case_sensitive=False + search_archives=True works for member names.
  A9. match_mode="glob" + search_archives=True works for member names.
  A10. FOLDERS mode with search_archives=True returns no archive members
       (archive transparency applies to FILES mode only).
"""
from __future__ import annotations

import io
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

from ff_explorer.core import (
    EntryKind,
    MatchEntry,
    list_entries,
    remove_entries,
    compress_entries,
)
from ff_explorer.api import service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def zip_archive(tmp_path: Path) -> Path:
    """Create a .zip with members: report_2024.txt, notes.md, subdir/data.csv."""
    zp = tmp_path / "archive.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("report_2024.txt", "report content")
        zf.writestr("notes.md", "notes content")
        zf.writestr("subdir/data.csv", "csv content")
    return tmp_path  # return the root so list_entries can walk it


@pytest.fixture()
def tgz_archive(tmp_path: Path) -> Path:
    """Create a .tar.gz with members: report_2024.txt, other.log."""
    tgz = tmp_path / "archive.tar.gz"
    buf_report = io.BytesIO(b"report content")
    buf_other = io.BytesIO(b"other content")
    with tarfile.open(tgz, "w:gz") as tf:
        ti = tarfile.TarInfo(name="report_2024.txt")
        ti.size = len(b"report content")
        buf_report.seek(0)
        tf.addfile(ti, buf_report)
        ti2 = tarfile.TarInfo(name="other.log")
        ti2.size = len(b"other content")
        buf_other.seek(0)
        tf.addfile(ti2, buf_other)
    return tmp_path


@pytest.fixture()
def tgz_archive_tgz_ext(tmp_path: Path) -> Path:
    """Create a .tgz (same as .tar.gz but different extension)."""
    tgz = tmp_path / "archive.tgz"
    buf = io.BytesIO(b"hello")
    with tarfile.open(tgz, "w:gz") as tf:
        ti = tarfile.TarInfo(name="report_inside.txt")
        ti.size = 5
        buf.seek(0)
        tf.addfile(ti, buf)
    return tmp_path


@pytest.fixture()
def mixed_tree(tmp_path: Path) -> Path:
    """
    Tree with both a real file and an archive containing a matching member:

        tmp_path/
            real_report.txt          (real file, name matches "report")
            container.zip            (contains report_inside.txt — also matches)
            keeper.txt               (real file, does NOT match "report")
    """
    (tmp_path / "real_report.txt").write_text("real")
    (tmp_path / "keeper.txt").write_text("keep")
    zp = tmp_path / "container.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.writestr("report_inside.txt", "inside")
        zf.writestr("unrelated.log", "log")
    return tmp_path


# ---------------------------------------------------------------------------
# A1 — ZIP member appears with archive!member identifier and in_archive=True
# ---------------------------------------------------------------------------

class TestZipMemberFound:
    def test_member_in_results(self, zip_archive):
        results = list_entries(zip_archive, EntryKind.FILES, "report",
                               search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        assert len(archive_hits) == 1, f"Expected 1 archive hit, got: {archive_hits}"
        hit = archive_hits[0]
        assert hit.in_archive is True
        path_str = str(hit.path)
        assert "!" in path_str, f"Expected '!' separator in path, got: {path_str!r}"
        archive_part, member_part = path_str.split("!", 1)
        assert archive_part.endswith("archive.zip")
        assert "report_2024.txt" in member_part

    def test_member_path_format(self, zip_archive):
        """Path has the exact <archive_path>!<member> format."""
        results = list_entries(zip_archive, EntryKind.FILES, "report_2024",
                               search_archives=True)
        hit = next(e for e in results if e.in_archive)
        assert str(hit.path) == str(zip_archive / "archive.zip") + "!report_2024.txt"

    def test_kind_is_files(self, zip_archive):
        results = list_entries(zip_archive, EntryKind.FILES, "report",
                               search_archives=True)
        for hit in (e for e in results if e.in_archive):
            assert hit.kind == EntryKind.FILES

    def test_non_matching_member_absent(self, zip_archive):
        """Member 'notes.md' does not match seed 'report' — must be absent."""
        results = list_entries(zip_archive, EntryKind.FILES, "report",
                               search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        hit_names = [str(e.path).split("!")[-1] for e in archive_hits]
        assert not any("notes" in n for n in hit_names)


# ---------------------------------------------------------------------------
# A2 — Default (search_archives=False) produces zero archive-internal results
# ---------------------------------------------------------------------------

class TestDefaultNoArchiveMembers:
    def test_false_default_no_members(self, zip_archive):
        results = list_entries(zip_archive, EntryKind.FILES, "report")
        assert all(not e.in_archive for e in results), \
            "Default search_archives=False must not yield archive-internal entries"

    def test_explicit_false_no_members(self, zip_archive):
        results = list_entries(zip_archive, EntryKind.FILES, "report",
                               search_archives=False)
        assert all(not e.in_archive for e in results)

    def test_result_count_unchanged(self, mixed_tree):
        """With search_archives=False the count equals only real-fs matches."""
        without = list_entries(mixed_tree, EntryKind.FILES, "report",
                               search_archives=False)
        # Only real_report.txt matches on-disk; archive members must be absent.
        assert len(without) == 1
        assert not without[0].in_archive
        assert "real_report" in str(without[0].path)


# ---------------------------------------------------------------------------
# A3 — Malformed archive is skipped gracefully
# ---------------------------------------------------------------------------

class TestMalformedArchiveSkipped:
    def test_truncated_zip_skipped(self, tmp_path):
        """A truncated .zip file must be skipped; other results still returned."""
        bad_zip = tmp_path / "bad.zip"
        bad_zip.write_bytes(b"PK\x03\x04" + b"\x00" * 10)  # invalid zip body
        real_file = tmp_path / "report.txt"
        real_file.write_text("real")

        # Must not raise; real file still returned
        results = list_entries(tmp_path, EntryKind.FILES, "report",
                               search_archives=True)
        real_hits = [e for e in results if not e.in_archive]
        assert len(real_hits) == 1
        assert "report.txt" in str(real_hits[0].path)

    def test_empty_file_with_zip_ext_skipped(self, tmp_path):
        """A zero-byte file named .zip must not raise."""
        (tmp_path / "empty.zip").write_bytes(b"")
        results = list_entries(tmp_path, EntryKind.FILES, "anything",
                               search_archives=True)
        # Should return without error; no archive-internal entries from empty file
        assert all(not e.in_archive for e in results)

    def test_random_bytes_tar_gz_skipped(self, tmp_path):
        """A .tar.gz file containing random bytes must be skipped gracefully."""
        bad = tmp_path / "bad.tar.gz"
        bad.write_bytes(b"\x1f\x8b" + b"\xff" * 50)  # gzip magic but garbage body
        results = list_entries(tmp_path, EntryKind.FILES, "anything",
                               search_archives=True)
        assert all(not e.in_archive for e in results)


# ---------------------------------------------------------------------------
# A4 — remove_entries dry-run never lists archive-internal members
# ---------------------------------------------------------------------------

class TestRemoveEntriesNoArchiveMembers:
    def test_dry_run_matched_has_no_archive_entries(self, mixed_tree):
        """remove_entries matched/would_affect must contain only real-fs paths."""
        report = remove_entries(mixed_tree, EntryKind.FILES, "report",
                                dry_run=True)
        for p in report.matched:
            assert "!" not in str(p), \
                f"Archive-internal path leaked into remove_entries.matched: {p}"

    def test_would_affect_no_archive_entries(self, mixed_tree):
        report = remove_entries(mixed_tree, EntryKind.FILES, "report",
                                dry_run=True)
        for p in report.would_affect:
            assert "!" not in str(p), \
                f"Archive-internal path leaked into remove_entries.would_affect: {p}"

    def test_remove_never_receives_archive_path_even_with_zip_present(
        self, zip_archive
    ):
        """Even when a zip contains a matching member, remove_entries ignores it."""
        report = remove_entries(zip_archive, EntryKind.FILES, "report",
                                dry_run=True)
        archive_internal = [p for p in report.matched if "!" in str(p)]
        assert archive_internal == [], \
            f"remove_entries must not list archive members: {archive_internal}"


# ---------------------------------------------------------------------------
# A5 — compress_entries dry-run never lists archive-internal members
# ---------------------------------------------------------------------------

class TestCompressEntriesNoArchiveMembers:
    def test_dry_run_matched_has_no_archive_entries(self, mixed_tree):
        report = compress_entries(mixed_tree, EntryKind.FILES, "report",
                                  dry_run=True)
        for p in report.matched:
            assert "!" not in str(p), \
                f"Archive-internal path leaked into compress_entries.matched: {p}"

    def test_would_affect_no_archive_entries(self, mixed_tree):
        report = compress_entries(mixed_tree, EntryKind.FILES, "report",
                                  dry_run=True)
        for p in report.would_affect:
            assert "!" not in str(p), \
                f"Archive-internal path leaked into compress_entries.would_affect: {p}"

    def test_compress_never_receives_archive_path_even_with_zip_present(
        self, zip_archive
    ):
        report = compress_entries(zip_archive, EntryKind.FILES, "report",
                                  dry_run=True)
        archive_internal = [p for p in report.matched if "!" in str(p)]
        assert archive_internal == [], \
            f"compress_entries must not list archive members: {archive_internal}"


# ---------------------------------------------------------------------------
# A6 — service.list_entries threads search_archives through to core
# ---------------------------------------------------------------------------

class TestServicePassthrough:
    def test_service_search_archives_true(self, zip_archive):
        results = service.list_entries(str(zip_archive), 1, "report",
                                       search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        assert len(archive_hits) == 1
        assert "report_2024.txt" in str(archive_hits[0].path)

    def test_service_search_archives_false_default(self, zip_archive):
        results = service.list_entries(str(zip_archive), 1, "report")
        assert all(not e.in_archive for e in results)

    def test_service_returns_match_entry_with_in_archive(self, zip_archive):
        results = service.list_entries(str(zip_archive), 1, "report",
                                       search_archives=True)
        hit = next((e for e in results if e.in_archive), None)
        assert hit is not None
        assert isinstance(hit, MatchEntry)
        assert hit.in_archive is True


# ---------------------------------------------------------------------------
# A7 — .tar.gz and .tgz members found
# ---------------------------------------------------------------------------

class TestTarGzMemberFound:
    def test_tar_gz_member_found(self, tgz_archive):
        results = list_entries(tgz_archive, EntryKind.FILES, "report",
                               search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        assert len(archive_hits) == 1
        assert "report_2024.txt" in str(archive_hits[0].path)
        assert "!" in str(archive_hits[0].path)

    def test_tgz_extension_member_found(self, tgz_archive_tgz_ext):
        results = list_entries(tgz_archive_tgz_ext, EntryKind.FILES, "report",
                               search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        assert len(archive_hits) == 1
        assert "report_inside.txt" in str(archive_hits[0].path)

    def test_non_matching_tar_member_absent(self, tgz_archive):
        """'other.log' does not match seed 'report'."""
        results = list_entries(tgz_archive, EntryKind.FILES, "report",
                               search_archives=True)
        hit_names = [str(e.path).split("!")[-1] for e in results if e.in_archive]
        assert not any("other" in n for n in hit_names)


# ---------------------------------------------------------------------------
# A8 — case_sensitive=False + search_archives=True
# ---------------------------------------------------------------------------

class TestCaseInsensitiveArchive:
    def test_case_insensitive_zip_member(self, tmp_path):
        zp = tmp_path / "ci.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("REPORT_upper.txt", "upper")
            zf.writestr("lower_report.txt", "lower")
        results = list_entries(tmp_path, EntryKind.FILES, "REPORT",
                               case_sensitive=False, search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        hit_names = [str(e.path).split("!")[-1] for e in archive_hits]
        assert "REPORT_upper.txt" in hit_names
        assert "lower_report.txt" in hit_names

    def test_case_sensitive_zip_member_no_false_positive(self, tmp_path):
        zp = tmp_path / "cs.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("REPORT_upper.txt", "upper")
        # seed is lowercase "report"; case_sensitive=True → no match
        results = list_entries(tmp_path, EntryKind.FILES, "report",
                               case_sensitive=True, search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        assert archive_hits == []


# ---------------------------------------------------------------------------
# A9 — match_mode="glob" + search_archives=True
# ---------------------------------------------------------------------------

class TestGlobModeArchive:
    def test_glob_zip_member(self, tmp_path):
        zp = tmp_path / "glob.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("report_2024.txt", "r")
            zf.writestr("report_2023.csv", "r")
            zf.writestr("summary.txt", "s")
        results = list_entries(tmp_path, EntryKind.FILES, "report_*.txt",
                               match_mode="glob", search_archives=True)
        archive_hits = [e for e in results if e.in_archive]
        assert len(archive_hits) == 1
        assert "report_2024.txt" in str(archive_hits[0].path)


# ---------------------------------------------------------------------------
# A10 — FOLDERS mode with search_archives=True returns no archive members
# ---------------------------------------------------------------------------

class TestFoldersModeNoArchiveMembers:
    def test_folders_mode_ignores_archive_contents(self, zip_archive):
        """FOLDERS mode must never yield archive-internal entries."""
        results = list_entries(zip_archive, EntryKind.FOLDERS, "",
                               search_archives=True)
        assert all(not e.in_archive for e in results), \
            "FOLDERS mode must not yield archive-internal entries"


# ---------------------------------------------------------------------------
# MatchEntry backward-compatibility: in_archive defaults to False
# ---------------------------------------------------------------------------

class TestMatchEntryBackwardCompat:
    def test_construction_without_in_archive(self, tmp_path):
        """Existing construction sites (path, kind only) still work."""
        f = tmp_path / "x.txt"
        f.write_text("x")
        entry = MatchEntry(path=f, kind=EntryKind.FILES)
        assert entry.in_archive is False

    def test_in_archive_true_construction(self, tmp_path):
        fake_path = Path("/some/archive.zip!member.txt")
        entry = MatchEntry(path=fake_path, kind=EntryKind.FILES, in_archive=True)
        assert entry.in_archive is True
        assert "!" in str(entry.path)

    def test_str_returns_path_string(self, tmp_path):
        f = tmp_path / "y.txt"
        f.write_text("y")
        entry = MatchEntry(path=f, kind=EntryKind.FILES)
        assert str(entry) == str(f)
