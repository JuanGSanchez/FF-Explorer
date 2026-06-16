"""
tests/test_versioning.py
========================
Acceptance tests for FFX-I08 — versioned safe-delete.

Covered:
  1. versioning=True + dry_run=False + confirm=True:
       matched files are MOVED under <path>/.ffe-versions/<ts>/ with relative
       structure preserved; sources are gone; report reflects removal.
  2. versioning=True + dry_run=True (default):
       NOTHING moved (preview only); .ffe-versions not created.
  3. versioning=True + dry_run=False + confirm=False:
       ValueError raised; NOTHING moved.
  4. blank seed → EmptySeedError (gate unchanged).
  5. versioning=False (default):
       .ffe-versions dir NOT created; send2trash path used (mocked).
  6. second removal run does not re-target items already in .ffe-versions.
  7. versioned_to field on RemovalReport is populated correctly.
  8. service.py passthrough threads versioning correctly.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from ff_explorer.core import (
    EntryKind,
    EmptySeedError,
    remove_entries,
)
import ff_explorer.api.service as service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def vtree(tmp_path: Path) -> Path:
    """
    Simple tree for versioning tests:

        tmp_path/
            alpha.txt
            beta.txt
            sub/
                alpha_nested.txt
    """
    (tmp_path / "alpha.txt").write_text("alpha content")
    (tmp_path / "beta.txt").write_text("beta content")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "alpha_nested.txt").write_text("nested alpha")
    return tmp_path


# ---------------------------------------------------------------------------
# 1. versioning=True, live run: files moved into .ffe-versions/<ts>/ structure
# ---------------------------------------------------------------------------

class TestVersioningLiveRun:
    def test_sources_are_gone(self, vtree):
        """Matched files no longer exist at their original paths."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        assert not (vtree / "alpha.txt").exists()
        assert not (vtree / "sub" / "alpha_nested.txt").exists()
        # beta.txt was NOT matched — must still exist
        assert (vtree / "beta.txt").exists()

    def test_report_removed_populated(self, vtree):
        """report.removed lists the paths that were moved away."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        assert len(report.removed) == 2
        assert len(report.failed) == 0

    def test_relative_structure_preserved_root_file(self, vtree):
        """alpha.txt (root-level) lands directly under the version timestamp dir."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha.txt",
            dry_run=False, confirm=True, versioning=True,
        )
        version_dir = Path(report.versioned_to)
        dest = version_dir / "alpha.txt"
        assert dest.exists(), f"Expected versioned file at {dest}"
        assert dest.read_text() == "alpha content"

    def test_relative_structure_preserved_nested_file(self, vtree):
        """alpha_nested.txt (in sub/) lands under version_dir/sub/alpha_nested.txt."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        version_dir = Path(report.versioned_to)
        dest = version_dir / "sub" / "alpha_nested.txt"
        assert dest.exists(), f"Expected versioned file at {dest}"
        assert dest.read_text() == "nested alpha"

    def test_version_dir_is_under_ffe_versions(self, vtree):
        """The version directory is <root>/.ffe-versions/<YYYYMMDD-HHMMSS>."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        version_dir = Path(report.versioned_to)
        assert version_dir.parent == vtree / ".ffe-versions"
        # Timestamp format: YYYYMMDD-HHMMSS
        ts_name = version_dir.name
        assert re.fullmatch(r"\d{8}-\d{6}", ts_name), (
            f"Unexpected timestamp format: {ts_name!r}"
        )

    def test_versioned_to_field_set(self, vtree):
        """report.versioned_to is a non-None string naming the version dir."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        assert report.versioned_to is not None
        assert isinstance(report.versioned_to, str)

    def test_all_items_same_timestamp_dir(self, vtree):
        """All items in a single call land under the same timestamp directory."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        version_dir = Path(report.versioned_to)
        # Both removed paths should resolve under version_dir
        for p in report.removed:
            rel = p.relative_to(vtree)
            assert (version_dir / rel).exists()


# ---------------------------------------------------------------------------
# 2. versioning=True + dry_run=True: NOTHING moved, no .ffe-versions created
# ---------------------------------------------------------------------------

