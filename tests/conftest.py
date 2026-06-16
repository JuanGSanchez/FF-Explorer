"""
Shared pytest fixtures for the FF-Explorer test suite.

All filesystem work uses tmp_path; no real user files are touched.
"""
from __future__ import annotations

import os
import sys

import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Qt / GUI fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """
    Session-scoped QApplication for offscreen GUI smoke tests.

    Uses PySide6 directly — no pytest-qt dependency required.
    Sets QT_QPA_PLATFORM=offscreen if not already set so the suite can run
    in headless CI without a display server.

    Yields the QApplication instance; keeps it alive for the entire session.
    """
    # Ensure offscreen platform when no display variable is set and the caller
    # hasn't already set the platform explicitly.
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from PySide6.QtWidgets import QApplication

    # QApplication must be a singleton; reuse if one already exists.
    existing = QApplication.instance()
    if existing is not None:
        yield existing
        return

    app = QApplication(sys.argv[:1])
    app.setApplicationName("FF Explorer Test")
    yield app
    # Do NOT call app.quit() or app.exec() — the fixture just provides the
    # instance; individual tests are responsible for showing/hiding windows.


# ---------------------------------------------------------------------------
# File-tree fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def simple_tree(tmp_path: Path) -> Path:
    """
    A minimal flat+nested tree for query tests:

        tmp_path/
            alpha.txt
            beta.log
            gamma.txt
            sub/
                delta.txt
                epsilon.log
            sub2/
                zeta.TXT        ← uppercase extension (case-sensitivity tests)
    """
    (tmp_path / "alpha.txt").write_text("a")
    (tmp_path / "beta.log").write_text("b")
    (tmp_path / "gamma.txt").write_text("g")

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "delta.txt").write_text("d")
    (sub / "epsilon.log").write_text("e")

    sub2 = tmp_path / "sub2"
    sub2.mkdir()
    (sub2 / "zeta.TXT").write_text("z")

    return tmp_path


@pytest.fixture()
def file_tree(tmp_path: Path) -> Path:
    """
    Tree for destructive-ops tests (remove/compress).

        tmp_path/
            keep_me.txt
            delete_me.txt
            delete_also.txt
            nested/
                nested_delete.txt
                nested_keep.txt
    """
    (tmp_path / "keep_me.txt").write_text("keep")
    (tmp_path / "delete_me.txt").write_text("del1")
    (tmp_path / "delete_also.txt").write_text("del2")

    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "nested_delete.txt").write_text("nd")
    (nested / "nested_keep.txt").write_text("nk")

    return tmp_path


@pytest.fixture()
def folder_tree(tmp_path: Path) -> Path:
    """
    Tree for FOLDERS-mode tests.

        tmp_path/
            archive_one/   (contains file_a.txt)
            archive_two/   (contains file_b.txt)
            other_dir/     (contains file_c.txt)
    """
    a1 = tmp_path / "archive_one"
    a1.mkdir()
    (a1 / "file_a.txt").write_text("a")

    a2 = tmp_path / "archive_two"
    a2.mkdir()
    (a2 / "file_b.txt").write_text("b")

    od = tmp_path / "other_dir"
    od.mkdir()
    (od / "file_c.txt").write_text("c")

    return tmp_path
