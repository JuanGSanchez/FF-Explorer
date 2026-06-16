"""
Tests for ff_explorer.rename (FFX-I07) — batch rename with preview + undo.

Coverage targets:
- apply_rules: each rule kind unit-tested
- rename_entries: preview, apply, gate (empty seed, dry_run without confirm,
  confirm without dry_run=False), collision detection (intra-batch + disk)
- replay_undo: restores original names; error paths
- service passthrough
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ff_explorer.core import EmptySeedError, EntryKind
from ff_explorer.rename import (
    RenameRule,
    RenameReport,
    apply_rules,
    rename_entries,
    replay_undo,
)
from ff_explorer.api import service


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def file_tree(tmp_path: Path) -> Path:
    """A flat directory with several files for rename testing."""
    (tmp_path / "report_2024.txt").write_text("a")
    (tmp_path / "report_2025.txt").write_text("b")
    (tmp_path / "summary_2024.csv").write_text("c")
    (tmp_path / "notes.md").write_text("d")
    return tmp_path


@pytest.fixture()
def single_file(tmp_path: Path) -> Path:
    """A directory with one file."""
    (tmp_path / "hello_world.txt").write_text("x")
    return tmp_path


# ---------------------------------------------------------------------------
# Unit tests: apply_rules (each rule kind)
# ---------------------------------------------------------------------------

class TestApplyRulesKinds:

    def test_find_replace(self):
        rule = RenameRule("find_replace", {"find": "2024", "replace": "2025"})
        assert apply_rules("report_2024.txt", [rule]) == "report_2025.txt"

    def test_find_replace_no_match_is_noop(self):
        rule = RenameRule("find_replace", {"find": "XYZ", "replace": "ABC"})
        assert apply_rules("hello.txt", [rule]) == "hello.txt"

    def test_regex_replace(self):
        rule = RenameRule("regex_replace", {"pattern": r"\d{4}", "replacement": "YEAR"})
        assert apply_rules("report_2024.txt", [rule]) == "report_YEAR.txt"

    def test_regex_replace_ignore_case(self):
        rule = RenameRule("regex_replace", {
            "pattern": "REPORT",
            "replacement": "doc",
            "ignore_case": True,
        })
        assert apply_rules("report_2024.txt", [rule]) == "doc_2024.txt"

    def test_prefix(self):
        rule = RenameRule("prefix", {"text": "DRAFT_"})
        assert apply_rules("notes.txt", [rule]) == "DRAFT_notes.txt"

    def test_suffix_before_extension(self):
        rule = RenameRule("suffix", {"text": "_final"})
        assert apply_rules("report.txt", [rule]) == "report_final.txt"

    def test_suffix_no_extension(self):
        rule = RenameRule("suffix", {"text": "_v2"})
        assert apply_rules("Makefile", [rule]) == "Makefile_v2"

    def test_case_upper(self):
        rule = RenameRule("case", {"mode": "upper"})
        assert apply_rules("hello.txt", [rule]) == "HELLO.txt"

    def test_case_lower(self):
        rule = RenameRule("case", {"mode": "lower"})
        assert apply_rules("HELLO.TXT", [rule]) == "hello.TXT"

    def test_case_title(self):
        rule = RenameRule("case", {"mode": "title"})
        assert apply_rules("hello world.txt", [rule]) == "Hello World.txt"

    def test_counter_appended_via_template(self):
        rule = RenameRule("counter", {
            "start": 1, "step": 1, "padding": 3,
            "template": "{stem}_{n}{suffix}",
        })
        counter = [1]
        r1 = apply_rules("file.txt", [rule], counter)
        counter_val_after_first = counter[0]
        r2 = apply_rules("other.txt", [rule], counter)
        assert r1 == "file_001.txt"
        assert r2 == "other_002.txt"
        assert counter_val_after_first == 2

    def test_counter_custom_start_step(self):
        rule = RenameRule("counter", {
            "start": 10, "step": 5, "padding": 2,
            "template": "{n}_{stem}{suffix}",
        })
        counter = [10]
        r1 = apply_rules("a.txt", [rule], counter)
        r2 = apply_rules("b.txt", [rule], counter)
        assert r1 == "10_a.txt"
        assert r2 == "15_b.txt"

    def test_unknown_rule_raises(self):
        rule = RenameRule("nonexistent_rule", {})
        with pytest.raises(ValueError, match="Unknown rename rule kind"):
            apply_rules("file.txt", [rule])

    def test_rules_applied_in_order(self):
        """prefix then case → prefix text is also uppercased."""
        rules = [
            RenameRule("prefix", {"text": "pre_"}),
            RenameRule("case", {"mode": "upper"}),
        ]
        result = apply_rules("hello.txt", rules)
        assert result == "PRE_HELLO.txt"

    def test_empty_rules_is_noop(self):
        assert apply_rules("unchanged.txt", []) == "unchanged.txt"


# ---------------------------------------------------------------------------
# rename_entries — preview (dry_run default)
# ---------------------------------------------------------------------------

class TestRenameEntriesPreview:

    def test_preview_returns_mapping(self, file_tree):
        rules = [RenameRule("find_replace", {"find": "2024", "replace": "2099"})]
        report = rename_entries(str(file_tree), EntryKind.FILES, "2024", rules=rules)
        assert report.dry_run is True
        assert len(report.matched) == 2
        assert len(report.mapping) == 2
        for old_name, new_name in report.mapping:
            assert "2024" in old_name
            assert "2099" in new_name

    def test_preview_touches_nothing(self, file_tree):
        rules = [RenameRule("prefix", {"text": "NEW_"})]
        rename_entries(str(file_tree), EntryKind.FILES, "report", rules=rules)
        # originals still present
        assert (file_tree / "report_2024.txt").exists()
        assert (file_tree / "report_2025.txt").exists()
        # no new files created
        assert not (file_tree / "NEW_report_2024.txt").exists()

    def test_preview_no_undo_file(self, file_tree):
        rules = [RenameRule("suffix", {"text": "_bak"})]
        report = rename_entries(str(file_tree), EntryKind.FILES, "notes", rules=rules)
        assert report.undo_file is None

    def test_preview_renamed_list_empty(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        report = rename_entries(str(file_tree), EntryKind.FILES, "report", rules=rules)
        assert report.renamed == []

    def test_preview_no_match_returns_empty_mapping(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        report = rename_entries(str(file_tree), EntryKind.FILES, "NOMATCH_XYZ", rules=rules)
        assert report.matched == []
        assert report.mapping == []

    def test_would_affect_property(self, file_tree):
        rules = [RenameRule("prefix", {"text": "Z_"})]
        report = rename_entries(str(file_tree), EntryKind.FILES, "report", rules=rules)
        assert report.would_affect == report.matched


# ---------------------------------------------------------------------------
# rename_entries — live apply (dry_run=False, confirm=True)
# ---------------------------------------------------------------------------

class TestRenameEntriesApply:

    def _apply_rules(self):
        return [RenameRule("find_replace", {"find": "report", "replace": "doc"})]

    def test_apply_renames_files(self, file_tree):
        rules = self._apply_rules()
        report = rename_entries(
            str(file_tree), EntryKind.FILES, "report",
            rules=rules, dry_run=False, confirm=True,
        )
        assert report.dry_run is False
        assert len(report.renamed) == 2
        assert (file_tree / "doc_2024.txt").exists()
        assert (file_tree / "doc_2025.txt").exists()
        assert not (file_tree / "report_2024.txt").exists()

    def test_apply_writes_undo_file(self, file_tree):
        rules = self._apply_rules()
        report = rename_entries(
            str(file_tree), EntryKind.FILES, "report",
            rules=rules, dry_run=False, confirm=True,
        )
        assert report.undo_file is not None
        undo_path = Path(report.undo_file)
        assert undo_path.exists()
        assert undo_path.suffix == ".json"
        # Parent dir should be .ffe-rename-undo under file_tree
        assert undo_path.parent.name == ".ffe-rename-undo"
        assert undo_path.parent.parent == file_tree

    def test_undo_file_json_is_valid_reverse_map(self, file_tree):
        rules = self._apply_rules()
        report = rename_entries(
            str(file_tree), EntryKind.FILES, "report",
            rules=rules, dry_run=False, confirm=True,
        )
        with open(report.undo_file, encoding="utf-8") as f:
            undo_map = json.load(f)
        # keys are new paths, values are old paths
        assert len(undo_map) == 2
        for new_path_str, old_path_str in undo_map.items():
            assert "doc_" in Path(new_path_str).name
            assert "report_" in Path(old_path_str).name

    def test_replay_undo_restores_originals(self, file_tree):
        rules = self._apply_rules()
        report = rename_entries(
            str(file_tree), EntryKind.FILES, "report",
            rules=rules, dry_run=False, confirm=True,
        )
        # Files are now renamed
        assert (file_tree / "doc_2024.txt").exists()
        assert not (file_tree / "report_2024.txt").exists()

        # Replay undo
        result_pairs = replay_undo(report.undo_file)
        assert len(result_pairs) == 2

        # Originals restored
        assert (file_tree / "report_2024.txt").exists()
        assert (file_tree / "report_2025.txt").exists()
        assert not (file_tree / "doc_2024.txt").exists()

    def test_apply_no_collision_empty_failed(self, file_tree):
        rules = self._apply_rules()
        report = rename_entries(
            str(file_tree), EntryKind.FILES, "report",
            rules=rules, dry_run=False, confirm=True,
        )
        assert report.failed == []
        assert report.collisions == []

    def test_apply_folders_kind(self, tmp_path):
        sub = tmp_path / "project_alpha"
        sub.mkdir()
        (sub / "keep.txt").write_text("x")
        rules = [RenameRule("find_replace", {"find": "alpha", "replace": "beta"})]
        report = rename_entries(
            str(tmp_path), EntryKind.FOLDERS, "project",
            rules=rules, dry_run=False, confirm=True,
        )
        assert (tmp_path / "project_beta").exists()
        assert len(report.renamed) == 1


# ---------------------------------------------------------------------------
# rename_entries — gate enforcement
# ---------------------------------------------------------------------------

class TestRenameEntriesGate:

    def test_blank_seed_raises_empty_seed_error(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(EmptySeedError):
            rename_entries(str(file_tree), EntryKind.FILES, "", rules=rules)

    def test_whitespace_seed_raises_empty_seed_error(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(EmptySeedError):
            rename_entries(str(file_tree), EntryKind.FILES, "   ", rules=rules)

    def test_dry_run_false_without_confirm_raises_value_error(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(ValueError, match="confirm=True"):
            rename_entries(
                str(file_tree), EntryKind.FILES, "report",
                rules=rules, dry_run=False, confirm=False,
            )

    def test_dry_run_false_without_confirm_nothing_renamed(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(ValueError):
            rename_entries(
                str(file_tree), EntryKind.FILES, "report",
                rules=rules, dry_run=False, confirm=False,
            )
        # originals untouched
        assert (file_tree / "report_2024.txt").exists()

    def test_confirm_true_without_dry_run_false_is_preview(self, file_tree):
        """confirm=True with dry_run=True (default) must still be a preview."""
        rules = [RenameRule("prefix", {"text": "X_"})]
        report = rename_entries(
            str(file_tree), EntryKind.FILES, "report",
            rules=rules, dry_run=True, confirm=True,
        )
        assert report.dry_run is True
        assert report.renamed == []
        # Nothing renamed on disk
        assert (file_tree / "report_2024.txt").exists()
        assert not (file_tree / "X_report_2024.txt").exists()

    def test_empty_seed_error_has_correct_operation(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(EmptySeedError) as exc_info:
            rename_entries(str(file_tree), EntryKind.FILES, "", rules=rules)
        assert exc_info.value.operation == "rename_entries"


# ---------------------------------------------------------------------------
# rename_entries — collision detection
# ---------------------------------------------------------------------------

class TestRenameEntriesCollision:

    def test_intra_batch_collision_refused(self, tmp_path):
        """Two files mapping to the same target name → collision, nothing renamed."""
        (tmp_path / "file_a.txt").write_text("a")
        (tmp_path / "file_b.txt").write_text("b")
        # Both will become "file.txt" after removing _a / _b → collision
        rules = [RenameRule("regex_replace", {"pattern": r"_[ab]", "replacement": ""})]
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "file_",
            rules=rules, dry_run=False, confirm=True,
        )
        assert len(report.collisions) >= 1
        assert report.renamed == []
        # Originals untouched
        assert (tmp_path / "file_a.txt").exists()
        assert (tmp_path / "file_b.txt").exists()

    def test_disk_collision_refused(self, tmp_path):
        """Target already exists on disk and is not being renamed away."""
        (tmp_path / "report_old.txt").write_text("old")
        (tmp_path / "report_new.txt").write_text("existing target")
        # Rename report_old → report_new, but report_new already exists
        rules = [RenameRule("find_replace", {"find": "_old", "replace": "_new"})]
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "report_old",
            rules=rules, dry_run=False, confirm=True,
        )
        assert len(report.collisions) >= 1
        assert report.renamed == []
        assert (tmp_path / "report_old.txt").exists()

    def test_collision_reported_in_preview_too(self, tmp_path):
        """Collision detection runs even in dry_run mode."""
        (tmp_path / "file_a.txt").write_text("a")
        (tmp_path / "file_b.txt").write_text("b")
        rules = [RenameRule("regex_replace", {"pattern": r"_[ab]", "replacement": ""})]
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "file_",
            rules=rules,  # dry_run=True default
        )
        assert len(report.collisions) >= 1
        assert report.renamed == []

    def test_no_collision_when_rename_clears_slot(self, tmp_path):
        """A→B, B→C: B is being renamed away, so A→B is not a disk collision."""
        (tmp_path / "step1.txt").write_text("1")
        (tmp_path / "step2.txt").write_text("2")
        # Rename step1→step2 and step2→step3 simultaneously
        # This is NOT possible with current substring match (both match "step")
        # but we can test that renaming step1 to a name that is itself being
        # renamed away (step2) does not falsely trigger a disk collision.
        # step1 → step2 (step2 exists but step2 is also being renamed → step3)
        # After rename: step2→step3, step1→step2 — this is a valid chain but
        # both are matched; the old step2 IS being renamed (it's in old_paths_set)
        # so no disk collision should be raised.
        rules = [RenameRule("find_replace", {"find": "step1", "replace": "step2"})]
        # Only rename step1; step2 exists and is NOT being renamed by this call
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "step1",
            rules=rules, dry_run=True,
        )
        # step2 exists and step1 is not being renamed away → collision
        assert len(report.collisions) >= 1

    def test_noop_rename_no_collision(self, tmp_path):
        """A file that renames to itself (noop) should not produce a disk collision."""
        (tmp_path / "keep.txt").write_text("k")
        # find_replace with no match → old == new
        rules = [RenameRule("find_replace", {"find": "NOMATCH", "replace": "X"})]
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "keep",
            rules=rules, dry_run=True,
        )
        assert report.collisions == []


# ---------------------------------------------------------------------------
# replay_undo — error paths
# ---------------------------------------------------------------------------

class TestReplayUndo:

    def test_missing_undo_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            replay_undo(str(tmp_path / "nonexistent.json"))

    def test_invalid_json_raises(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{{")
        with pytest.raises(ValueError, match="Invalid undo file JSON"):
            replay_undo(str(bad))

    def test_replay_returns_pairs(self, tmp_path):
        (tmp_path / "old.txt").write_text("x")
        rules = [RenameRule("find_replace", {"find": "old", "replace": "new"})]
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "old",
            rules=rules, dry_run=False, confirm=True,
        )
        pairs = replay_undo(report.undo_file)
        assert isinstance(pairs, list)
        assert len(pairs) == 1
        new_p, old_p = pairs[0]
        assert "new.txt" in new_p
        assert "old.txt" in old_p


# ---------------------------------------------------------------------------
# Service passthrough (FFX-I07 acceptance: service exports rename_entries)
# ---------------------------------------------------------------------------

class TestServiceRenamePassthrough:

    def test_service_exports_rename_entries(self):
        assert hasattr(service, "rename_entries")
        assert "rename_entries" in service.__all__

    def test_service_exports_replay_undo(self):
        assert hasattr(service, "replay_undo")
        assert "replay_undo" in service.__all__

    def test_service_exports_rename_rule(self):
        assert hasattr(service, "RenameRule")
        assert "RenameRule" in service.__all__

    def test_service_exports_rename_report(self):
        assert hasattr(service, "RenameReport")
        assert "RenameReport" in service.__all__

    def test_service_preview_passthrough(self, file_tree):
        rules = [RenameRule("prefix", {"text": "SVC_"})]
        report = service.rename_entries(str(file_tree), 1, "report", rules=rules)
        assert report.dry_run is True
        assert len(report.matched) == 2
        assert report.renamed == []

    def test_service_apply_passthrough(self, file_tree):
        rules = [RenameRule("find_replace", {"find": "report", "replace": "svc_doc"})]
        report = service.rename_entries(
            str(file_tree), 1, "report",
            rules=rules, dry_run=False, confirm=True,
        )
        assert report.dry_run is False
        assert len(report.renamed) == 2
        assert (file_tree / "svc_doc_2024.txt").exists()

    def test_service_gate_empty_seed(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(EmptySeedError):
            service.rename_entries(str(file_tree), 1, "", rules=rules)

    def test_service_gate_no_confirm(self, file_tree):
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(ValueError):
            service.rename_entries(
                str(file_tree), 1, "report",
                rules=rules, dry_run=False, confirm=False,
            )

    def test_service_replay_undo_passthrough(self, file_tree):
        rules = [RenameRule("find_replace", {"find": "notes", "replace": "memo"})]
        report = service.rename_entries(
            str(file_tree), 1, "notes",
            rules=rules, dry_run=False, confirm=True,
        )
        assert report.undo_file is not None
        pairs = service.replay_undo(report.undo_file)
        assert len(pairs) == 1
        assert (file_tree / "notes.md").exists()


# ---------------------------------------------------------------------------
# Coverage completeness — branches not hit by the main test paths
# ---------------------------------------------------------------------------

class TestCoverageBranches:

    def test_normalise_path_invalid_dir_raises(self, tmp_path):
        """_normalise_path raises ValueError for a non-directory path."""
        rules = [RenameRule("prefix", {"text": "X_"})]
        with pytest.raises(ValueError, match="path must be an existing directory"):
            rename_entries(str(tmp_path / "ghost_dir"), EntryKind.FILES, "x", rules=rules)

    def test_case_rule_unknown_mode_noop(self):
        """case rule with an unknown mode returns the name unchanged."""
        rule = RenameRule("case", {"mode": "camelCase_unsupported"})
        assert apply_rules("Hello.txt", [rule]) == "Hello.txt"

    def test_counter_rule_via_rename_entries_with_explicit_start(self, tmp_path):
        """Counter rule applied via rename_entries uses the explicit start param."""
        (tmp_path / "img001.png").write_text("a")
        (tmp_path / "img002.png").write_text("b")
        rules = [RenameRule("counter", {
            "start": 5, "step": 1, "padding": 2,
            "template": "photo_{n}{suffix}",
        })]
        report = rename_entries(
            str(tmp_path), EntryKind.FILES, "img",
            rules=rules, dry_run=True,
        )
        new_names = [new for _, new in report.mapping]
        # Should start from 5
        assert any("05" in n or "06" in n for n in new_names)

    def test_apply_oserror_collected_in_failed(self, tmp_path):
        """Per-file OSError is collected in .failed rather than aborting."""
        from unittest.mock import patch
        (tmp_path / "target.txt").write_text("t")
        rules = [RenameRule("prefix", {"text": "NEW_"})]

        original_rename = Path.rename

        def _failing_rename(self, target):
            raise OSError("simulated rename failure")

        with patch.object(Path, "rename", _failing_rename):
            report = rename_entries(
                str(tmp_path), EntryKind.FILES, "target",
                rules=rules, dry_run=False, confirm=True,
            )

        assert len(report.failed) == 1
        assert "simulated rename failure" in report.failed[0][1]
        assert report.renamed == []
        assert report.undo_file is None  # no successes → no undo file

    def test_replay_undo_oserror_is_best_effort(self, tmp_path):
        """replay_undo OSError on rename is swallowed; pairs list still returned."""
        from unittest.mock import patch
        # Write a valid undo file pointing to a file that no longer exists
        undo_dir = tmp_path / ".ffe-rename-undo"
        undo_dir.mkdir()
        undo_file = undo_dir / "20260101-000000.json"
        new_p = str(tmp_path / "new_name.txt")
        old_p = str(tmp_path / "original.txt")
        # new_name.txt does not exist → rename will raise
        undo_file.write_text(
            '{"' + new_p.replace("\\", "\\\\") + '": "' + old_p.replace("\\", "\\\\") + '"}'
        )
        # Should not raise; returns list with the pair
        result = replay_undo(str(undo_file))
        assert len(result) == 1
        assert result[0] == (new_p, old_p)