class TestVersioningDryRun:
    def test_dry_run_moves_nothing(self, vtree):
        """With dry_run=True, no files are moved regardless of versioning flag."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=True, versioning=True,
        )
        # Sources still exist
        assert (vtree / "alpha.txt").exists()
        assert (vtree / "sub" / "alpha_nested.txt").exists()

    def test_dry_run_ffe_versions_not_created(self, vtree):
        """The .ffe-versions directory is NOT created on a dry run."""
        remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=True, versioning=True,
        )
        assert not (vtree / ".ffe-versions").exists()

    def test_dry_run_report_fields(self, vtree):
        """dry_run report has matched populated, removed empty, versioned_to None."""
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=True, versioning=True,
        )
        assert report.dry_run is True
        assert len(report.matched) == 2
        assert report.removed == []
        assert report.versioned_to is None


# ---------------------------------------------------------------------------
# 3. versioning=True + dry_run=False + confirm=False → ValueError, nothing moved
# ---------------------------------------------------------------------------

class TestVersioningGateEnforced:
    def test_no_confirm_raises_value_error(self, vtree):
        """The gate (confirm required when not dry_run) still applies with versioning."""
        with pytest.raises(ValueError):
            remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=False, versioning=True,
            )

    def test_no_confirm_nothing_moved(self, vtree):
        """Nothing is moved when ValueError is raised."""
        try:
            remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=False, versioning=True,
            )
        except ValueError:
            pass
        assert (vtree / "alpha.txt").exists()
        assert not (vtree / ".ffe-versions").exists()


# ---------------------------------------------------------------------------
# 4. blank seed → EmptySeedError (gate unchanged)
# ---------------------------------------------------------------------------

class TestVersioningBlankSeed:
    def test_blank_seed_raises_empty_seed_error(self, vtree):
        """EmptySeedError is raised for a blank seed regardless of versioning."""
        with pytest.raises(EmptySeedError):
            remove_entries(
                vtree, EntryKind.FILES, "",
                dry_run=False, confirm=True, versioning=True,
            )

    def test_whitespace_seed_raises_empty_seed_error(self, vtree):
        with pytest.raises(EmptySeedError):
            remove_entries(
                vtree, EntryKind.FILES, "   ",
                dry_run=False, confirm=True, versioning=True,
            )


# ---------------------------------------------------------------------------
# 5. versioning=False (default): send2trash path used; .ffe-versions NOT created
# ---------------------------------------------------------------------------

class TestVersioningFalseDefault:
    def test_send2trash_called_not_shutil_move(self, vtree):
        """With versioning=False, send2trash is invoked (not the versioning branch)."""
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=True, versioning=False,
            )
        assert mock_trash.called
        assert len(report.removed) == 2

    def test_ffe_versions_not_created_when_versioning_false(self, vtree):
        """The .ffe-versions directory is NOT created when versioning=False."""
        with patch("ff_explorer.core._send2trash"), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=True, versioning=False,
            )
        assert not (vtree / ".ffe-versions").exists()

    def test_versioned_to_is_none_when_versioning_false(self, vtree):
        """report.versioned_to is None when versioning=False."""
        with patch("ff_explorer.core._send2trash"), \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=True, versioning=False,
            )
        assert report.versioned_to is None

    def test_default_versioning_param_is_false(self, vtree):
        """Calling remove_entries without versioning= uses the False default."""
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=True,
            )
        assert mock_trash.called
        assert report.versioned_to is None


# ---------------------------------------------------------------------------
# 6. second removal run does not re-target items already in .ffe-versions
# ---------------------------------------------------------------------------

class TestVersioningNoRetarget:
    def test_second_run_does_not_match_ffe_versions_contents(self, vtree):
        """Items in .ffe-versions are excluded from subsequent remove_entries calls."""
        # First run: version alpha.txt
        report1 = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        assert len(report1.removed) == 2

        # Confirm items are in .ffe-versions
        version_dir = Path(report1.versioned_to)
        assert (version_dir / "alpha.txt").exists()

        # Second run with same seed: .ffe-versions contents must NOT be matched
        report2 = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        # Nothing new should be matched (originals are gone; versioned copies excluded)
        assert len(report2.matched) == 0
        assert len(report2.removed) == 0

    def test_dry_run_second_pass_excludes_ffe_versions(self, vtree):
        """Even a dry_run after a live versioning run excludes .ffe-versions."""
        # First live run
        remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        # Dry-run second pass: matched should be empty
        report = remove_entries(
            vtree, EntryKind.FILES, "alpha",
            dry_run=True, versioning=True,
        )
        assert len(report.matched) == 0


# ---------------------------------------------------------------------------
# 7. OSError during versioned move lands in report.failed
# ---------------------------------------------------------------------------

class TestVersioningOSError:
    def test_oserror_during_move_lands_in_failed(self, vtree):
        """An OSError from shutil.move is captured in report.failed."""
        with patch("ff_explorer.core.shutil.move", side_effect=OSError("move denied")):
            report = remove_entries(
                vtree, EntryKind.FILES, "alpha",
                dry_run=False, confirm=True, versioning=True,
            )
        assert len(report.failed) >= 1
        assert any("move denied" in msg for _, msg in report.failed)
        assert len(report.removed) == 0


# ---------------------------------------------------------------------------
# 8. service.py passthrough threads versioning correctly
# ---------------------------------------------------------------------------

class TestServiceVersioningPassthrough:
    def test_service_versioning_true_moves_files(self, vtree):
        """service.remove_entries with versioning=True delegates to core correctly."""
        report = service.remove_entries(
            str(vtree), 1, "alpha",
            dry_run=False, confirm=True, versioning=True,
        )
        assert len(report.removed) == 2
        assert report.versioned_to is not None
        assert not (vtree / "alpha.txt").exists()

    def test_service_versioning_false_uses_send2trash(self, vtree):
        """service.remove_entries with versioning=False (default) uses send2trash."""
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = service.remove_entries(
                str(vtree), 1, "alpha",
                dry_run=False, confirm=True, versioning=False,
            )
        assert mock_trash.called
        assert report.versioned_to is None

    def test_service_dry_run_default_unchanged(self, vtree):
        """service.remove_entries default dry_run=True still previews safely."""
        report = service.remove_entries(str(vtree), 1, "alpha", versioning=True)
        assert report.dry_run is True
        assert report.removed == []
        assert (vtree / "alpha.txt").exists()

    def test_service_blank_seed_raises(self, vtree):
        """EmptySeedError propagates through service layer with versioning=True."""
        with pytest.raises(EmptySeedError):
            service.remove_entries(
                str(vtree), 1, "",
                dry_run=False, confirm=True, versioning=True,
            )
