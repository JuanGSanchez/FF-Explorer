"""
Test suite for ff_explorer.api.rest — FastAPI REST layer.

Uses FastAPI's TestClient (synchronous, in-process) so no async or
external server is needed.

Confirm-token contract tests (destructive routes):
  - Blank seed -> HTTP 422 (Pydantic min_length=1 rejects it).
  - dry_run=True (default) -> preview response, nothing removed.
  - dry_run=False without confirm=True -> HTTP 422 (ValueError from core).
  - dry_run=False + confirm=True -> live execution path.
"""
from __future__ import annotations

import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Suppress starlette/httpx deprecation warning for TestClient
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from ff_explorer.api.rest import app


@pytest.fixture(scope="module")
def client():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def rest_file_tree(tmp_path: Path) -> Path:
    """Files tree for REST destructive tests."""
    (tmp_path / "keep.txt").write_text("keep")
    (tmp_path / "target_a.txt").write_text("a")
    (tmp_path / "target_b.txt").write_text("b")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "target_sub.txt").write_text("sub")
    return tmp_path


@pytest.fixture()
def rest_folder_tree(tmp_path: Path) -> Path:
    """Folders tree for REST compress tests."""
    fd = tmp_path / "zip_me"
    fd.mkdir()
    (fd / "inside.txt").write_text("x")
    other = tmp_path / "other"
    other.mkdir()
    (other / "stay.txt").write_text("y")
    return tmp_path


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_version_is_string(self, client):
        resp = client.get("/health")
        assert isinstance(resp.json()["version"], str)


# ---------------------------------------------------------------------------
# POST /entries
# ---------------------------------------------------------------------------

class TestPostEntries:
    def test_list_files(self, client, rest_file_tree):
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 2
        for e in data["entries"]:
            assert "target" in Path(e["path"]).name

    def test_list_all_files_empty_seed(self, client, rest_file_tree):
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "",
        })
        assert resp.status_code == 200
        assert resp.json()["count"] >= 3

    def test_list_folders(self, client, rest_file_tree):
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 0, "name_seed": "",
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "sub" in names

    def test_invalid_path_422(self, client, tmp_path):
        resp = client.post("/entries", json={
            "path": str(tmp_path / "no_such"), "kind": 1,
        })
        assert resp.status_code == 422

    def test_case_insensitive(self, client, rest_file_tree):
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1,
            "name_seed": "TARGET", "case_sensitive": False,
        })
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2

    def test_case_sensitive_no_match(self, client, rest_file_tree):
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1,
            "name_seed": "TARGET", "case_sensitive": True,
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# POST /metadata
# ---------------------------------------------------------------------------

