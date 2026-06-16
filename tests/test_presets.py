"""
Tests for ff_explorer.presets (FFX-I03) and the service-layer preset functions.

All tests use the FFE_PRESETS_DIR env override (monkeypatched to tmp_path) so
that no real user config directory is read or written.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import ff_explorer.presets as presets_mod
from ff_explorer.presets import (
    Preset,
    delete_preset,
    get_preset,
    list_presets,
    presets_file,
    save_preset,
)
from ff_explorer.api import service
from ff_explorer.core import EmptySeedError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_presets_dir(tmp_path: Path, monkeypatch):
    """Redirect the preset store to tmp_path for every test in this module."""
    store_dir = tmp_path / "presets_store"
    store_dir.mkdir()
    monkeypatch.setenv("FFE_PRESETS_DIR", str(store_dir))
    yield store_dir


@pytest.fixture()
def query_tree(tmp_path: Path) -> Path:
    """Small fixtured tree for list-preset run tests."""
    root = tmp_path / "qtree"
    root.mkdir()
    (root / "report_jan.txt").write_text("jan")
    (root / "report_feb.txt").write_text("feb")
    (root / "summary.log").write_text("log")
    sub = root / "archive"
    sub.mkdir()
    (sub / "report_mar.txt").write_text("mar")
    return root


@pytest.fixture()
def destroy_tree(tmp_path: Path) -> Path:
    """Tree for destructive-preset tests."""
    root = tmp_path / "dtree"
    root.mkdir()
    (root / "target_a.txt").write_text("a")
    (root / "target_b.txt").write_text("b")
    (root / "keep.log").write_text("keep")
    return root


# ---------------------------------------------------------------------------
# presets_file() resolution
# ---------------------------------------------------------------------------

class TestPresetsFileResolution:
    def test_env_override_used(self, isolated_presets_dir):
        fp = presets_file()
        assert str(isolated_presets_dir) in str(fp)
        assert fp.name == "presets.json"

    def test_windows_appdata_fallback(self, monkeypatch):
        monkeypatch.delenv("FFE_PRESETS_DIR", raising=False)
        monkeypatch.setenv("APPDATA", "C:\\Users\\test\\AppData\\Roaming")
        # Patch sys.platform to win32
        monkeypatch.setattr(presets_mod.sys, "platform", "win32")
        fp = presets_mod._config_dir()
        assert "ff-explorer" in str(fp)

    def test_xdg_config_home_posix(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FFE_PRESETS_DIR", raising=False)
        monkeypatch.setattr(presets_mod.sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        fp = presets_mod._config_dir()
        assert str(tmp_path / "xdg") in str(fp)
        assert "ff-explorer" in str(fp)

    def test_posix_home_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FFE_PRESETS_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(presets_mod.sys, "platform", "linux")
        fp = presets_mod._config_dir()
        assert ".config" in str(fp) or str(Path.home()) in str(fp)
        assert "ff-explorer" in str(fp)

    def test_windows_no_appdata_fallback(self, monkeypatch):
        monkeypatch.delenv("FFE_PRESETS_DIR", raising=False)
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.setattr(presets_mod.sys, "platform", "win32")
        fp = presets_mod._config_dir()
        assert "ff-explorer" in str(fp)


# ---------------------------------------------------------------------------
# save / list / get / delete round-trip
# ---------------------------------------------------------------------------

class TestPresetsRoundTrip:
    def _make_preset(self, name="search_txt", path="/tmp/root") -> Preset:
        return Preset(
            name=name,
            path=path,
            kind=1,
            name_seed="report",
            case_sensitive=False,
            match_mode="substring",
            operation="list",
        )

    def test_save_and_list(self):
        p = self._make_preset()
        save_preset(p)
        results = list_presets()
        assert len(results) == 1
        assert results[0].name == "search_txt"

    def test_save_and_get(self):
        p = self._make_preset()
        save_preset(p)
        got = get_preset("search_txt")
        assert got.name_seed == "report"
        assert got.case_sensitive is False
        assert got.operation == "list"

    def test_upsert_by_name(self):
        p = self._make_preset()
        save_preset(p)
        updated = Preset(
            name="search_txt",
            path="/tmp/root",
            kind=1,
            name_seed="summary",
            operation="list",
        )
        save_preset(updated)
        results = list_presets()
        assert len(results) == 1
        assert results[0].name_seed == "summary"

    def test_multiple_presets_listed(self):
        save_preset(self._make_preset("p1"))
        save_preset(self._make_preset("p2"))
        names = {p.name for p in list_presets()}
        assert names == {"p1", "p2"}

    def test_delete_removes_preset(self):
        save_preset(self._make_preset())
        delete_preset("search_txt")
        assert list_presets() == []

    def test_delete_nonexistent_raises_key_error(self):
        with pytest.raises(KeyError):
            delete_preset("ghost")

    def test_get_nonexistent_raises_key_error(self):
        with pytest.raises(KeyError):
            get_preset("ghost")

    def test_empty_file_returns_empty_list(self, isolated_presets_dir):
        fp = isolated_presets_dir / "presets.json"
        fp.write_text("")
        assert list_presets() == []

    def test_missing_file_returns_empty_list(self):
        # File was never created
        assert list_presets() == []

    def test_corrupt_json_returns_empty_list(self, isolated_presets_dir):
        fp = isolated_presets_dir / "presets.json"
        fp.write_text("{not valid json{{")
        assert list_presets() == []

    def test_non_dict_json_returns_empty_list(self, isolated_presets_dir):
        fp = isolated_presets_dir / "presets.json"
        fp.write_text(json.dumps([1, 2, 3]))
        assert list_presets() == []

    def test_json_round_trip_all_fields(self):
        p = Preset(
            name="full",
            path="/some/path",
            kind=0,
            name_seed="src",
            case_sensitive=True,
            match_mode="glob",
            min_size=100,
            max_size=5000,
            modified_after=1_700_000_000.0,
            modified_before=1_800_000_000.0,
            extensions=[".py", ".txt"],
            respect_ignore=True,
            ignore_globs=["*.pyc"],
            operation="list",
        )
        save_preset(p)
        got = get_preset("full")
        assert got.kind == 0
        assert got.match_mode == "glob"
        assert got.min_size == 100
        assert got.max_size == 5000
        assert got.modified_after == 1_700_000_000.0
        assert got.modified_before == 1_800_000_000.0
        assert got.extensions == [".py", ".txt"]
        assert got.respect_ignore is True
        assert got.ignore_globs == ["*.pyc"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestPresetValidation:
    def test_invalid_operation_raises_value_error(self):
        p = Preset(name="bad", path="/tmp", operation="delete")
        with pytest.raises(ValueError, match="operation"):
            save_preset(p)

    def test_empty_name_raises_value_error(self):
        p = Preset(name="", path="/tmp", operation="list")
        with pytest.raises(ValueError):
            save_preset(p)

    def test_whitespace_name_raises_value_error(self):
        p = Preset(name="   ", path="/tmp", operation="list")
        with pytest.raises(ValueError):
            save_preset(p)

    def test_valid_operations_all_accepted(self):
        for op in ("list", "remove", "compress"):
            p = Preset(name=f"op_{op}", path="/tmp", name_seed="x", operation=op)
            save_preset(p)  # must not raise


# ---------------------------------------------------------------------------
# run_preset — "list" operation
# ---------------------------------------------------------------------------

class TestRunPresetList:
    def test_run_list_preset_matches_inline_list_entries(self, query_tree):
        p = Preset(
            name="find_reports",
            path=str(query_tree),
            kind=1,
            name_seed="report",
            operation="list",
        )
        save_preset(p)

        inline = service.list_entries(str(query_tree), 1, "report")
        via_preset = service.run_preset("find_reports")

        assert {e.path for e in inline} == {e.path for e in via_preset}

    def test_run_list_preset_respects_case_insensitive(self, query_tree):
        p = Preset(
            name="ci_search",
            path=str(query_tree),
            kind=1,
            name_seed="REPORT",
            case_sensitive=False,
            operation="list",
        )
        save_preset(p)
        results = service.run_preset("ci_search")
        names = {e.path.name for e in results}
        assert "report_jan.txt" in names
        assert "report_feb.txt" in names

    def test_run_list_preset_empty_seed_returns_all(self, query_tree):
        p = Preset(
            name="all_files",
            path=str(query_tree),
            kind=1,
            name_seed="",
            operation="list",
        )
        save_preset(p)
        inline = service.list_entries(str(query_tree), 1)
        via_preset = service.run_preset("all_files")
        assert {e.path for e in inline} == {e.path for e in via_preset}

    def test_run_list_preset_glob_mode(self, query_tree):
        p = Preset(
            name="glob_txt",
            path=str(query_tree),
            kind=1,
            name_seed="*.txt",
            match_mode="glob",
            operation="list",
        )
        save_preset(p)
        results = service.run_preset("glob_txt")
        assert all(e.path.suffix == ".txt" for e in results)
        assert len(results) >= 3

    def test_run_list_preset_with_extensions_filter(self, query_tree):
        p = Preset(
            name="txt_only",
            path=str(query_tree),
            kind=1,
            name_seed="",
            extensions=[".txt"],
            operation="list",
        )
        save_preset(p)
        results = service.run_preset("txt_only")
        names = {e.path.name for e in results}
        assert "summary.log" not in names
        assert "report_jan.txt" in names

    def test_run_preset_missing_name_raises_key_error(self):
        with pytest.raises(KeyError):
            service.run_preset("does_not_exist")


# ---------------------------------------------------------------------------
# run_preset — "remove" operation (destructive gate tests)
# ---------------------------------------------------------------------------

class TestRunPresetRemove:
    def test_dry_run_default_returns_preview_no_mutation(self, destroy_tree):
        """Default dry_run=True must return preview and leave files intact."""
        p = Preset(
            name="rm_targets",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="remove",
        )
        save_preset(p)

        report = service.run_preset("rm_targets")  # dry_run=True by default
        assert report.dry_run is True
        assert report.removed == []
        assert len(report.matched) >= 2
        # Files must still exist
        assert (destroy_tree / "target_a.txt").exists()
        assert (destroy_tree / "target_b.txt").exists()

    def test_confirm_false_dry_run_true_is_safe(self, destroy_tree):
        """Explicit dry_run=True + confirm=False (defaults) must not mutate."""
        p = Preset(
            name="rm_safe",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="remove",
        )
        save_preset(p)
        report = service.run_preset("rm_safe", dry_run=True, confirm=False)
        assert report.dry_run is True
        assert report.removed == []

    def test_no_confirm_with_live_run_raises(self, destroy_tree):
        """dry_run supplied as False without confirm raises ValueError."""
        p = Preset(
            name="rm_badgate",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="remove",
        )
        save_preset(p)
        with pytest.raises(ValueError):
            service.run_preset("rm_badgate", dry_run=False, confirm=False)

    def test_live_remove_requires_both_flags(self, destroy_tree):
        """With dry_run=False and confirm=True the files are actually removed."""
        p = Preset(
            name="rm_live",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="remove",
        )
        save_preset(p)
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            report = service.run_preset("rm_live", dry_run=False, confirm=True)
        assert mock_trash.called
        assert len(report.removed) >= 2


# ---------------------------------------------------------------------------
# run_preset — "compress" operation (destructive gate tests)
# ---------------------------------------------------------------------------

class TestRunPresetCompress:
    def test_dry_run_default_returns_preview_no_mutation(self, destroy_tree):
        p = Preset(
            name="cmp_targets",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="compress",
        )
        save_preset(p)
        report = service.run_preset("cmp_targets")  # dry_run=True default
        assert report.dry_run is True
        assert report.archives == []
        assert (destroy_tree / "target_a.txt").exists()

    def test_no_confirm_with_live_compress_raises(self, destroy_tree):
        p = Preset(
            name="cmp_badgate",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="compress",
        )
        save_preset(p)
        with pytest.raises(ValueError):
            service.run_preset("cmp_badgate", dry_run=False, confirm=False)

    def test_live_compress_mutates(self, destroy_tree):
        p = Preset(
            name="cmp_live",
            path=str(destroy_tree),
            kind=1,
            name_seed="target",
            operation="compress",
        )
        save_preset(p)
        report = service.run_preset("cmp_live", dry_run=False, confirm=True)
        assert len(report.archives) >= 1
        assert report.archives[0].exists()


# ---------------------------------------------------------------------------
# service.__all__ exports + wrapper coverage
# ---------------------------------------------------------------------------

class TestServicePresetsExports:
    def test_save_preset_in_all(self):
        assert "save_preset" in service.__all__

    def test_list_presets_in_all(self):
        assert "list_presets" in service.__all__

    def test_run_preset_in_all(self):
        assert "run_preset" in service.__all__

    def test_preset_class_in_all(self):
        assert "Preset" in service.__all__

    def test_save_preset_callable(self):
        assert callable(service.save_preset)

    def test_list_presets_callable(self):
        assert callable(service.list_presets)

    def test_run_preset_callable(self):
        assert callable(service.run_preset)

    def test_service_save_preset_delegates(self, query_tree):
        """service.save_preset wrapper (line 356) reaches the presets module."""
        p = Preset(
            name="svc_delegate",
            path=str(query_tree),
            kind=1,
            name_seed="report",
            operation="list",
        )
        service.save_preset(p)
        assert get_preset("svc_delegate").name_seed == "report"

    def test_service_list_presets_delegates(self, query_tree):
        """service.list_presets wrapper (line 364) reaches the presets module."""
        p = Preset(
            name="svc_list_test",
            path=str(query_tree),
            kind=1,
            name_seed="x",
            operation="list",
        )
        service.save_preset(p)
        names = {pr.name for pr in service.list_presets()}
        assert "svc_list_test" in names


# ---------------------------------------------------------------------------
# Defensive / edge-case coverage
# ---------------------------------------------------------------------------

class TestDefensiveCoverage:
    def test_list_presets_skips_malformed_entry(self, isolated_presets_dir):
        """list_presets silently skips a JSON entry that cannot be parsed
        as a Preset (covers the except branch in list_presets, lines 208-210)."""
        fp = isolated_presets_dir / "presets.json"
        # An entry where 'name' key is missing — _dict_to_preset gets a
        # TypeError because the Preset dataclass requires 'name'.
        fp.write_text(json.dumps({
            "good": {
                "name": "good", "path": "/tmp", "kind": 1,
                "name_seed": "", "case_sensitive": True,
                "match_mode": "substring", "min_size": None,
                "max_size": None, "modified_after": None,
                "modified_before": None, "extensions": None,
                "respect_ignore": False, "ignore_globs": None,
                "operation": "list",
            },
            "bad": {"no_name_key": True},  # will raise TypeError in _dict_to_preset
        }))
        result = list_presets()
        # Only the good entry survives; the bad one is silently skipped.
        assert len(result) == 1
        assert result[0].name == "good"

    def test_run_preset_unknown_operation_raises(self, query_tree, monkeypatch):
        """The defensive raise at the end of run_preset (service.py line 446)
        is reached when a preset slips through with an unrecognised operation."""
        # Save a valid preset then patch the store to return a bad operation.
        import ff_explorer.presets as pm
        original_get = pm.get_preset

        def _bad_get(name):
            p = original_get(name)
            # Return a copy with a mutated operation that bypasses save_preset
            from dataclasses import replace
            return replace(p, operation="unknown_op")

        p = Preset(
            name="bad_op_preset",
            path=str(query_tree),
            kind=1,
            name_seed="x",
            operation="list",
        )
        save_preset(p)
        monkeypatch.setattr(pm, "get_preset", _bad_get)
        # The service imports _presets_get which is already bound; patch it there.
        import ff_explorer.api.service as svc_mod
        monkeypatch.setattr(svc_mod, "_presets_get", _bad_get)

        with pytest.raises(ValueError, match="Unknown preset operation"):
            service.run_preset("bad_op_preset")
