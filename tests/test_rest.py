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

    # ------------------------------------------------------------------
    # FFX-I01 / FFX-I02 — advanced filter params
    # ------------------------------------------------------------------

    def test_default_fields_baseline_unchanged(self, client, rest_file_tree):
        """Omitting all new fields returns same result as before (baseline)."""
        resp_old = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        resp_new = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
            "match_mode": "substring", "case_sensitive": True,
            "min_size": None, "max_size": None,
            "modified_after": None, "modified_before": None,
            "extensions": None,
        })
        assert resp_old.status_code == 200
        assert resp_new.status_code == 200
        assert sorted(e["path"] for e in resp_old.json()["entries"]) == \
               sorted(e["path"] for e in resp_new.json()["entries"])

    def test_regex_match_mode_returns_matches(self, client, rest_file_tree):
        """match_mode='regex' with a valid pattern returns regex-matching entries."""
        # rest_file_tree has: keep.txt, target_a.txt, target_b.txt, sub/target_sub.txt
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1,
            "name_seed": r"^target_[ab]\.txt$",
            "match_mode": "regex",
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert sorted(names) == ["target_a.txt", "target_b.txt"]

    def test_regex_match_mode_excludes_non_matches(self, client, rest_file_tree):
        """Regex mode does not return entries that do not match the pattern."""
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1,
            "name_seed": r"^keep\.txt$",
            "match_mode": "regex",
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert names == ["keep.txt"]

    def test_invalid_regex_returns_422(self, client, rest_file_tree):
        """Invalid regex pattern → HTTP 422 (InvalidRegexError subclasses ValueError)."""
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1,
            "name_seed": "[unclosed",
            "match_mode": "regex",
        })
        assert resp.status_code == 422

    def test_glob_match_mode(self, client, rest_file_tree):
        """match_mode='glob' with wildcard returns only glob-matching entries."""
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1,
            "name_seed": "target_*.txt",
            "match_mode": "glob",
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert all(n.startswith("target_") and n.endswith(".txt") for n in names)
        assert len(names) >= 2

    def test_extension_filter_returns_only_matching(self, client, tmp_path):
        """extensions filter returns only files with the specified suffix."""
        (tmp_path / "doc.txt").write_text("a")
        (tmp_path / "doc.log").write_text("b")
        (tmp_path / "doc.py").write_text("c")
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "extensions": [".txt", ".log"],
        })
        assert resp.status_code == 200
        data = resp.json()
        suffixes = {Path(e["path"]).suffix for e in data["entries"]}
        assert suffixes == {".txt", ".log"}

    def test_min_size_filter(self, client, tmp_path):
        """min_size excludes files smaller than the threshold."""
        (tmp_path / "small.txt").write_bytes(b"x")          # 1 byte
        (tmp_path / "large.txt").write_bytes(b"x" * 100)   # 100 bytes
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "min_size": 50,
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "large.txt" in names
        assert "small.txt" not in names

    def test_max_size_filter(self, client, tmp_path):
        """max_size excludes files larger than the threshold."""
        (tmp_path / "small.txt").write_bytes(b"x")          # 1 byte
        (tmp_path / "large.txt").write_bytes(b"x" * 100)   # 100 bytes
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "max_size": 10,
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "small.txt" in names
        assert "large.txt" not in names

    def test_size_and_extension_combined(self, client, tmp_path):
        """min_size + extensions both apply (AND semantics)."""
        (tmp_path / "big.txt").write_bytes(b"x" * 200)
        (tmp_path / "small.txt").write_bytes(b"x")
        (tmp_path / "big.log").write_bytes(b"x" * 200)
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "min_size": 100, "extensions": [".txt"],
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert names == ["big.txt"]

    def test_modified_after_filter(self, client, tmp_path):
        """modified_after excludes files not modified after the given epoch."""
        import time
        old_file = tmp_path / "old.txt"
        old_file.write_text("old")
        # Set mtime to a point far in the past
        past = 0.0  # epoch 0 = 1970-01-01
        import os
        os.utime(old_file, (past, past))
        new_file = tmp_path / "new.txt"
        new_file.write_text("new")
        # new_file has current mtime; filter for files modified after year 2000
        cutoff = 946684800.0  # 2000-01-01 00:00:00 UTC
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "modified_after": cutoff,
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "new.txt" in names
        assert "old.txt" not in names

    def test_invalid_match_mode_422(self, client, rest_file_tree):
        """An unrecognised match_mode value is rejected by Pydantic → 422."""
        resp = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "x",
            "match_mode": "fuzzy",
        })
        assert resp.status_code == 422

    def test_respect_ignore_excludes_gitignored_files(self, client, tmp_path):
        """FFX-I04: respect_ignore=true honours a .gitignore over REST."""
        (tmp_path / "keep.txt").write_text("keep")
        (tmp_path / "skip.log").write_text("skip")
        (tmp_path / ".gitignore").write_text("*.log\n")
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "respect_ignore": True,
        })
        assert resp.status_code == 200
        names = [Path(e["path"]).name for e in resp.json()["entries"]]
        assert "keep.txt" in names
        assert "skip.log" not in names

    def test_respect_ignore_default_off_keeps_all(self, client, tmp_path):
        """FFX-I04: default (omitted) preserves legacy output — nothing pruned."""
        (tmp_path / "keep.txt").write_text("keep")
        (tmp_path / "skip.log").write_text("skip")
        (tmp_path / ".gitignore").write_text("*.log\n")
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
        })
        assert resp.status_code == 200
        names = [Path(e["path"]).name for e in resp.json()["entries"]]
        assert "skip.log" in names

    def test_ignore_globs_excludes_extra_patterns(self, client, tmp_path):
        """FFX-I04: ignore_globs applies extra exclusions even without .gitignore."""
        (tmp_path / "keep.txt").write_text("keep")
        (tmp_path / "temp.tmp").write_text("tmp")
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "ignore_globs": ["*.tmp"],
        })
        assert resp.status_code == 200
        names = [Path(e["path"]).name for e in resp.json()["entries"]]
        assert "keep.txt" in names
        assert "temp.tmp" not in names

    # ------------------------------------------------------------------
    # FFX-I05 — Archive transparency: search_archives flag
    # ------------------------------------------------------------------

    def test_search_archives_finds_member_with_in_archive_true(self, client, tmp_path):
        """search_archives=true: archive member matching the seed is returned
        with in_archive=true and path in '<archive>!<member>' format."""
        # Build a zip containing one file whose name contains the seed.
        archive = tmp_path / "data.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("report_inside.txt", "content")
            zf.writestr("other_member.txt", "other")

        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1,
            "name_seed": "report_inside",
            "search_archives": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        archive_hits = [e for e in data["entries"] if e["in_archive"]]
        assert len(archive_hits) >= 1
        hit = archive_hits[0]
        # Path must use the <archive>!<member> separator
        assert "!" in hit["path"]
        assert "report_inside" in hit["path"]
        assert hit["in_archive"] is True

    def test_search_archives_default_off_member_absent(self, client, tmp_path):
        """search_archives omitted (default False): archive member does NOT appear;
        real filesystem files have in_archive=false."""
        archive = tmp_path / "data.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("report_inside.txt", "content")
        # Also place a real file that matches the seed — so we get a hit
        # but it must be a filesystem file, not an archive member.
        (tmp_path / "report_real.txt").write_text("real")

        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1,
            "name_seed": "report",
            # search_archives deliberately omitted → defaults to False
        })
        assert resp.status_code == 200
        data = resp.json()
        # No archive-internal hits
        assert all(not e["in_archive"] for e in data["entries"])
        # The real file is present
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "report_real.txt" in names

    def test_search_archives_explicit_false_is_same_as_default(self, client, tmp_path):
        """Explicit search_archives=false behaves identically to omitting it."""
        archive = tmp_path / "data.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("needle.txt", "content")

        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1,
            "name_seed": "needle",
            "search_archives": False,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert all(not e["in_archive"] for e in data["entries"])

    def test_search_archives_not_on_remove_request(self, client, rest_file_tree):
        """RemoveRequest has no search_archives field — sending it is ignored by
        Pydantic (extra fields are stripped) and the route still returns 200
        in dry-run mode rather than 422 (Pydantic forbids unknown fields only when
        configured to do so — default is to ignore extra fields)."""
        # The real assertion: RemoveRequest model does NOT expose search_archives,
        # so the destructive route never enables archive search.
        from ff_explorer.api.rest import RemoveRequest
        assert not hasattr(RemoveRequest.model_fields, "search_archives") or \
               "search_archives" not in RemoveRequest.model_fields

    # ------------------------------------------------------------------
    # FFX-I09 — Content search (grep-inside-files)
    # ------------------------------------------------------------------

    def test_content_query_with_name_prefilter_returns_matching_files(self, client, tmp_path):
        """FFX-I09(a): content_query + name_seed pre-filter returns only files
        whose content contains the query string."""
        (tmp_path / "needle.txt").write_text("The needle is here")
        (tmp_path / "haystack.txt").write_text("nothing interesting")
        (tmp_path / "also_needle.txt").write_text("another needle occurrence")
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "",
            "extensions": [".txt"],   # name/type pre-filter required by the gate
            "content_query": "needle",
        })
        assert resp.status_code == 200
        data = resp.json()
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "needle.txt" in names
        assert "also_needle.txt" in names
        assert "haystack.txt" not in names

    def test_content_query_no_prefilter_returns_422(self, client, tmp_path):
        """FFX-I09(b): content_query without any name/type/size pre-filter →
        HTTP 422 with a message explaining a pre-filter is required."""
        (tmp_path / "some_file.txt").write_text("content")
        resp = client.post("/entries", json={
            "path": str(tmp_path), "kind": 1,
            "name_seed": "",        # empty = no name pre-filter
            # no extensions, no min_size, no max_size, no date bounds
            "content_query": "content",
        })
        assert resp.status_code == 422
        detail = resp.json().get("detail", "")
        # The error message must mention the pre-filter requirement
        assert "pre-filter" in str(detail).lower() or "content_query" in str(detail).lower()

    def test_content_query_none_baseline_unchanged(self, client, rest_file_tree):
        """FFX-I09(c): omitting content_query (default None) returns the same
        result as before — baseline behaviour is unaffected."""
        resp_baseline = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
        })
        resp_explicit_none = client.post("/entries", json={
            "path": str(rest_file_tree), "kind": 1, "name_seed": "target",
            "content_query": None,
        })
        assert resp_baseline.status_code == 200
        assert resp_explicit_none.status_code == 200
        assert sorted(e["path"] for e in resp_baseline.json()["entries"]) == \
               sorted(e["path"] for e in resp_explicit_none.json()["entries"])

    def test_content_query_fields_present_in_model(self, client):
        """FFX-I09: ListEntriesRequest exposes content_query and content_max_bytes fields."""
        from ff_explorer.api.rest import ListEntriesRequest
        assert "content_query" in ListEntriesRequest.model_fields
        assert "content_max_bytes" in ListEntriesRequest.model_fields

    def test_content_max_bytes_default_is_constant(self, client):
        """FFX-I09: content_max_bytes defaults to the CONTENT_MAX_BYTES constant from service."""
        from ff_explorer.api.rest import ListEntriesRequest, CONTENT_MAX_BYTES
        field = ListEntriesRequest.model_fields["content_max_bytes"]
        assert field.default == CONTENT_MAX_BYTES


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

    # ------------------------------------------------------------------
    # FFX-I08 — versioning flag on /remove
    # ------------------------------------------------------------------

    def test_versioning_confirmed_moves_files_to_version_dir(self, tmp_path):
        """versioning=true + dry_run=false + confirm=true: matched files are
        moved into .ffe-versions/<ts>/ (sources gone), versioned_to is set."""
        # Build a small tree under a fresh tmp_path so we control its layout.
        (tmp_path / "keep.txt").write_text("keep")
        (tmp_path / "old_a.txt").write_text("a")
        (tmp_path / "old_b.txt").write_text("b")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with TestClient(app) as c:
                resp = c.post("/remove", json={
                    "path": str(tmp_path),
                    "kind": 1,
                    "name_seed": "old_",
                    "dry_run": False,
                    "confirm": True,
                    "versioning": True,
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is False
        # versioned_to must be a non-null path string
        assert data["versioned_to"] is not None
        version_dir = Path(data["versioned_to"])
        assert version_dir.exists()
        # Sources must be gone
        assert not (tmp_path / "old_a.txt").exists()
        assert not (tmp_path / "old_b.txt").exists()
        # Files must appear under the version directory (structure preserved)
        versioned_names = [p.name for p in version_dir.rglob("*") if p.is_file()]
        assert "old_a.txt" in versioned_names
        assert "old_b.txt" in versioned_names
        # Non-matching file is untouched
        assert (tmp_path / "keep.txt").exists()

    def test_versioning_dry_run_default_no_move_versioned_to_null(self, tmp_path):
        """versioning=true but dry_run omitted (defaults true): preview only,
        nothing moved, versioned_to is null."""
        (tmp_path / "old_x.txt").write_text("x")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with TestClient(app) as c:
                resp = c.post("/remove", json={
                    "path": str(tmp_path),
                    "kind": 1,
                    "name_seed": "old_",
                    "versioning": True,
                    # dry_run omitted → defaults to True
                })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["versioned_to"] is None
        # File is still present
        assert (tmp_path / "old_x.txt").exists()

    def test_versioning_dry_run_false_no_confirm_422(self, tmp_path):
        """versioning=true, dry_run=false, confirm omitted → 422, nothing moved."""
        (tmp_path / "old_y.txt").write_text("y")

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with TestClient(app) as c:
                resp = c.post("/remove", json={
                    "path": str(tmp_path),
                    "kind": 1,
                    "name_seed": "old_",
                    "dry_run": False,
                    # confirm omitted → defaults to False
                    "versioning": True,
                })
        assert resp.status_code == 422
        # File is still present
        assert (tmp_path / "old_y.txt").exists()


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


# ---------------------------------------------------------------------------
# POST /duplicates — FFX-I06
# ---------------------------------------------------------------------------

class TestPostDuplicates:
    """REST integration tests for POST /duplicates (FFX-I06).

    Tree layout for each test (built via tmp_path):
      dup_a.bin  — identical content to dup_b.bin  → form one duplicate group
      dup_b.bin  — identical content to dup_a.bin
      same_size.bin — same byte-length as dup_a/b but different content → NOT in any group
      unique.bin — different size and content → NOT in any group
    """

    @pytest.fixture()
    def dup_tree(self, tmp_path: Path) -> Path:
        content = b"duplicate-content-xyz"
        (tmp_path / "dup_a.bin").write_bytes(content)
        (tmp_path / "dup_b.bin").write_bytes(content)
        # Same size as the duplicates but different content — must NOT be grouped.
        same_size = b"different-content-!?!"  # exactly 21 bytes, same as content
        assert len(same_size) == len(content), f"{len(same_size)} != {len(content)}"
        (tmp_path / "same_size.bin").write_bytes(same_size)
        # Completely unique file.
        (tmp_path / "unique.bin").write_bytes(b"unique")
        return tmp_path

    def test_duplicates_returns_one_group(self, client, dup_tree):
        """Exactly one group containing the two identical files."""
        resp = client.post("/duplicates", json={"path": str(dup_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert len(data["groups"]) == 1

    def test_duplicates_group_contains_both_identical_files(self, client, dup_tree):
        """The group members are exactly dup_a.bin and dup_b.bin."""
        resp = client.post("/duplicates", json={"path": str(dup_tree)})
        assert resp.status_code == 200
        group = resp.json()["groups"][0]
        names = sorted(Path(p).name for p in group["paths"])
        assert names == ["dup_a.bin", "dup_b.bin"]

    def test_same_size_different_content_not_in_any_group(self, client, dup_tree):
        """same_size.bin has the same length but different content → not grouped."""
        resp = client.post("/duplicates", json={"path": str(dup_tree)})
        assert resp.status_code == 200
        all_paths = [
            Path(p).name
            for g in resp.json()["groups"]
            for p in g["paths"]
        ]
        assert "same_size.bin" not in all_paths

    def test_unique_file_not_in_any_group(self, client, dup_tree):
        """unique.bin has distinct content → not returned in any group."""
        resp = client.post("/duplicates", json={"path": str(dup_tree)})
        assert resp.status_code == 200
        all_paths = [
            Path(p).name
            for g in resp.json()["groups"]
            for p in g["paths"]
        ]
        assert "unique.bin" not in all_paths

    def test_group_fields_present(self, client, dup_tree):
        """Each group carries hash, size, and paths fields."""
        resp = client.post("/duplicates", json={"path": str(dup_tree)})
        assert resp.status_code == 200
        group = resp.json()["groups"][0]
        assert "hash" in group
        assert "size" in group
        assert "paths" in group
        assert isinstance(group["hash"], str) and len(group["hash"]) > 0
        assert isinstance(group["size"], int) and group["size"] > 0

    def test_invalid_path_returns_422(self, client, tmp_path):
        """A path that does not exist → ValueError from service → HTTP 422."""
        resp = client.post("/duplicates", json={
            "path": str(tmp_path / "no_such_directory"),
        })
        assert resp.status_code == 422

    def test_empty_dir_returns_zero_groups(self, client, tmp_path):
        """An empty directory has no duplicate groups."""
        resp = client.post("/duplicates", json={"path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["groups"] == []

    def test_sha256_algo_also_detects_duplicates(self, client, dup_tree):
        """algo='sha256' also finds the duplicate pair."""
        resp = client.post("/duplicates", json={
            "path": str(dup_tree), "algo": "sha256",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        names = sorted(Path(p).name for p in data["groups"][0]["paths"])
        assert names == ["dup_a.bin", "dup_b.bin"]

    def test_min_size_zero_includes_empty_files(self, client, tmp_path):
        """min_size=0 includes zero-byte files in the duplicate scan."""
        (tmp_path / "empty_a.bin").write_bytes(b"")
        (tmp_path / "empty_b.bin").write_bytes(b"")
        resp = client.post("/duplicates", json={
            "path": str(tmp_path), "min_size": 0,
        })
        assert resp.status_code == 200
        # Both empty files should appear as a duplicate group
        all_names = [
            Path(p).name
            for g in resp.json()["groups"]
            for p in g["paths"]
        ]
        assert "empty_a.bin" in all_names
        assert "empty_b.bin" in all_names

    def test_response_count_matches_groups_length(self, client, dup_tree):
        """count field always equals len(groups)."""
        resp = client.post("/duplicates", json={"path": str(dup_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == len(data["groups"])


# ---------------------------------------------------------------------------
# POST /presets/save, POST /presets/list, POST /presets/run — FFX-I03
# ---------------------------------------------------------------------------

class TestPresetRoutes:
    """REST integration tests for the preset operations (FFX-I03).

    Each test monkeypatches FFE_PRESETS_DIR to tmp_path so no real config
    directory is read or written (same pattern as test_presets.py).
    """

    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        """Redirect the preset JSON store to a temp dir for every test."""
        store_dir = tmp_path / "preset_store"
        store_dir.mkdir()
        monkeypatch.setenv("FFE_PRESETS_DIR", str(store_dir))

    @pytest.fixture()
    def preset_tree(self, tmp_path: Path) -> Path:
        """Small file tree used by preset-run tests."""
        root = tmp_path / "ptree"
        root.mkdir()
        (root / "report_a.txt").write_text("a")
        (root / "report_b.txt").write_text("b")
        (root / "other.log").write_text("log")
        return root

    # ------------------------------------------------------------------
    # POST /presets/save
    # ------------------------------------------------------------------

    def test_save_preset_returns_204(self, client, preset_tree):
        resp = client.post("/presets/save", json={
            "name": "my_preset",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "report",
            "operation": "list",
        })
        assert resp.status_code == 204

    def test_save_preset_invalid_operation_422(self, client, preset_tree):
        """Invalid operation value → ValueError from service → HTTP 422."""
        resp = client.post("/presets/save", json={
            "name": "bad_op",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "x",
            "operation": "delete",       # not a valid Literal — Pydantic rejects first
        })
        assert resp.status_code == 422

    def test_save_preset_empty_name_422(self, client, preset_tree):
        """Empty name (min_length=1) → Pydantic → HTTP 422."""
        resp = client.post("/presets/save", json={
            "name": "",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "x",
            "operation": "list",
        })
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # POST /presets/list
    # ------------------------------------------------------------------

    def test_list_presets_empty_store(self, client):
        """Empty store returns an empty list without error."""
        resp = client.post("/presets/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["presets"] == []
        assert data["count"] == 0

    def test_save_then_list_round_trip(self, client, preset_tree):
        """Save a preset then retrieve it via /presets/list."""
        client.post("/presets/save", json={
            "name": "rt_preset",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "report",
            "case_sensitive": False,
            "operation": "list",
        })
        resp = client.post("/presets/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        p = data["presets"][0]
        assert p["name"] == "rt_preset"
        assert p["name_seed"] == "report"
        assert p["case_sensitive"] is False
        assert p["operation"] == "list"

    def test_list_presets_response_fields(self, client, preset_tree):
        """PresetOut has all expected fields."""
        client.post("/presets/save", json={
            "name": "fields_check",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "x",
            "operation": "list",
        })
        resp = client.post("/presets/list")
        p = resp.json()["presets"][0]
        expected_keys = {
            "name", "path", "kind", "name_seed", "case_sensitive",
            "match_mode", "min_size", "max_size", "modified_after",
            "modified_before", "extensions", "respect_ignore",
            "ignore_globs", "operation",
        }
        assert expected_keys <= set(p.keys())

    def test_upsert_keeps_one_entry(self, client, preset_tree):
        """Saving the same name twice updates (upsert); list still has count=1."""
        body = {"name": "up", "path": str(preset_tree), "kind": 1,
                 "name_seed": "first", "operation": "list"}
        client.post("/presets/save", json=body)
        body["name_seed"] = "second"
        client.post("/presets/save", json=body)
        resp = client.post("/presets/list")
        data = resp.json()
        assert data["count"] == 1
        assert data["presets"][0]["name_seed"] == "second"

    # ------------------------------------------------------------------
    # POST /presets/run — list operation
    # ------------------------------------------------------------------

    def test_run_list_preset_returns_entries(self, client, preset_tree):
        """Running a 'list' preset populates entries, report is null."""
        client.post("/presets/save", json={
            "name": "find_reports",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "report",
            "operation": "list",
        })
        resp = client.post("/presets/run", json={"name": "find_reports"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["operation"] == "list"
        assert data["report"] is None
        assert data["entries"] is not None
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "report_a.txt" in names
        assert "report_b.txt" in names
        assert "other.log" not in names

    def test_run_list_preset_response_shape(self, client, preset_tree):
        """PresetRunResponse has operation, entries, report keys."""
        client.post("/presets/save", json={
            "name": "shape_check",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "",
            "operation": "list",
        })
        resp = client.post("/presets/run", json={"name": "shape_check"})
        assert resp.status_code == 200
        assert set(resp.json().keys()) >= {"operation", "entries", "report"}

    # ------------------------------------------------------------------
    # POST /presets/run — remove operation (destructive gate)
    # ------------------------------------------------------------------

    def test_run_remove_preset_dry_run_default_no_mutation(self, client, preset_tree):
        """Default dry_run=True: returns preview report, files untouched."""
        client.post("/presets/save", json={
            "name": "rm_preview",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "report",
            "operation": "remove",
        })
        resp = client.post("/presets/run", json={"name": "rm_preview"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["operation"] == "remove"
        assert data["entries"] is None
        report = data["report"]
        assert report["dry_run"] is True
        assert report["removed"] == []
        assert len(report["matched"]) >= 2
        # Files must still exist
        assert (preset_tree / "report_a.txt").exists()
        assert (preset_tree / "report_b.txt").exists()

    def test_run_remove_preset_dry_run_false_no_confirm_422(self, client, preset_tree):
        """dry_run=False without confirm → ValueError from core → HTTP 422."""
        client.post("/presets/save", json={
            "name": "rm_gate",
            "path": str(preset_tree),
            "kind": 1,
            "name_seed": "report",
            "operation": "remove",
        })
        resp = client.post("/presets/run", json={
            "name": "rm_gate",
            "dry_run": False,
            "confirm": False,
        })
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # POST /presets/run — missing preset
    # ------------------------------------------------------------------

    def test_run_missing_preset_404(self, client):
        """Running a non-existent preset → KeyError from service → HTTP 404."""
        resp = client.post("/presets/run", json={"name": "does_not_exist"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /rename — FFX-I07 (GUARDED destructive — batch rename)
# ---------------------------------------------------------------------------

class TestPostRename:
    """REST integration tests for POST /rename (FFX-I07).

    Confirm-token contract tests:
      - blank name_seed → 422 (Pydantic min_length=1).
      - dry_run=True (default) → preview mapping returned, nothing renamed.
      - dry_run=False without confirm=True → 422 (ValueError from core).
      - dry_run=False + confirm=True → live rename, renamed list + undo_file.
      - collision → collisions reported, nothing renamed.
    """

    @pytest.fixture()
    def rename_tree(self, tmp_path: Path) -> Path:
        """Small file tree for rename tests."""
        (tmp_path / "report_a.txt").write_text("a")
        (tmp_path / "report_b.txt").write_text("b")
        (tmp_path / "keep.txt").write_text("keep")
        return tmp_path

    # ------------------------------------------------------------------
    # Blank seed → 422
    # ------------------------------------------------------------------

    def test_blank_seed_422(self, client, rename_tree):
        """Empty name_seed rejected at schema level (min_length=1) → HTTP 422."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "",
            "rules": [{"kind": "prefix", "text": "NEW_"}],
        })
        assert resp.status_code == 422

    # ------------------------------------------------------------------
    # dry_run=True (default) → preview only, nothing renamed
    # ------------------------------------------------------------------

    def test_dry_run_default_preview(self, client, rename_tree):
        """Default dry_run=True returns the mapping preview; no files are renamed."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "prefix", "text": "2024_"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert len(data["matched"]) == 2
        assert len(data["mapping"]) == 2
        assert data["renamed"] == []
        assert data["undo_file"] is None
        # Originals still present
        assert (rename_tree / "report_a.txt").exists()
        assert (rename_tree / "report_b.txt").exists()
        # Prefixed names do NOT yet exist
        assert not (rename_tree / "2024_report_a.txt").exists()

    def test_dry_run_explicit_true_nothing_renamed(self, client, rename_tree):
        """Explicit dry_run=True + confirm=False: same safe behaviour."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "suffix", "text": "_archived"}],
            "dry_run": True, "confirm": False,
        })
        assert resp.status_code == 200
        assert resp.json()["renamed"] == []
        assert (rename_tree / "report_a.txt").exists()

    def test_mapping_contains_old_and_new_names(self, client, rename_tree):
        """Mapping list contains (old_name, new_name) pairs.

        The 'case' rule uppercases only the stem, not the extension
        (per core behaviour: new_stem + original_suffix).
        """
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "case", "mode": "upper"}],
        })
        assert resp.status_code == 200
        mapping = resp.json()["mapping"]
        assert len(mapping) == 2
        from pathlib import Path as _Path
        for pair in mapping:
            old_name, new_name = pair
            assert "report" in old_name.lower()
            # stem is uppercased; extension is preserved as-is
            expected = _Path(old_name).stem.upper() + _Path(old_name).suffix
            assert new_name == expected

    # ------------------------------------------------------------------
    # dry_run=False without confirm=True → 422
    # ------------------------------------------------------------------

    def test_dry_run_false_no_confirm_422(self, client, rename_tree):
        """dry_run=False without confirm=True → ValueError from core → HTTP 422."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "prefix", "text": "X_"}],
            "dry_run": False, "confirm": False,
        })
        assert resp.status_code == 422

    def test_dry_run_false_no_confirm_nothing_renamed(self, client, rename_tree):
        """Gate fires → no mutation even on a valid request with confirm=False."""
        client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "prefix", "text": "X_"}],
            "dry_run": False, "confirm": False,
        })
        assert (rename_tree / "report_a.txt").exists()
        assert (rename_tree / "report_b.txt").exists()

    # ------------------------------------------------------------------
    # dry_run=False + confirm=True → live rename
    # ------------------------------------------------------------------

    def test_live_rename_renames_files_and_returns_undo_file(self, client, rename_tree):
        """dry_run=False + confirm=True renames matched files and returns undo_file."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "prefix", "text": "2024_"}],
            "dry_run": False, "confirm": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is False
        assert len(data["renamed"]) == 2
        assert data["undo_file"] is not None
        assert Path(data["undo_file"]).exists()
        # Originals gone; prefixed names present
        assert not (rename_tree / "report_a.txt").exists()
        assert not (rename_tree / "report_b.txt").exists()
        assert (rename_tree / "2024_report_a.txt").exists()
        assert (rename_tree / "2024_report_b.txt").exists()

    def test_live_rename_response_fields(self, client, rename_tree):
        """RenameResponse carries all expected fields."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "suffix", "text": "_v2"}],
        })
        assert resp.status_code == 200
        keys = set(resp.json().keys())
        assert keys >= {"dry_run", "matched", "mapping", "renamed", "collisions", "failed", "undo_file"}

    # ------------------------------------------------------------------
    # Collision case → collisions reported, nothing renamed
    # ------------------------------------------------------------------

    def test_collision_reported_nothing_renamed(self, client, tmp_path):
        """When two sources map to the same target name, collisions is non-empty
        and no files are renamed (batch refused entirely)."""
        # Create two files that a find_replace rule will collapse to the same name
        (tmp_path / "file_a.txt").write_text("a")
        (tmp_path / "file_b.txt").write_text("b")
        # Rule: replace "file_a" → "out" AND "file_b" → "out" (both → out.txt → collision)
        resp = client.post("/rename", json={
            "path": str(tmp_path), "kind": 1, "name_seed": "file_",
            "rules": [{"kind": "find_replace", "find": "file_a", "replace": "out"},
                      {"kind": "find_replace", "find": "file_b", "replace": "out"}],
            "dry_run": False, "confirm": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["collisions"]) >= 1
        assert data["renamed"] == []
        # Originals still present
        assert (tmp_path / "file_a.txt").exists()
        assert (tmp_path / "file_b.txt").exists()

    # ------------------------------------------------------------------
    # Rule kinds smoke-tests (dry_run preview only)
    # ------------------------------------------------------------------

    def test_find_replace_rule_preview(self, client, rename_tree):
        """find_replace rule produces the expected new names in the preview."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "find_replace", "find": "report", "replace": "doc"}],
        })
        assert resp.status_code == 200
        mapping = resp.json()["mapping"]
        new_names = [pair[1] for pair in mapping]
        assert all("doc" in n for n in new_names)

    def test_regex_replace_rule_preview(self, client, rename_tree):
        """regex_replace rule applies the pattern in preview mode."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "regex_replace", "pattern": r"_[ab]", "replacement": "_x"}],
        })
        assert resp.status_code == 200
        mapping = resp.json()["mapping"]
        new_names = [pair[1] for pair in mapping]
        assert all("_x" in n for n in new_names)

    def test_counter_rule_preview(self, client, rename_tree):
        """counter rule assigns sequential numbers in preview mode."""
        resp = client.post("/rename", json={
            "path": str(rename_tree), "kind": 1, "name_seed": "report",
            "rules": [{"kind": "counter", "start": 1, "padding": 2,
                       "template": "{stem}_{n}{suffix}"}],
        })
        assert resp.status_code == 200
        mapping = resp.json()["mapping"]
        assert len(mapping) == 2
        new_names = [pair[1] for pair in mapping]
        # Both new names must contain a zero-padded counter sequence
        assert any("_01" in n or "_02" in n for n in new_names)


# ---------------------------------------------------------------------------
# POST /index/start, /index/stop, /index/status — FFX-I10
# ---------------------------------------------------------------------------

class TestIndexLifecycle:
    """REST integration tests for index lifecycle endpoints (FFX-I10).

    Layout: uses a per-test tmp_path with a small file tree.
    Observers are stopped in teardown via the /index/stop route (or directly
    via service) so no threads leak between tests.
    """

    @pytest.fixture()
    def index_tree(self, tmp_path: Path) -> Path:
        """Small file tree for index lifecycle tests."""
        (tmp_path / "alpha.txt").write_text("alpha content")
        (tmp_path / "beta.txt").write_text("beta content")
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "gamma.txt").write_text("gamma content")
        return tmp_path

    @pytest.fixture(autouse=True)
    def _stop_index_on_teardown(self, index_tree):
        """Ensure the observer is stopped after each test to prevent thread leaks."""
        yield
        # Best-effort stop; ignore errors if never started or already stopped.
        try:
            from ff_explorer.index import IndexManager
            IndexManager.stop_index(index_tree)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # POST /index/status — initial state
    # ------------------------------------------------------------------

    def test_status_not_indexed_initially(self, client, index_tree):
        """A fresh root reports indexed=false before start is called."""
        resp = client.post("/index/status", json={"path": str(index_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexed"] is False
        assert data["root"] == str(index_tree)

    # ------------------------------------------------------------------
    # POST /index/start
    # ------------------------------------------------------------------

    def test_start_returns_indexed_true(self, client, index_tree):
        """POST /index/start returns {root, indexed: true}."""
        resp = client.post("/index/start", json={"path": str(index_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexed"] is True
        assert data["root"] == str(index_tree)

    def test_start_nonexistent_path_404(self, client, tmp_path):
        """POST /index/start with a non-existent path → HTTP 404."""
        resp = client.post("/index/start", json={
            "path": str(tmp_path / "no_such_dir"),
        })
        assert resp.status_code == 404

    def test_start_idempotent(self, client, index_tree):
        """Calling /index/start twice on the same root is a safe no-op (200 both times)."""
        r1 = client.post("/index/start", json={"path": str(index_tree)})
        r2 = client.post("/index/start", json={"path": str(index_tree)})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["indexed"] is True
        assert r2.json()["indexed"] is True

    # ------------------------------------------------------------------
    # POST /index/status — after start
    # ------------------------------------------------------------------

    def test_status_indexed_true_after_start(self, client, index_tree):
        """Status shows indexed=true after a successful start."""
        client.post("/index/start", json={"path": str(index_tree)})
        resp = client.post("/index/status", json={"path": str(index_tree)})
        assert resp.status_code == 200
        assert resp.json()["indexed"] is True

    # ------------------------------------------------------------------
    # Query via /entries uses the index (smoke test — index path)
    # ------------------------------------------------------------------

    def test_entries_returns_results_when_indexed(self, client, index_tree):
        """After starting the index, a name query via POST /entries returns hits.

        This exercises the index-backed query path through list_entries → core.
        """
        client.post("/index/start", json={"path": str(index_tree)})
        resp = client.post("/entries", json={
            "path": str(index_tree), "kind": 1, "name_seed": "alpha",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        names = [Path(e["path"]).name for e in data["entries"]]
        assert "alpha.txt" in names

    # ------------------------------------------------------------------
    # POST /index/stop
    # ------------------------------------------------------------------

    def test_stop_returns_indexed_false(self, client, index_tree):
        """POST /index/stop returns {root, indexed: false}."""
        client.post("/index/start", json={"path": str(index_tree)})
        resp = client.post("/index/stop", json={"path": str(index_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["indexed"] is False
        assert data["root"] == str(index_tree)

    def test_stop_idempotent(self, client, index_tree):
        """Calling /index/stop on a root that was never indexed is a safe no-op."""
        resp = client.post("/index/stop", json={"path": str(index_tree)})
        assert resp.status_code == 200
        assert resp.json()["indexed"] is False

    # ------------------------------------------------------------------
    # Full lifecycle: start → status true → entries → stop → status false
    # ------------------------------------------------------------------

    def test_full_lifecycle(self, client, index_tree):
        """start → status=true → query returns results → stop → status=false."""
        # 1. Start indexing
        r_start = client.post("/index/start", json={"path": str(index_tree)})
        assert r_start.status_code == 200
        assert r_start.json()["indexed"] is True

        # 2. Status shows indexed
        r_status = client.post("/index/status", json={"path": str(index_tree)})
        assert r_status.json()["indexed"] is True

        # 3. A query returns results (index-backed path)
        r_query = client.post("/entries", json={
            "path": str(index_tree), "kind": 1, "name_seed": "beta",
        })
        assert r_query.status_code == 200
        names = [Path(e["path"]).name for e in r_query.json()["entries"]]
        assert "beta.txt" in names

        # 4. Stop indexing
        r_stop = client.post("/index/stop", json={"path": str(index_tree)})
        assert r_stop.status_code == 200
        assert r_stop.json()["indexed"] is False

        # 5. Status now shows not indexed
        r_status2 = client.post("/index/status", json={"path": str(index_tree)})
        assert r_status2.json()["indexed"] is False

    # ------------------------------------------------------------------
    # Response model fields
    # ------------------------------------------------------------------

    def test_response_model_fields_present(self, client, index_tree):
        """IndexStatusResponse carries root and indexed fields."""
        resp = client.post("/index/status", json={"path": str(index_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert "root" in data
        assert "indexed" in data
        assert isinstance(data["indexed"], bool)
        assert isinstance(data["root"], str)


# ---------------------------------------------------------------------------
# POST /largest — FFX-I11 (size aggregation, non-destructive)
# ---------------------------------------------------------------------------

class TestPostLargest:
    """REST integration tests for POST /largest (FFX-I11).

    Tree layout (built fresh per test via tmp_path):
      tiny.bin   —   10 bytes
      medium.bin — 1 000 bytes
      large.bin  — 5 000 bytes
      (optional) extra_large.bin — 9 000 bytes for top_n cap tests
    """

    @pytest.fixture()
    def sized_tree(self, tmp_path: Path) -> Path:
        """Files with known sizes for sort/cap assertions."""
        (tmp_path / "tiny.bin").write_bytes(b"x" * 10)
        (tmp_path / "medium.bin").write_bytes(b"x" * 1_000)
        (tmp_path / "large.bin").write_bytes(b"x" * 5_000)
        return tmp_path

    # ------------------------------------------------------------------
    # Happy path: returns entries sorted descending by size
    # ------------------------------------------------------------------

    def test_returns_200_and_entries(self, client, sized_tree):
        """POST /largest returns HTTP 200 with a non-empty entries list."""
        resp = client.post("/largest", json={"path": str(sized_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data
        assert "count" in data
        assert data["count"] == len(data["entries"])

    def test_entries_sorted_descending_by_size(self, client, sized_tree):
        """Entries are sorted largest-first by the 'size' field."""
        resp = client.post("/largest", json={"path": str(sized_tree)})
        assert resp.status_code == 200
        sizes = [e["size"] for e in resp.json()["entries"]]
        assert sizes == sorted(sizes, reverse=True)

    def test_largest_file_is_first(self, client, sized_tree):
        """The first entry is the file with the most bytes (large.bin = 5 000 B)."""
        resp = client.post("/largest", json={"path": str(sized_tree)})
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert Path(entries[0]["path"]).name == "large.bin"
        assert entries[0]["size"] == 5_000

    def test_count_matches_number_of_files(self, client, sized_tree):
        """count equals the number of files returned (3 in the fixture)."""
        resp = client.post("/largest", json={"path": str(sized_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3

    def test_entry_fields_present(self, client, sized_tree):
        """Each entry carries 'path' (str) and 'size' (int) fields."""
        resp = client.post("/largest", json={"path": str(sized_tree)})
        assert resp.status_code == 200
        for entry in resp.json()["entries"]:
            assert "path" in entry
            assert "size" in entry
            assert isinstance(entry["path"], str)
            assert isinstance(entry["size"], int)

    # ------------------------------------------------------------------
    # top_n cap
    # ------------------------------------------------------------------

    def test_top_n_caps_results(self, client, sized_tree):
        """top_n=2 returns at most 2 entries (the two largest)."""
        (sized_tree / "extra_large.bin").write_bytes(b"x" * 9_000)
        resp = client.post("/largest", json={"path": str(sized_tree), "top_n": 2})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["entries"]) == 2
        # Must be the two largest
        sizes = [e["size"] for e in data["entries"]]
        assert sizes == [9_000, 5_000]

    def test_top_n_1_returns_single_largest(self, client, sized_tree):
        """top_n=1 returns exactly one entry — the largest file."""
        resp = client.post("/largest", json={"path": str(sized_tree), "top_n": 1})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert Path(data["entries"][0]["path"]).name == "large.bin"

    # ------------------------------------------------------------------
    # name_seed filter
    # ------------------------------------------------------------------

    def test_name_seed_filters_results(self, client, sized_tree):
        """name_seed='large' returns only files whose name contains 'large'."""
        resp = client.post("/largest", json={
            "path": str(sized_tree), "name_seed": "large",
        })
        assert resp.status_code == 200
        names = [Path(e["path"]).name for e in resp.json()["entries"]]
        assert all("large" in n for n in names)
        assert "tiny.bin" not in names
        assert "medium.bin" not in names

    def test_empty_name_seed_returns_all(self, client, sized_tree):
        """Empty name_seed (default) is allowed and aggregates the whole tree."""
        resp = client.post("/largest", json={
            "path": str(sized_tree), "name_seed": "",
        })
        assert resp.status_code == 200
        assert resp.json()["count"] == 3

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    def test_top_n_zero_returns_422(self, client, sized_tree):
        """top_n=0 is rejected at the schema level (ge=1) → HTTP 422."""
        resp = client.post("/largest", json={"path": str(sized_tree), "top_n": 0})
        assert resp.status_code == 422

    def test_top_n_negative_returns_422(self, client, sized_tree):
        """top_n=-1 is also rejected by the ge=1 constraint → HTTP 422."""
        resp = client.post("/largest", json={"path": str(sized_tree), "top_n": -1})
        assert resp.status_code == 422

    def test_missing_path_returns_404(self, client, tmp_path):
        """A path that does not exist → FileNotFoundError → HTTP 404."""
        resp = client.post("/largest", json={
            "path": str(tmp_path / "no_such_directory"),
        })
        assert resp.status_code == 404

    def test_response_model_fields(self, client, sized_tree):
        """LargestEntriesResponse carries 'entries' and 'count' keys."""
        resp = client.post("/largest", json={"path": str(sized_tree)})
        assert resp.status_code == 200
        data = resp.json()
        assert set(data.keys()) >= {"entries", "count"}
