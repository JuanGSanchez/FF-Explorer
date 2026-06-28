"""
Integration tests for ff_explorer.api.main — combined ASGI app (FFX-B03)
and bind host-resolution logic (FFX-B06).

FFX-B03: drives the combined ``ff_explorer.api.main.app`` end-to-end and
asserts that REST routes and exception-handler behaviour (422 on empty seed /
missing confirm) are preserved through the composed app — matching behaviour
already asserted against ``rest.app`` in ``test_rest.py``.

FFX-B06: asserts the ``_resolve_host`` helper returns the correct bind
address under all three cases (default, env-var opt-in, explicit ``--host``),
without binding any real socket.

MCP tool-name contract: asserts the derived tool names are unchanged after
the B03 composition refactor.
"""
from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from ff_explorer.api.main import app, _resolve_host
from ff_explorer.api.mcp_server import mcp


# ---------------------------------------------------------------------------
# Shared TestClient for the combined app
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def main_client():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def main_file_tree(tmp_path: Path) -> Path:
    """Simple file tree for combined-app integration tests."""
    (tmp_path / "keep.txt").write_text("keep")
    (tmp_path / "target_x.txt").write_text("x")
    (tmp_path / "target_y.txt").write_text("y")
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "target_sub.txt").write_text("sub")
    return tmp_path


# ---------------------------------------------------------------------------
# FFX-B03 — combined app: REST routes reachable and exception mapping intact
# ---------------------------------------------------------------------------