class TestPostMetadata:
    def test_file_metadata(self, client, rest_file_tree):
        target = rest_file_tree / "keep.txt"
        resp = client.post("/metadata", json={"path": str(target)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "file"
        assert data["exists"] is True
        assert data["size_bytes"] >= 0

    def test_directory_metadata(self, client, rest_file_tree):
        resp = client.post("/metadata", json={"path": str(rest_file_tree)})
        assert resp.status_code == 200
        assert resp.json()["type"] == "directory"

    def test_nonexistent_404(self, client, tmp_path):
        resp = client.post("/metadata", json={"path": str(tmp_path / "ghost.txt")})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /listing
# ---------------------------------------------------------------------------

class TestPostListing:
    def test_creates_listing_file(self, client, rest_file_tree):
        resp = client.post("/listing", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        assert resp.status_code == 200
        listing_path = Path(resp.json()["listing_path"])
        assert listing_path.exists()
        assert listing_path.suffix == ".txt"

    def test_listing_content(self, client, rest_file_tree):
        resp = client.post("/listing", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "keep",
        })
        listing_path = Path(resp.json()["listing_path"])
        content = listing_path.read_text(encoding="utf-8")
        assert "keep.txt" in content

    def test_invalid_path_422(self, client, tmp_path):
        resp = client.post("/listing", json={
            "path": str(tmp_path / "no_dir"), "kind": 1,
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /remove — confirm-token contract
# ---------------------------------------------------------------------------

class TestPostRemove:
    # Blank seed -> 422 (Pydantic min_length=1 before core even runs)
    def test_blank_seed_422(self, client, rest_file_tree):
        # Pydantic's min_length=1 rejects empty string with HTTP 422
        resp = client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "",
        })
        assert resp.status_code == 422

    # dry_run=True (default) — preview only
    def test_dry_run_default_preview(self, client, rest_file_tree):
        resp = client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert len(data["matched"]) >= 2
        assert data["removed"] == []
        # Files still exist
        assert (rest_file_tree / "target_a.txt").exists()

    def test_explicit_dry_run_true_nothing_removed(self, client, rest_file_tree):
        resp = client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
            "dry_run": True, "confirm": False,
        })
        assert resp.status_code == 200
        assert resp.json()["removed"] == []
        assert (rest_file_tree / "target_a.txt").exists()

    # dry_run=False without confirm=True -> 422
    def test_dry_run_false_no_confirm_422(self, client, rest_file_tree):
        resp = client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
            "dry_run": False, "confirm": False,
        })
        assert resp.status_code == 422

    def test_dry_run_false_no_confirm_nothing_removed(self, client, rest_file_tree):
        client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
            "dry_run": False, "confirm": False,
        })
        assert (rest_file_tree / "target_a.txt").exists()

    # dry_run=False + confirm=True -> live removal via send2trash
    def test_live_remove_calls_send2trash(self, client, rest_file_tree):
        with patch("ff_explorer.core._send2trash") as mock_trash, \
             patch("ff_explorer.core._SEND2TRASH_AVAILABLE", True):
            resp = client.post("/remove", json={
                "path": str(rest_file_tree), "kind": 1, "name_seed": "target_a",
                "dry_run": False, "confirm": True,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is False
        assert mock_trash.called

    def test_response_model_fields(self, client, rest_file_tree):
        resp = client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        data = resp.json()
        assert set(data.keys()) >= {"dry_run", "matched", "removed", "failed", "would_affect"}

    def test_would_affect_equals_matched(self, client, rest_file_tree):
        resp = client.post("/remove", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        data = resp.json()
        assert sorted(data["would_affect"]) == sorted(data["matched"])


# ---------------------------------------------------------------------------
# POST /compress — confirm-token contract
# ---------------------------------------------------------------------------

class TestPostCompress:
    # Blank seed -> 422 (Pydantic min_length=1)
    def test_blank_seed_422(self, client, rest_folder_tree):
        resp = client.post("/compress", json={
            "path": str(rest_folder_tree), "kind": 0, "name_seed": "",
        })
        assert resp.status_code == 422

    # dry_run=True (default) — preview only
    def test_dry_run_default_preview(self, client, rest_folder_tree):
        resp = client.post("/compress", json={
            "path": str(rest_folder_tree), "kind": 0, "name_seed": "zip_me",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["archives"] == []
        assert list(rest_folder_tree.glob("*.zip")) == []

    # dry_run=False without confirm=True -> 422
    def test_dry_run_false_no_confirm_422(self, client, rest_folder_tree):
        resp = client.post("/compress", json={
            "path": str(rest_folder_tree), "kind": 0, "name_seed": "zip_me",
            "dry_run": False, "confirm": False,
        })
        assert resp.status_code == 422

    # dry_run=False + confirm=True -> live compress
    def test_live_compress_creates_zip(self, client, rest_folder_tree):
        resp = client.post("/compress", json={
            "path": str(rest_folder_tree), "kind": 0, "name_seed": "zip_me",
            "dry_run": False, "confirm": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is False
        assert len(data["archives"]) == 1
        archive_path = Path(data["archives"][0])
        assert archive_path.exists()
        with zipfile.ZipFile(archive_path) as zf:
            assert "inside.txt" in zf.namelist()

    def test_response_model_fields(self, client, rest_folder_tree):
        resp = client.post("/compress", json={
            "path": str(rest_folder_tree), "kind": 0, "name_seed": "zip_me",
        })
        data = resp.json()
        assert set(data.keys()) >= {"dry_run", "matched", "archives", "failed", "would_affect"}