class TestCombinedAppREST:
    """B03: REST routes work through the combined main.app."""

    def test_health_via_combined_app(self, main_client):
        resp = main_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_list_entries_success(self, main_client, main_file_tree):
        """B03(a): successful list_entries call through the combined app."""
        resp = main_client.post("/entries", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "target",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2
        for entry in data["entries"]:
            assert "target" in Path(entry["path"]).name

    def test_list_entries_empty_seed_all_files(self, main_client, main_file_tree):
        resp = main_client.post("/entries", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "",
        })
        assert resp.status_code == 200
        assert resp.json()["count"] >= 3

    def test_invalid_path_422(self, main_client, tmp_path):
        resp = main_client.post("/entries", json={
            "path": str(tmp_path / "no_such_dir"), "kind": 1,
        })
        assert resp.status_code == 422

    def test_metadata_success(self, main_client, main_file_tree):
        target = main_file_tree / "keep.txt"
        resp = main_client.post("/metadata", json={"path": str(target)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "file"
        assert data["exists"] is True

    def test_metadata_nonexistent_404(self, main_client, tmp_path):
        resp = main_client.post("/metadata", json={
            "path": str(tmp_path / "ghost.txt"),
        })
        assert resp.status_code == 404


class TestCombinedAppDestructiveGate:
    """B03(b): destructive gate (422 paths) works through the combined app."""

    def test_remove_empty_seed_422(self, main_client, main_file_tree):
        """Empty name_seed must yield 422 — Pydantic min_length=1."""
        resp = main_client.post("/remove", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "",
        })
        assert resp.status_code == 422

    def test_remove_dry_run_false_no_confirm_422(self, main_client, main_file_tree):
        """dry_run=False without confirm=True must yield 422 (ValueError from core)."""
        resp = main_client.post("/remove", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "target",
            "dry_run": False, "confirm": False,
        })
        assert resp.status_code == 422

    def test_remove_dry_run_default_preview(self, main_client, main_file_tree):
        """Default dry_run=True: returns preview, nothing removed."""
        resp = main_client.post("/remove", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "target",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["removed"] == []
        # Files must still exist after a dry-run
        assert (main_file_tree / "target_x.txt").exists()

    def test_compress_empty_seed_422(self, main_client, main_file_tree):
        resp = main_client.post("/compress", json={
            "path": str(main_file_tree), "kind": 0, "name_seed": "",
        })
        assert resp.status_code == 422

    def test_compress_dry_run_false_no_confirm_422(self, main_client, main_file_tree):
        resp = main_client.post("/compress", json={
            "path": str(main_file_tree), "kind": 0, "name_seed": "subdir",
            "dry_run": False, "confirm": False,
        })
        assert resp.status_code == 422

    def test_rename_empty_seed_422(self, main_client, main_file_tree):
        """FFX-I07: empty name_seed rejected at schema level → HTTP 422."""
        resp = main_client.post("/rename", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "",
            "rules": [{"kind": "prefix", "text": "X_"}],
        })
        assert resp.status_code == 422

    def test_rename_dry_run_false_no_confirm_422(self, main_client, main_file_tree):
        """FFX-I07: dry_run=False without confirm=True → ValueError → HTTP 422."""
        resp = main_client.post("/rename", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "target",
            "rules": [{"kind": "prefix", "text": "X_"}],
            "dry_run": False, "confirm": False,
        })
        assert resp.status_code == 422

    def test_rename_dry_run_default_preview(self, main_client, main_file_tree):
        """FFX-I07: default dry_run=True returns preview mapping, nothing renamed."""
        resp = main_client.post("/rename", json={
            "path": str(main_file_tree), "kind": 1, "name_seed": "target",
            "rules": [{"kind": "prefix", "text": "2024_"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["renamed"] == []
        assert len(data["mapping"]) >= 2
        assert (main_file_tree / "target_x.txt").exists()

    def test_remove_live_calls_send2trash(self, main_client, main_file_tree):
        """dry_run=False + confirm=True routes through send2trash."""
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            resp = main_client.post("/remove", json={
                "path": str(main_file_tree), "kind": 1, "name_seed": "target_x",
                "dry_run": False, "confirm": True,
            })
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is False
        assert mock_trash.called


# ---------------------------------------------------------------------------
# FFX-B06 — host-resolution logic (no real socket bound)
# ---------------------------------------------------------------------------

class TestResolveHost:
    """B06: _resolve_host returns the correct bind address in all cases."""

    def test_default_is_loopback(self):
        """With no flag and no env var, must resolve to 127.0.0.1."""
        with patch.dict(os.environ, {}, clear=False):
            # Ensure FFE_BIND_ALL is absent
            env = os.environ.copy()
            env.pop("FFE_BIND_ALL", None)
            with patch.dict(os.environ, env, clear=True):
                assert _resolve_host(None) == "127.0.0.1"

    def test_env_var_bind_all(self):
        """FFE_BIND_ALL=1 with no --host flag resolves to 0.0.0.0."""
        with patch.dict(os.environ, {"FFE_BIND_ALL": "1"}):
            assert _resolve_host(None) == "0.0.0.0"

    def test_explicit_host_wins_over_env(self):
        """Explicit --host always takes precedence over FFE_BIND_ALL."""
        with patch.dict(os.environ, {"FFE_BIND_ALL": "1"}):
            assert _resolve_host("192.168.1.1") == "192.168.1.1"

    def test_explicit_host_loopback(self):
        """Explicit --host 127.0.0.1 is returned as-is."""
        assert _resolve_host("127.0.0.1") == "127.0.0.1"

    def test_explicit_host_all_interfaces(self):
        """Explicit --host 0.0.0.0 is returned as-is."""
        assert _resolve_host("0.0.0.0") == "0.0.0.0"

    def test_env_var_not_set_to_1_keeps_loopback(self):
        """FFE_BIND_ALL with a value other than '1' does not trigger opt-in."""
        with patch.dict(os.environ, {"FFE_BIND_ALL": "0"}):
            assert _resolve_host(None) == "127.0.0.1"

    def test_env_var_empty_keeps_loopback(self):
        """Empty FFE_BIND_ALL does not trigger opt-in."""
        with patch.dict(os.environ, {"FFE_BIND_ALL": ""}):
            assert _resolve_host(None) == "127.0.0.1"


# ---------------------------------------------------------------------------
# FFX-I01 / FFX-I02 — advanced filter params through combined app
# ---------------------------------------------------------------------------

class TestCombinedAppAdvancedFilters:
    """New filter params (FFX-I01/I02) work through the combined main.app."""

    def test_regex_match_via_combined_app(self, main_client, main_file_tree):
        """match_mode='regex' returns correct entries through combined app."""
        resp = main_client.post("/entries", json={
            "path": str(main_file_tree), "kind": 1,
            "name_seed": r"^target_[xy]\.txt$",
            "match_mode": "regex",
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(entry["path"]).name for entry in data["entries"]]
        assert sorted(names) == ["target_x.txt", "target_y.txt"]

    def test_invalid_regex_422_via_combined_app(self, main_client, main_file_tree):
        """Invalid regex → 422 through combined app (exception handler intact)."""
        resp = main_client.post("/entries", json={
            "path": str(main_file_tree), "kind": 1,
            "name_seed": "[bad_regex",
            "match_mode": "regex",
        })
        assert resp.status_code == 422

    def test_extension_filter_via_combined_app(self, main_client, tmp_path):
        """Extension filter returns only matching suffixes through combined app."""
        (tmp_path / "file.txt").write_text("a")
        (tmp_path / "file.log").write_text("b")
        (tmp_path / "file.py").write_text("c")
        resp = main_client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "extensions": [".txt"],
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert names == ["file.txt"]

    def test_size_filter_via_combined_app(self, main_client, tmp_path):
        """min_size filter works through combined app."""
        (tmp_path / "tiny.txt").write_bytes(b"x")
        (tmp_path / "big.txt").write_bytes(b"x" * 500)
        resp = main_client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "min_size": 100,
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "big.txt" in names
        assert "tiny.txt" not in names


# ---------------------------------------------------------------------------
# MCP tool-name contract — unchanged after B03 composition refactor
# ---------------------------------------------------------------------------

EXPECTED_MCP_TOOL_NAMES = {
    "health_health_get",
    "post_list_entries_entries_post",
    "post_entry_metadata_metadata_post",
    "post_save_listing_listing_post",
    "post_remove_remove_post",
    "post_compress_compress_post",
    # FFX-I03 — preset operations (derived from FastMCP.from_fastapi)
    "post_save_preset_presets_save_post",
    "post_list_presets_presets_list_post",
    "post_run_preset_presets_run_post",
    # FFX-I06 — duplicate detection (derived from FastMCP.from_fastapi)
    "post_find_duplicates_duplicates_post",
    # FFX-I07 — batch rename (derived from FastMCP.from_fastapi)
    "post_rename_rename_post",
    # FFX-I10 — index lifecycle (derived from FastMCP.from_fastapi)
    "post_start_index_index_start_post",
    "post_stop_index_index_stop_post",
    "post_index_status_index_status_post",
    # FFX-I11 — size aggregation / largest-files (derived from FastMCP.from_fastapi)
    "post_largest_entries_largest_post",
    # SPEC-18 — copy / move (gated destructive; derived from FastMCP.from_fastapi)
    "post_copy_copy_post",
    "post_move_move_post",
    # SPEC-15 — list with skip report (derived from FastMCP.from_fastapi)
    "post_list_with_report_list_with_report_post",
}


class TestMCPToolNames:
    """Assert the derived MCP tool-name set is unchanged after B03 refactor."""

    def test_tool_names_unchanged(self):
        async def _get_names() -> set[str]:
            tools = await mcp.list_tools()
            return {t.name for t in tools}

        names = asyncio.run(_get_names())
        assert names == EXPECTED_MCP_TOOL_NAMES, (
            f"MCP tool names changed!\n"
            f"  expected: {sorted(EXPECTED_MCP_TOOL_NAMES)}\n"
            f"  got:      {sorted(names)}"
        )
