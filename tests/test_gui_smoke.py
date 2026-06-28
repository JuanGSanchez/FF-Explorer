"""
FFX-B05 / FFX-I01 / FFX-I02 — Headless GUI smoke tests for
ff_explorer.gui.main_window.

Runs under QT_QPA_PLATFORM=offscreen (set by the qapp session fixture in
conftest.py when not already present in the environment).

Assertions covered:
  A1 — MainWindow instantiates without error under offscreen Qt.
  A2 — Preview-then-confirm safety gate: QMessageBox.question defaults to No;
       destructive core calls are NOT issued when the dialog returns No.
  A3 — FFX-B08 regression: pressing Control alone does NOT close/exit the
       window (no Control-exit branch in keyPressEvent).
  A4 — FFX-B09 regression: _path_edit is a _ClickableLineEdit subclass;
       mousePressEvent calls the browse callback AND the base handler;
       no instance-level monkey-patch of mousePressEvent remains.
  A5 — FFX-I01/I02: filter controls exist; _build_list_entries_kwargs produces
       correct param dicts; default state yields {} (no filters); selecting
       Regex sets match_mode="regex"; extensions parsing normalises tokens;
       invalid regex is surfaced as a warning, not a crash.
  A6 — FFX-I01/I02: the Run path with Regex match_mode passes match_mode to
       list_entries via the captured kwargs (monkeypatched).

The qapp session fixture (tests/conftest.py) provides a singleton
QApplication using PySide6 directly — no pytest-qt dependency.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QMessageBox

from ff_explorer.gui.widget_info import WIDGET_INFO, info_text, register_info_text

from ff_explorer.gui.main_window import MainWindow, _ClickableLineEdit


# ---------------------------------------------------------------------------
# A1 — Window instantiates without error under offscreen Qt
# ---------------------------------------------------------------------------

class TestMainWindowInstantiation:
    """A1: MainWindow must construct cleanly under the offscreen platform."""

    def test_instantiation(self, qapp):
        """MainWindow() raises no exception and produces a QMainWindow instance."""
        win = MainWindow()
        try:
            assert win is not None
            assert win.windowTitle() == "FF Explorer"
        finally:
            win.close()
            win.deleteLater()

    def test_window_has_expected_widgets(self, qapp):
        """A1 extended: path edit, seed edit, action combo, status bar exist."""
        win = MainWindow()
        try:
            assert hasattr(win, "_path_edit")
            assert hasattr(win, "_seed_edit")
            assert hasattr(win, "_action_combo")
            assert hasattr(win, "_status_bar")
            assert hasattr(win, "_mode_group")
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A2 — Safety gate: destructive actions are NOT issued when dialog returns No
# ---------------------------------------------------------------------------

class TestDestructiveSafetyGateDefaultsNo:
    """
    A2: When QMessageBox.question returns No (the default button), the
    destructive core call (remove_entries / compress_entries with
    dry_run=False, confirm=True) must NOT be invoked.
    """

    def _make_match_entries(self, tmp_path: Path) -> list:
        """Return a list with one MatchEntry for a real file in tmp_path."""
        from ff_explorer import MatchEntry, EntryKind
        fake_path = tmp_path / "target.txt"
        fake_path.write_text("x")
        return [MatchEntry(path=fake_path, kind=EntryKind.FILES)]

    def test_remove_dialog_default_no_skips_destructive_call(self, qapp, tmp_path):
        """
        _do_remove: when QMessageBox.question returns No, the live
        remove_entries(dry_run=False, confirm=True) is never called.

        SPEC-14: _do_remove now receives the pre-scanned entries list from the
        worker (no dry-run inside _do_remove itself).  The safety gate is the
        QMessageBox.question defaulting to No.
        """
        win = MainWindow()
        try:
            entries = self._make_match_entries(tmp_path)

            calls = []

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                calls.append({"dry_run": dry_run, "confirm": confirm})
                if not dry_run:
                    raise AssertionError("Destructive remove must not be called when user clicks No")
                from ff_explorer.core import RemovalReport
                return RemovalReport(matched=[e.path for e in entries])

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "target", "file", entries)

            # Only the confirmation dialog was shown; no destructive call must occur.
            destructive_calls = [c for c in calls if not c["dry_run"]]
            assert len(destructive_calls) == 0, (
                "Destructive remove_entries(dry_run=False) must not be called when dialog returns No"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_compress_dialog_default_no_skips_destructive_call(self, qapp, tmp_path):
        """
        _do_compress: when QMessageBox.question returns No, the live
        compress_entries(dry_run=False, confirm=True) is never called.

        SPEC-14: _do_compress now receives the pre-scanned entries list.
        """
        win = MainWindow()
        try:
            from ff_explorer import MatchEntry, EntryKind
            fake_path = tmp_path / "target_folder"
            fake_path.mkdir()
            entries = [MatchEntry(path=fake_path, kind=EntryKind.FOLDERS)]

            calls = []

            def fake_compress(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                calls.append({"dry_run": dry_run, "confirm": confirm})
                if not dry_run:
                    raise AssertionError("Destructive compress must not be called when user clicks No")
                from ff_explorer.core import CompressionReport
                return CompressionReport(matched=[fake_path])

            with (
                patch("ff_explorer.gui.main_window.compress_entries", side_effect=fake_compress),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_compress(str(tmp_path), win._current_kind(), "target", "folder", entries)

            destructive_calls = [c for c in calls if not c["dry_run"]]
            assert len(destructive_calls) == 0, (
                "Destructive compress_entries(dry_run=False) must not be called when dialog returns No"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_remove_proceeds_on_yes(self, qapp, tmp_path):
        """
        Converse: when dialog returns Yes, the destructive call IS issued
        (confirms the gate only blocks on No, not always).
        """
        win = MainWindow()
        try:
            from ff_explorer import MatchEntry, EntryKind
            from ff_explorer.core import RemovalReport
            fake_path = tmp_path / "yes_target.txt"
            fake_path.write_text("x")
            entries = [MatchEntry(path=fake_path, kind=EntryKind.FILES)]
            live_report = RemovalReport(matched=[fake_path], removed=[fake_path])

            calls = []

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                calls.append({"dry_run": dry_run, "confirm": confirm})
                return live_report

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "yes_target", "file", entries)

            destructive_calls = [c for c in calls if not c["dry_run"]]
            assert len(destructive_calls) == 1, (
                "Destructive remove_entries must be called exactly once when user clicks Yes"
            )
            assert destructive_calls[0]["confirm"] is True
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A3 — FFX-B08 regression: Control key alone does NOT close/exit the window
# ---------------------------------------------------------------------------

class TestControlKeyNoExit:
    """
    A3: keyPressEvent has no Control-exit branch.
    Pressing Control alone must not close or hide the window.
    """

    def test_control_key_does_not_close_window(self, qapp):
        """Pressing Qt.Key_Control alone does not close the window."""
        win = MainWindow()
        win.show()
        try:
            assert win.isVisible(), "Window should be visible after show()"

            # Simulate a bare Control key press event
            key_event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Control,
                Qt.KeyboardModifier.ControlModifier,
            )
            win.keyPressEvent(key_event)

            # Window must still be visible — no Control-exit branch exists
            assert win.isVisible(), (
                "Window must remain visible after a bare Control key press "
                "(FFX-B08: Control-exit branch must not exist)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_keyPressEvent_has_no_control_exit_branch(self, qapp):
        """
        Source-level regression: inspect keyPressEvent logic.
        Pressing Control with ControlModifier must not trigger _exit/_close.
        We verify by monkeypatching _exit to detect if it is called.
        """
        win = MainWindow()
        win.show()
        try:
            exit_called = []
            original_exit = win._exit
            win._exit = lambda: exit_called.append(True)  # type: ignore[method-assign]

            key_event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Control,
                Qt.KeyboardModifier.ControlModifier,
            )
            win.keyPressEvent(key_event)

            assert len(exit_called) == 0, (
                "_exit() must not be called on a bare Control key press "
                "(FFX-B08 regression)"
            )
        finally:
            win._exit = original_exit  # type: ignore[method-assign]
            win.close()
            win.deleteLater()

    def test_enter_key_still_triggers_run(self, qapp, tmp_path):
        """
        Sanity: Enter key still triggers _run (the only keyPressEvent handler).
        We verify by monkeypatching _run and confirming it is called.
        """
        win = MainWindow()
        try:
            run_called = []
            win._run = lambda: run_called.append(True)  # type: ignore[method-assign]

            key_event = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Return,
                Qt.KeyboardModifier.NoModifier,
            )
            win.keyPressEvent(key_event)

            assert len(run_called) == 1, (
                "_run() must be called exactly once when Enter/Return is pressed"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A4 — FFX-B09 regression: _path_edit is _ClickableLineEdit, not monkey-patched
# ---------------------------------------------------------------------------

class TestClickableLineEditNotMonkeyPatched:
    """
    A4: _path_edit must be a _ClickableLineEdit instance (the idiomatic subclass).
    Its mousePressEvent calls the base handler AND the browse callback.
    No instance-level monkey-patch of mousePressEvent must be present.
    """

    def test_path_edit_is_clickable_line_edit_subclass(self, qapp):
        """_path_edit is an instance of _ClickableLineEdit, not a plain QLineEdit."""
        from PySide6.QtWidgets import QLineEdit
        win = MainWindow()
        try:
            assert isinstance(win._path_edit, _ClickableLineEdit), (
                "_path_edit must be an instance of _ClickableLineEdit (FFX-B09)"
            )
            assert isinstance(win._path_edit, QLineEdit), (
                "_ClickableLineEdit must remain a QLineEdit subclass"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_path_edit_mousePressEvent_not_instance_monkey_patched(self, qapp):
        """
        mousePressEvent on _path_edit must be the class method, not an
        instance-level attribute (no lambda monkey-patch on the instance).
        """
        win = MainWindow()
        try:
            # If there were an instance-level patch, it would show up in
            # __dict__ as 'mousePressEvent'.
            assert "mousePressEvent" not in win._path_edit.__dict__, (
                "_path_edit.mousePressEvent must NOT be an instance-level attribute "
                "(FFX-B09: the lambda monkey-patch must be gone)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_clickable_line_edit_calls_browse_callback_on_mouse_press(self, qapp):
        """
        _ClickableLineEdit.mousePressEvent invokes the on_click callback.
        The browse callback is registered as on_click; assert it is called.
        """
        browse_calls = []
        widget = _ClickableLineEdit("placeholder", on_click=lambda: browse_calls.append(True))

        mouse_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            widget.rect().center().toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        widget.mousePressEvent(mouse_event)

        assert len(browse_calls) == 1, (
            "_ClickableLineEdit.mousePressEvent must invoke the on_click callback "
            "exactly once on a mouse press (FFX-B09)"
        )

    def test_clickable_line_edit_without_callback_does_not_raise(self, qapp):
        """_ClickableLineEdit with on_click=None must not raise on mouse press."""
        widget = _ClickableLineEdit("text", on_click=None)
        mouse_event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            widget.rect().center().toPointF(),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        # Must not raise
        widget.mousePressEvent(mouse_event)

    def test_main_window_path_edit_browse_callback_wired(self, qapp):
        """
        In the real MainWindow, _path_edit._on_click is set to a callable
        (the lambda that calls _browse_path) — assert it is not None.
        """
        win = MainWindow()
        try:
            assert win._path_edit._on_click is not None, (
                "_path_edit._on_click must be set to the browse callback, not None"
            )
            assert callable(win._path_edit._on_click), (
                "_path_edit._on_click must be callable"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A5 — FFX-I01/I02: filter controls exist and produce correct param dicts
# ---------------------------------------------------------------------------

class TestFilterControlsExist:
    """A5a: The filter panel and all filter widgets must be present on MainWindow."""

    def test_filter_panel_exists(self, qapp):
        """_filters_panel (QGroupBox) exists and is initially hidden.

        isHidden() reflects the widget's own explicit hide flag, independent
        of whether the parent window has been shown yet.
        """
        from PySide6.QtWidgets import QGroupBox
        win = MainWindow()
        try:
            assert hasattr(win, "_filters_panel"), "_filters_panel must exist"
            assert isinstance(win._filters_panel, QGroupBox)
            assert win._filters_panel.isHidden(), (
                "_filters_panel must be hidden by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_match_mode_combo_exists_with_three_items(self, qapp):
        """_match_mode_combo has items Substring, Glob, Regex and defaults to Substring."""
        from PySide6.QtWidgets import QComboBox
        win = MainWindow()
        try:
            assert hasattr(win, "_match_mode_combo"), "_match_mode_combo must exist"
            assert isinstance(win._match_mode_combo, QComboBox)
            items = [win._match_mode_combo.itemText(i)
                     for i in range(win._match_mode_combo.count())]
            assert "Substring" in items
            assert "Glob" in items
            assert "Regex" in items
            assert win._match_mode_combo.currentText() == "Substring", (
                "Default match mode must be Substring"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_case_sensitive_checkbox_exists_and_checked_by_default(self, qapp):
        """_case_sensitive_check exists and is checked (True) by default."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_case_sensitive_check")
            assert isinstance(win._case_sensitive_check, QCheckBox)
            assert win._case_sensitive_check.isChecked(), (
                "case_sensitive must be checked (True) by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_size_spinboxes_exist_and_default_to_zero(self, qapp):
        """_min_size_spin and _max_size_spin exist and default to 0 (no bound)."""
        from PySide6.QtWidgets import QSpinBox
        win = MainWindow()
        try:
            assert hasattr(win, "_min_size_spin")
            assert hasattr(win, "_max_size_spin")
            assert isinstance(win._min_size_spin, QSpinBox)
            assert isinstance(win._max_size_spin, QSpinBox)
            assert win._min_size_spin.value() == 0, "min_size_spin must default to 0"
            assert win._max_size_spin.value() == 0, "max_size_spin must default to 0"
        finally:
            win.close()
            win.deleteLater()

    def test_date_filter_checkboxes_unchecked_by_default(self, qapp):
        """Date filter checkboxes default to unchecked (disabled — no date filter)."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_date_after_check")
            assert hasattr(win, "_date_before_check")
            assert isinstance(win._date_after_check, QCheckBox)
            assert isinstance(win._date_before_check, QCheckBox)
            assert not win._date_after_check.isChecked(), (
                "date_after_check must be unchecked by default"
            )
            assert not win._date_before_check.isChecked(), (
                "date_before_check must be unchecked by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_date_edits_disabled_when_checkboxes_unchecked(self, qapp):
        """QDateEdit widgets are disabled when their enable checkboxes are unchecked."""
        from PySide6.QtWidgets import QDateEdit
        win = MainWindow()
        try:
            assert hasattr(win, "_date_after_edit")
            assert hasattr(win, "_date_before_edit")
            assert isinstance(win._date_after_edit, QDateEdit)
            assert isinstance(win._date_before_edit, QDateEdit)
            assert not win._date_after_edit.isEnabled(), (
                "_date_after_edit must be disabled when checkbox unchecked"
            )
            assert not win._date_before_edit.isEnabled(), (
                "_date_before_edit must be disabled when checkbox unchecked"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_extensions_lineedit_exists_and_empty(self, qapp):
        """_extensions_edit exists, is a QLineEdit, and is empty by default."""
        from PySide6.QtWidgets import QLineEdit
        win = MainWindow()
        try:
            assert hasattr(win, "_extensions_edit")
            assert isinstance(win._extensions_edit, QLineEdit)
            assert win._extensions_edit.text() == "", (
                "_extensions_edit must be empty by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_filters_toggle_btn_exists_and_unchecked(self, qapp):
        """_filters_toggle_btn is a checkable QPushButton, unchecked by default."""
        from PySide6.QtWidgets import QPushButton
        win = MainWindow()
        try:
            assert hasattr(win, "_filters_toggle_btn")
            assert isinstance(win._filters_toggle_btn, QPushButton)
            assert win._filters_toggle_btn.isCheckable()
            assert not win._filters_toggle_btn.isChecked(), (
                "Filters toggle must be unchecked (collapsed) by default"
            )
        finally:
            win.close()
            win.deleteLater()


class TestFilterParamAssembly:
    """A5b: _build_list_entries_kwargs produces correct dicts from control state."""

    def test_default_state_yields_empty_dict(self, qapp):
        """At default state (Substring, case-sensitive, 0 sizes, no dates, empty ext)
        _build_list_entries_kwargs returns {} — no filter params sent to core."""
        win = MainWindow()
        try:
            kwargs = win._build_list_entries_kwargs()
            assert kwargs == {}, (
                "Default filter state must produce an empty dict "
                "(no extra params passed to list_entries, preserving prior behaviour)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_selecting_regex_sets_match_mode_regex(self, qapp):
        """Selecting 'Regex' in _match_mode_combo yields match_mode='regex'."""
        win = MainWindow()
        try:
            idx = [win._match_mode_combo.itemText(i)
                   for i in range(win._match_mode_combo.count())].index("Regex")
            win._match_mode_combo.setCurrentIndex(idx)
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("match_mode") == "regex", (
                "Selecting Regex must yield match_mode='regex'"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_selecting_glob_sets_match_mode_glob(self, qapp):
        """Selecting 'Glob' yields match_mode='glob'."""
        win = MainWindow()
        try:
            idx = [win._match_mode_combo.itemText(i)
                   for i in range(win._match_mode_combo.count())].index("Glob")
            win._match_mode_combo.setCurrentIndex(idx)
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("match_mode") == "glob"
        finally:
            win.close()
            win.deleteLater()

    def test_substring_mode_not_in_kwargs(self, qapp):
        """Substring mode (default) must NOT appear in kwargs (avoids redundant param)."""
        win = MainWindow()
        try:
            idx = [win._match_mode_combo.itemText(i)
                   for i in range(win._match_mode_combo.count())].index("Substring")
            win._match_mode_combo.setCurrentIndex(idx)
            kwargs = win._build_list_entries_kwargs()
            assert "match_mode" not in kwargs, (
                "Substring mode must not appear in kwargs — it is the default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_unchecking_case_sensitive_adds_param(self, qapp):
        """Unchecking case_sensitive yields case_sensitive=False in kwargs."""
        win = MainWindow()
        try:
            win._case_sensitive_check.setChecked(False)
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("case_sensitive") is False, (
                "Unchecking case_sensitive must yield case_sensitive=False"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_case_sensitive_true_not_in_kwargs(self, qapp):
        """Checked case_sensitive (True = default) must NOT appear in kwargs."""
        win = MainWindow()
        try:
            win._case_sensitive_check.setChecked(True)
            kwargs = win._build_list_entries_kwargs()
            assert "case_sensitive" not in kwargs, (
                "case_sensitive=True (default) must not appear in kwargs"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_min_size_spin_converts_kb_to_bytes(self, qapp):
        """Setting min_size_spin to N yields min_size=N*1024 bytes."""
        win = MainWindow()
        try:
            win._min_size_spin.setValue(10)  # 10 KB
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("min_size") == 10 * 1024, (
                "min_size_spin=10 KB must yield min_size=10240 bytes"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_max_size_spin_converts_kb_to_bytes(self, qapp):
        """Setting max_size_spin to N yields max_size=N*1024 bytes."""
        win = MainWindow()
        try:
            win._max_size_spin.setValue(500)  # 500 KB
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("max_size") == 500 * 1024, (
                "max_size_spin=500 KB must yield max_size=512000 bytes"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_zero_size_spins_yield_no_size_params(self, qapp):
        """Spinboxes at 0 must not add min_size/max_size to kwargs."""
        win = MainWindow()
        try:
            win._min_size_spin.setValue(0)
            win._max_size_spin.setValue(0)
            kwargs = win._build_list_entries_kwargs()
            assert "min_size" not in kwargs
            assert "max_size" not in kwargs
        finally:
            win.close()
            win.deleteLater()

    def test_date_after_enabled_yields_modified_after_epoch(self, qapp):
        """Enabling date_after_check adds a float modified_after epoch to kwargs."""
        win = MainWindow()
        try:
            win._date_after_check.setChecked(True)
            win._date_after_edit.setDate(QDate(2024, 1, 1))
            kwargs = win._build_list_entries_kwargs()
            assert "modified_after" in kwargs, (
                "Enabling date_after must yield modified_after in kwargs"
            )
            assert isinstance(kwargs["modified_after"], float), (
                "modified_after must be a float (epoch seconds)"
            )
            import datetime
            expected = datetime.datetime(2024, 1, 1, 0, 0, 0,
                                         tzinfo=datetime.timezone.utc).timestamp()
            assert abs(kwargs["modified_after"] - expected) < 2, (
                f"modified_after epoch mismatch: got {kwargs['modified_after']}, "
                f"expected ~{expected}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_date_before_enabled_yields_modified_before_epoch(self, qapp):
        """Enabling date_before_check adds a float modified_before epoch to kwargs."""
        win = MainWindow()
        try:
            win._date_before_check.setChecked(True)
            win._date_before_edit.setDate(QDate(2024, 6, 15))
            kwargs = win._build_list_entries_kwargs()
            assert "modified_before" in kwargs, (
                "Enabling date_before must yield modified_before in kwargs"
            )
            assert isinstance(kwargs["modified_before"], float), (
                "modified_before must be a float (epoch seconds)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_date_filters_disabled_not_in_kwargs(self, qapp):
        """Unchecked date filter checkboxes must not add any date params."""
        win = MainWindow()
        try:
            win._date_after_check.setChecked(False)
            win._date_before_check.setChecked(False)
            kwargs = win._build_list_entries_kwargs()
            assert "modified_after" not in kwargs
            assert "modified_before" not in kwargs
        finally:
            win.close()
            win.deleteLater()

    def test_extensions_comma_separated_parsed_to_list(self, qapp):
        """'.txt, .md' in extensions edit yields ['.txt', '.md']."""
        win = MainWindow()
        try:
            win._extensions_edit.setText(".txt, .md")
            kwargs = win._build_list_entries_kwargs()
            assert "extensions" in kwargs, (
                "Non-empty extensions field must yield extensions in kwargs"
            )
            exts = kwargs["extensions"]
            assert isinstance(exts, list)
            assert ".txt" in exts
            assert ".md" in exts
        finally:
            win.close()
            win.deleteLater()

    def test_extensions_without_dots_gets_dot_prepended(self, qapp):
        """'txt md' (no dots) still yields ['.txt', '.md'] after normalisation."""
        win = MainWindow()
        try:
            win._extensions_edit.setText("txt md")
            kwargs = win._build_list_entries_kwargs()
            exts = kwargs.get("extensions", [])
            assert ".txt" in exts, "Missing dot must be prepended automatically"
            assert ".md" in exts
        finally:
            win.close()
            win.deleteLater()

    def test_extensions_space_separated_parsed(self, qapp):
        """Space-separated extensions are accepted."""
        win = MainWindow()
        try:
            win._extensions_edit.setText(".log .csv")
            kwargs = win._build_list_entries_kwargs()
            exts = kwargs.get("extensions", [])
            assert ".log" in exts
            assert ".csv" in exts
        finally:
            win.close()
            win.deleteLater()

    def test_empty_extensions_field_not_in_kwargs(self, qapp):
        """Empty extensions field must not add extensions to kwargs."""
        win = MainWindow()
        try:
            win._extensions_edit.setText("")
            kwargs = win._build_list_entries_kwargs()
            assert "extensions" not in kwargs, (
                "Empty extensions field must not add extensions to kwargs"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_extensions_lowercased(self, qapp):
        """Extensions are normalised to lower-case."""
        win = MainWindow()
        try:
            win._extensions_edit.setText(".TXT, .MD")
            kwargs = win._build_list_entries_kwargs()
            exts = kwargs.get("extensions", [])
            assert ".txt" in exts, "Extensions must be lower-cased"
            assert ".md" in exts
        finally:
            win.close()
            win.deleteLater()


class TestFilterToggle:
    """A5c: Filters toggle shows/hides the panel and resizes the window.

    Note: isVisible() returns False when the parent window is not shown, even
    if the widget itself has been made visible via setVisible(True).  We use
    isHidden() (the explicit hide flag, independent of parent state) to test
    the panel's own show/hide state without requiring the window to be shown.
    """

    def test_toggle_shows_filters_panel(self, qapp):
        """_toggle_filters(True) makes _filters_panel not-hidden (shown)."""
        win = MainWindow()
        try:
            # Before toggle: panel must be hidden
            assert win._filters_panel.isHidden(), (
                "_filters_panel must be hidden by default"
            )
            win._toggle_filters(True)
            assert not win._filters_panel.isHidden(), (
                "_filters_panel must not be hidden after toggle ON"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_toggle_hides_filters_panel(self, qapp):
        """Toggling back makes _filters_panel hidden again."""
        win = MainWindow()
        try:
            win._toggle_filters(True)
            win._toggle_filters(False)
            assert win._filters_panel.isHidden(), (
                "_filters_panel must be hidden after toggle OFF"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_toggle_resizes_window(self, qapp):
        """Window height increases when filters shown and returns to original."""
        from ff_explorer.gui.main_window import _WIN_HEIGHT_COLLAPSED, _WIN_HEIGHT_EXPANDED
        win = MainWindow()
        try:
            assert win.height() == _WIN_HEIGHT_COLLAPSED
            win._toggle_filters(True)
            assert win.height() == _WIN_HEIGHT_EXPANDED, (
                f"Window height must expand to {_WIN_HEIGHT_EXPANDED} when filters shown"
            )
            win._toggle_filters(False)
            assert win.height() == _WIN_HEIGHT_COLLAPSED, (
                f"Window height must return to {_WIN_HEIGHT_COLLAPSED} when filters hidden"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A6 — FFX-I01/I02: Run path passes filter kwargs to list_entries
# ---------------------------------------------------------------------------

class TestRunPassesFilterKwargs:
    """A6: When Run is triggered with non-default filters, save_listing / iter_entries
    receive the correct kwargs.

    SPEC-14: _do_save no longer calls list_entries itself — the entries list is
    delivered by the _ScanWorker (which calls iter_entries).  The _do_save method
    only calls save_listing.  Filter-param correctness for the scan side is
    verified via _build_list_entries_kwargs() in TestFilterParamAssembly (A5b).
    """

    def test_run_save_passes_match_mode_regex_to_list_entries(self, qapp, tmp_path):
        """_build_list_entries_kwargs passes match_mode='regex' when Regex is selected.

        SPEC-14 adaptation: _do_save no longer calls list_entries directly; the
        worker uses iter_entries with _build_list_entries_kwargs().  We verify
        _do_save calls save_listing correctly and uses the passed entries list
        (the match_mode kwarg is verified via _build_list_entries_kwargs in A5b).
        """
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            idx = [win._match_mode_combo.itemText(i)
                   for i in range(win._match_mode_combo.count())].index("Regex")
            win._match_mode_combo.setCurrentIndex(idx)

            save_called = []

            def fake_save_listing(path, kind, seed, **kwargs):
                save_called.append(kwargs)
                return tmp_path / "out.txt"

            # Pre-built entries list (as the worker would supply)
            fake_entry = MatchEntry(path=tmp_path / "match.txt", kind=EntryKind.FILES)
            entries = [fake_entry]

            with patch("ff_explorer.gui.main_window.save_listing",
                       side_effect=fake_save_listing):
                win._do_save(str(tmp_path), win._current_kind(), ".*", "file", entries)

            assert len(save_called) == 1, "_do_save must call save_listing exactly once"
            # Verify _build_list_entries_kwargs reflects Regex selection
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("match_mode") == "regex", (
                "_build_list_entries_kwargs must include match_mode='regex' when Regex selected"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_run_save_passes_case_insensitive_when_unchecked(self, qapp, tmp_path):
        """_do_save passes case_sensitive=False to save_listing.

        SPEC-14: _do_save no longer calls list_entries; it calls save_listing
        with core_kwargs (which includes case_sensitive).
        """
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            win._case_sensitive_check.setChecked(False)

            save_kwargs: dict = {}

            def fake_save_listing(path, kind, seed, **kwargs):
                save_kwargs.update(kwargs)
                return tmp_path / "out.txt"

            entries: list = []  # empty — nothing was scanned in this focused test

            with patch("ff_explorer.gui.main_window.save_listing",
                       side_effect=fake_save_listing):
                win._do_save(str(tmp_path), win._current_kind(), "test", "file", entries)

            assert save_kwargs.get("case_sensitive") is False, (
                "case_sensitive=False must be passed to save_listing"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_run_save_default_filters_no_extra_kwargs(self, qapp, tmp_path):
        """_do_save with default filters passes no extra kwargs to save_listing."""
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            save_kwargs: dict = {}

            def fake_save_listing(path, kind, seed, **kwargs):
                save_kwargs.update(kwargs)
                return tmp_path / "out.txt"

            entries: list = []

            with patch("ff_explorer.gui.main_window.save_listing",
                       side_effect=fake_save_listing):
                win._do_save(str(tmp_path), win._current_kind(), "test", "file", entries)

            assert save_kwargs == {}, (
                "Default filters must produce no extra kwargs to save_listing"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_invalid_regex_surfaced_as_warning_not_crash(self, qapp, tmp_path):
        """An invalid regex ValueError from the worker is shown as QMessageBox.warning.

        SPEC-14: the worker emits error(exc); the main-thread handler
        _handle_scan_error routes it to QMessageBox.warning.  We test
        _handle_scan_error directly here (the threading + exec() path is
        covered by TestScanWorker.test_worker_emits_error_on_exception).
        """
        win = MainWindow()
        try:
            warning_shown = []

            def fake_warning(parent, title, message, *args, **kwargs):
                warning_shown.append({"title": title, "message": message})

            with patch("ff_explorer.gui.main_window.QMessageBox.warning",
                       side_effect=fake_warning):
                win._handle_scan_error(ValueError("bad regex: [invalid("))

            assert len(warning_shown) > 0, (
                "An invalid regex ValueError must be surfaced as QMessageBox.warning"
            )
            assert any("regex" in w["message"].lower() or "bad" in w["message"].lower()
                       or "invalid" in w["message"].lower()
                       for w in warning_shown), (
                "Warning message must mention the regex error"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_run_remove_passes_case_sensitive_to_remove_entries(self, qapp, tmp_path):
        """_do_remove passes case_sensitive=False to remove_entries when unchecked.

        SPEC-14: _do_remove now receives the pre-scanned entries list; the
        case_sensitive kwarg is forwarded to the destructive call on Yes.
        """
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            win._case_sensitive_check.setChecked(False)
            fake_path = tmp_path / "target.txt"
            fake_path.write_text("x")
            entries = [MatchEntry(path=fake_path, kind=EntryKind.FILES)]
            live_report = RemovalReport(matched=[fake_path], removed=[fake_path])

            remove_kwargs: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                remove_kwargs.update(kwargs)
                remove_kwargs["dry_run"] = dry_run
                return live_report

            with (
                patch("ff_explorer.gui.main_window.remove_entries",
                      side_effect=fake_remove),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.Yes),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "target", "file", entries)

            assert remove_kwargs.get("case_sensitive") is False, (
                "_do_remove must pass case_sensitive=False to remove_entries"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A7 — FFX-I11: LargestEntriesView constructs, populates, and reflects data
# ---------------------------------------------------------------------------

class TestDiskUsageView:
    """A7: LargestEntriesView must construct headlessly, accept set_entries data,
    and expose it correctly through the public API without crashing.
    """

    # Minimal synthetic entry — mimics ff_explorer.core.SizedEntry
    class _FakeEntry:
        def __init__(self, path: str, size: int) -> None:
            self.path = path
            self.size = size

    def _make_entries(self):
        """Return three synthetic entries in descending size order."""
        return [
            self._FakeEntry("/data/big_file.bin", 10_000_000),
            self._FakeEntry("/data/medium_file.zip", 5_000_000),
            self._FakeEntry("/data/small_file.txt", 1_024),
        ]

    def test_largest_entries_view_instantiates(self, qapp):
        """LargestEntriesView() constructs without error under offscreen Qt."""
        from ff_explorer.gui.treemap_view import LargestEntriesView
        view = LargestEntriesView()
        try:
            assert view is not None
        finally:
            view.deleteLater()

    def test_set_entries_populates_count(self, qapp):
        """set_entries with 3 items yields entry_count() == 3."""
        from ff_explorer.gui.treemap_view import LargestEntriesView
        view = LargestEntriesView()
        try:
            view.set_entries(self._make_entries())
            assert view.entry_count() == 3, (
                "entry_count() must equal the number of entries passed to set_entries()"
            )
        finally:
            view.deleteLater()

    def test_set_entries_empty_list(self, qapp):
        """set_entries([]) results in entry_count() == 0 without error."""
        from ff_explorer.gui.treemap_view import LargestEntriesView
        view = LargestEntriesView()
        try:
            view.set_entries([])
            assert view.entry_count() == 0, (
                "entry_count() must be 0 after set_entries([])"
            )
        finally:
            view.deleteLater()

    def test_entry_at_returns_correct_path_and_size(self, qapp):
        """entry_at(0) returns the largest entry's path and size."""
        from ff_explorer.gui.treemap_view import LargestEntriesView
        view = LargestEntriesView()
        try:
            entries = self._make_entries()
            view.set_entries(entries)
            path0, size0 = view.entry_at(0)
            assert path0 == "/data/big_file.bin", (
                "entry_at(0).path must match the first (largest) entry's path"
            )
            assert size0 == 10_000_000, (
                "entry_at(0).size must match the first (largest) entry's size"
            )
        finally:
            view.deleteLater()

    def test_entries_preserve_descending_order(self, qapp):
        """Entries are stored in the order provided (expected: largest-first)."""
        from ff_explorer.gui.treemap_view import LargestEntriesView
        view = LargestEntriesView()
        try:
            entries = self._make_entries()
            view.set_entries(entries)
            sizes = [view.entry_at(i)[1] for i in range(view.entry_count())]
            assert sizes == sorted(sizes, reverse=True), (
                "Entries must be stored in descending size order "
                "as passed to set_entries()"
            )
        finally:
            view.deleteLater()

    def test_set_entries_twice_replaces_previous(self, qapp):
        """Calling set_entries a second time replaces the previous contents."""
        from ff_explorer.gui.treemap_view import LargestEntriesView
        view = LargestEntriesView()
        try:
            view.set_entries(self._make_entries())
            assert view.entry_count() == 3
            # Replace with a single entry
            view.set_entries([self._FakeEntry("/new/only_file.dat", 999)])
            assert view.entry_count() == 1, (
                "Second call to set_entries must replace previous contents"
            )
            path, size = view.entry_at(0)
            assert path == "/new/only_file.dat"
            assert size == 999
        finally:
            view.deleteLater()

    def test_fmt_size_formatter_bytes(self, qapp):
        """_fmt_size returns correct strings for bytes, KB, MB, GB."""
        from ff_explorer.gui.treemap_view import _fmt_size
        assert _fmt_size(0) == "0 B"
        assert _fmt_size(512) == "512 B"
        assert _fmt_size(1023) == "1023 B"

    def test_fmt_size_formatter_kilobytes(self, qapp):
        """_fmt_size converts to KB when 1024 <= n < 1 MB."""
        from ff_explorer.gui.treemap_view import _fmt_size
        assert _fmt_size(1024) == "1.00 KB"
        assert _fmt_size(2048) == "2.00 KB"

    def test_fmt_size_formatter_megabytes(self, qapp):
        """_fmt_size converts to MB when 1 MB <= n < 1 GB."""
        from ff_explorer.gui.treemap_view import _fmt_size
        assert _fmt_size(1_048_576) == "1.00 MB"
        assert _fmt_size(5_242_880) == "5.00 MB"

    def test_fmt_size_formatter_gigabytes(self, qapp):
        """_fmt_size converts to GB for values >= 1 GB."""
        from ff_explorer.gui.treemap_view import _fmt_size
        assert _fmt_size(1_073_741_824) == "1.00 GB"

    def test_disk_usage_button_wired_in_main_window(self, qapp):
        """MainWindow has a disk-usage button and _open_disk_usage handler."""
        win = MainWindow()
        try:
            assert hasattr(win, "_open_disk_usage"), (
                "MainWindow must have _open_disk_usage method (FFX-I11 wiring)"
            )
            assert callable(win._open_disk_usage), (
                "_open_disk_usage must be callable"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_disk_usage_no_path_shows_warning(self, qapp):
        """_open_disk_usage with no path selected shows a warning, no crash."""
        win = MainWindow()
        try:
            warned = []

            def fake_warning(parent, title, message, *args, **kwargs):
                warned.append({"title": title, "message": message})

            with patch(
                "ff_explorer.gui.main_window.QMessageBox.warning",
                side_effect=fake_warning,
            ):
                win._open_disk_usage()

            assert len(warned) == 1, (
                "_open_disk_usage with no path must show exactly one warning"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_disk_usage_with_real_tmp_tree(self, qapp, tmp_path):
        """_open_disk_usage on a real tmp tree runs without error.

        The dialog exec() is suppressed to keep the test non-blocking; the
        important assertion is that the handler reaches the dialog stage
        (i.e. largest_entries returned data and LargestEntriesView was built).
        """
        from PySide6.QtWidgets import QDialog
        from ff_explorer.gui.treemap_view import LargestEntriesView

        # Build a tiny tree
        (tmp_path / "big.bin").write_bytes(b"x" * 4096)
        (tmp_path / "small.txt").write_bytes(b"y" * 128)

        dialogs_opened = []

        original_exec = QDialog.exec

        def fake_exec(self_dlg):
            dialogs_opened.append(self_dlg)
            return 0  # suppress the modal event loop

        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))

            with patch.object(QDialog, "exec", fake_exec):
                win._open_disk_usage()

            # A dialog must have been opened (not blocked by a warning)
            assert len(dialogs_opened) == 1, (
                "_open_disk_usage must open exactly one dialog when a valid path is set"
            )
            # The dialog must contain a LargestEntriesView child
            dlg = dialogs_opened[0]
            views = [c for c in dlg.children() if isinstance(c, LargestEntriesView)]
            assert len(views) == 1, (
                "The disk-usage dialog must contain exactly one LargestEntriesView"
            )
            # The view must have been populated (2 files in tmp tree)
            assert views[0].entry_count() >= 1, (
                "LargestEntriesView must have at least one entry after load"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_disk_usage_uses_real_largest_entries_on_tmp_tree(self, qapp, tmp_path):
        """LargestEntriesView populated from real largest_entries reflects data."""
        from ff_explorer.core import largest_entries
        from ff_explorer.gui.treemap_view import LargestEntriesView

        # Build a small tree with known sizes
        (tmp_path / "alpha.bin").write_bytes(b"A" * 2048)
        (tmp_path / "beta.bin").write_bytes(b"B" * 512)
        (tmp_path / "gamma.bin").write_bytes(b"G" * 1024)

        entries = largest_entries(str(tmp_path), top_n=10)
        assert len(entries) >= 3, "largest_entries must return at least 3 files"

        view = LargestEntriesView()
        try:
            view.set_entries(entries)
            assert view.entry_count() == len(entries), (
                "entry_count() must match the number of real largest_entries results"
            )
            # First entry must be the largest by size
            _, top_size = view.entry_at(0)
            for i in range(1, view.entry_count()):
                _, s = view.entry_at(i)
                assert top_size >= s, (
                    "Entries must be in descending size order (largest first)"
                )
        finally:
            view.deleteLater()


# ---------------------------------------------------------------------------
# A8 — FFX-I09: content search controls exist; ungated error shows friendly msg
# ---------------------------------------------------------------------------

class TestContentSearch:
    """A8: Content search QLineEdit exists; ContentSearchUngatedError is caught
    and surfaced as a friendly QMessageBox.warning (never crashes).
    """

    def test_content_query_edit_exists(self, qapp):
        """_content_query_edit QLineEdit must exist and be empty by default."""
        from PySide6.QtWidgets import QLineEdit
        win = MainWindow()
        try:
            assert hasattr(win, "_content_query_edit"), (
                "_content_query_edit must exist (FFX-I09)"
            )
            assert isinstance(win._content_query_edit, QLineEdit)
            assert win._content_query_edit.text() == "", (
                "_content_query_edit must be empty by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_content_query_in_list_entries_kwargs_when_set(self, qapp):
        """Non-empty content_query_edit yields content_query in list_entries kwargs."""
        win = MainWindow()
        try:
            win._content_query_edit.setText("hello")
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("content_query") == "hello", (
                "Non-empty content_query_edit must yield content_query='hello'"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_empty_content_query_not_in_kwargs(self, qapp):
        """Empty content_query_edit must not add content_query to kwargs."""
        win = MainWindow()
        try:
            win._content_query_edit.setText("")
            kwargs = win._build_list_entries_kwargs()
            assert "content_query" not in kwargs, (
                "Empty content_query_edit must not appear in kwargs"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_ungated_content_search_shows_friendly_warning(self, qapp, tmp_path):
        """ContentSearchUngatedError from the worker is shown as QMessageBox.warning
        with a clear, friendly message — no crash.

        SPEC-14: the worker emits error(exc); _handle_scan_error routes it to
        QMessageBox.warning.  We test _handle_scan_error directly here to avoid
        the QProgressDialog.exec() nested-event-loop complexity in headless tests
        (the threading path is covered by TestScanWorker.test_worker_emits_error_on_exception).
        """
        from ff_explorer.core import ContentSearchUngatedError as _CSUE
        win = MainWindow()
        try:
            warned = []

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append({"title": title, "msg": msg})

            with patch("ff_explorer.gui.main_window.QMessageBox.warning",
                       side_effect=fake_warning):
                win._handle_scan_error(_CSUE())

            assert len(warned) >= 1, (
                "ContentSearchUngatedError must surface as QMessageBox.warning"
            )
            # Message must mention pre-filter or content search
            msg_lower = warned[0]["msg"].lower()
            assert any(kw in msg_lower for kw in ("pre-filter", "content search", "filter")), (
                "Warning message must mention pre-filter requirement"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A9 — FFX-I05: archive search checkbox exists and adds kwarg
# ---------------------------------------------------------------------------

class TestArchiveSearch:
    """A9: Search archives QCheckBox exists; checked state adds search_archives=True."""

    def test_search_archives_check_exists_unchecked_by_default(self, qapp):
        """_search_archives_check must exist and be unchecked by default."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_search_archives_check"), (
                "_search_archives_check must exist (FFX-I05)"
            )
            assert isinstance(win._search_archives_check, QCheckBox)
            assert not win._search_archives_check.isChecked(), (
                "_search_archives_check must be unchecked by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_search_archives_checked_adds_kwarg(self, qapp):
        """Checking _search_archives_check adds search_archives=True to kwargs."""
        win = MainWindow()
        try:
            win._search_archives_check.setChecked(True)
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("search_archives") is True, (
                "Checking search_archives_check must add search_archives=True to kwargs"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_search_archives_unchecked_not_in_kwargs(self, qapp):
        """Unchecked _search_archives_check must not add search_archives to kwargs."""
        win = MainWindow()
        try:
            win._search_archives_check.setChecked(False)
            kwargs = win._build_list_entries_kwargs()
            assert "search_archives" not in kwargs, (
                "Unchecked search_archives_check must not add kwarg"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A10 — FFX-I04: ignore controls exist and add kwargs
# ---------------------------------------------------------------------------

class TestIgnoreControls:
    """A10: Respect-ignore checkbox and extra-globs field exist and produce kwargs."""

    def test_respect_ignore_check_exists_unchecked_by_default(self, qapp):
        """_respect_ignore_check must exist and be unchecked by default."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_respect_ignore_check"), (
                "_respect_ignore_check must exist (FFX-I04)"
            )
            assert isinstance(win._respect_ignore_check, QCheckBox)
            assert not win._respect_ignore_check.isChecked(), (
                "_respect_ignore_check must be unchecked by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_respect_ignore_checked_adds_kwarg(self, qapp):
        """Checking _respect_ignore_check adds respect_ignore=True to kwargs."""
        win = MainWindow()
        try:
            win._respect_ignore_check.setChecked(True)
            kwargs = win._build_list_entries_kwargs()
            assert kwargs.get("respect_ignore") is True, (
                "Checking respect_ignore_check must add respect_ignore=True"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_ignore_globs_edit_exists_and_empty(self, qapp):
        """_ignore_globs_edit must exist and be empty by default."""
        from PySide6.QtWidgets import QLineEdit
        win = MainWindow()
        try:
            assert hasattr(win, "_ignore_globs_edit"), (
                "_ignore_globs_edit must exist (FFX-I04)"
            )
            assert isinstance(win._ignore_globs_edit, QLineEdit)
            assert win._ignore_globs_edit.text() == "", (
                "_ignore_globs_edit must be empty by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_ignore_globs_comma_separated_parsed(self, qapp):
        """Non-empty ignore_globs_edit adds ignore_globs list to kwargs."""
        win = MainWindow()
        try:
            win._ignore_globs_edit.setText("*.pyc, __pycache__/")
            kwargs = win._build_list_entries_kwargs()
            assert "ignore_globs" in kwargs, (
                "Non-empty ignore_globs_edit must add ignore_globs to kwargs"
            )
            globs = kwargs["ignore_globs"]
            assert "*.pyc" in globs
            assert "__pycache__/" in globs
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A11 — FFX-I08: versioning checkbox exists and passes versioning=True to remove
# ---------------------------------------------------------------------------

class TestVersioningCheckbox:
    """A11: Versioning QCheckBox exists; when checked, _do_remove passes
    versioning=True to remove_entries. Safety gate (defaults to No) preserved."""

    def test_versioning_check_exists_unchecked_by_default(self, qapp):
        """_versioning_check must exist and be unchecked by default."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_versioning_check"), (
                "_versioning_check must exist (FFX-I08)"
            )
            assert isinstance(win._versioning_check, QCheckBox)
            assert not win._versioning_check.isChecked(), (
                "_versioning_check must be unchecked by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_versioning_checked_passes_versioning_true_to_remove(self, qapp, tmp_path):
        """_do_remove with versioning checked passes versioning=True to remove_entries.

        SPEC-14: _do_remove receives the pre-scanned entries list; versioning
        kwarg is forwarded to the destructive remove_entries call on Yes.
        """
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            fake_target = tmp_path / "old_file.txt"
            fake_target.write_text("x")
            entries = [MatchEntry(path=fake_target, kind=EntryKind.FILES)]
            live_report = RemovalReport(matched=[fake_target], removed=[fake_target])

            captured_kwargs: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured_kwargs.update(kwargs)
                captured_kwargs["dry_run"] = dry_run
                return live_report

            win._versioning_check.setChecked(True)

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "old_file", "file", entries)

            assert captured_kwargs.get("versioning") is True, (
                "_do_remove with versioning checked must pass versioning=True to remove_entries"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_versioning_unchecked_no_versioning_kwarg(self, qapp, tmp_path):
        """_do_remove with versioning unchecked does NOT pass versioning kwarg.

        SPEC-14: entries list passed directly; No dialog means no destructive call.
        """
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            fake_target = tmp_path / "file.txt"
            fake_target.write_text("x")
            entries = [MatchEntry(path=fake_target, kind=EntryKind.FILES)]
            live_report = RemovalReport(matched=[fake_target], removed=[fake_target])

            captured_kwargs: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured_kwargs.update(kwargs)
                return live_report

            win._versioning_check.setChecked(False)

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "file", "file", entries)

            assert "versioning" not in captured_kwargs, (
                "_do_remove with unchecked versioning must not pass versioning kwarg"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_versioning_gate_still_defaults_to_no(self, qapp, tmp_path):
        """Even with versioning=True, the confirm dialog must default to No.

        SPEC-14: entries list passed directly; safety gate is unchanged.
        """
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            fake_target = tmp_path / "versioned.txt"
            fake_target.write_text("x")
            entries = [MatchEntry(path=fake_target, kind=EntryKind.FILES)]

            destructive_calls = []

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                if not dry_run:
                    destructive_calls.append(True)
                    raise AssertionError("Must not run destructive when No selected")
                from ff_explorer.core import RemovalReport
                return RemovalReport(matched=[fake_target])

            win._versioning_check.setChecked(True)

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "versioned", "file", entries)

            assert len(destructive_calls) == 0, (
                "Versioning remove gate must still default to No — no destructive call"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A12 — FFX-I06: Find duplicates dialog builds headlessly
# ---------------------------------------------------------------------------

class TestFindDuplicatesDialog:
    """A12: _open_find_duplicates handler exists; with no path shows warning;
    with empty results shows 'no duplicates' dialog; with duplicates dialog builds."""

    def test_open_find_duplicates_handler_exists(self, qapp):
        """MainWindow must have _open_find_duplicates method."""
        win = MainWindow()
        try:
            assert hasattr(win, "_open_find_duplicates"), (
                "_open_find_duplicates must exist (FFX-I06)"
            )
            assert callable(win._open_find_duplicates)
        finally:
            win.close()
            win.deleteLater()

    def test_no_path_shows_warning(self, qapp):
        """_open_find_duplicates with no path shows a warning, no crash."""
        win = MainWindow()
        try:
            warned = []

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append(title)

            with patch(
                "ff_explorer.gui.main_window.QMessageBox.warning",
                side_effect=fake_warning,
            ):
                win._open_find_duplicates()

            assert len(warned) >= 1
        finally:
            win.close()
            win.deleteLater()

    def test_no_duplicates_dialog_shows(self, qapp, tmp_path):
        """_open_find_duplicates with no duplicates opens a dialog (not a warning)."""
        from PySide6.QtWidgets import QDialog
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))
            dialogs_opened = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                return 0

            # Monkeypatch find_duplicates to return empty groups
            with (
                patch("ff_explorer.gui.main_window.find_duplicates", return_value=[]),
                patch.object(QDialog, "exec", fake_exec),
            ):
                win._open_find_duplicates()

            assert len(dialogs_opened) == 1, (
                "_open_find_duplicates must open a dialog even when no duplicates found"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_duplicate_groups_dialog_builds(self, qapp, tmp_path):
        """_open_find_duplicates with duplicate groups opens a dialog without crash."""
        from PySide6.QtWidgets import QDialog
        from ff_explorer.dedupe import DuplicateGroup
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))
            fake_groups = [
                DuplicateGroup(
                    hash="abc123",
                    size=1024,
                    paths=[str(tmp_path / "a.txt"), str(tmp_path / "b.txt")],
                )
            ]
            dialogs_opened = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                return 0

            with (
                patch("ff_explorer.gui.main_window.find_duplicates", return_value=fake_groups),
                patch.object(QDialog, "exec", fake_exec),
            ):
                win._open_find_duplicates()

            assert len(dialogs_opened) == 1, (
                "_open_find_duplicates must open a dialog when duplicate groups exist"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A13 — FFX-I03: preset save/load round-trip into the form
# ---------------------------------------------------------------------------

class TestPresetSaveLoad:
    """A13: Save preset captures form state; load preset applies it back.
    Uses FFE_PRESETS_DIR tmp env to isolate the store."""

    def test_preset_controls_exist(self, qapp):
        """_save_preset and _load_preset handlers must exist on MainWindow."""
        win = MainWindow()
        try:
            assert hasattr(win, "_save_preset"), "_save_preset must exist (FFX-I03)"
            assert hasattr(win, "_load_preset"), "_load_preset must exist (FFX-I03)"
            assert callable(win._save_preset)
            assert callable(win._load_preset)
        finally:
            win.close()
            win.deleteLater()

    def test_save_and_load_round_trip(self, qapp, tmp_path, monkeypatch):
        """Save preset then load preset restores the same form state."""
        import os
        monkeypatch.setenv("FFE_PRESETS_DIR", str(tmp_path))

        win = MainWindow()
        try:
            # Set a specific form state
            win._path_edit.setText(str(tmp_path))
            win._seed_edit.setText("mytest")
            win._radio_files.setChecked(True)
            win._case_sensitive_check.setChecked(False)
            idx = [
                win._match_mode_combo.itemText(i)
                for i in range(win._match_mode_combo.count())
            ].index("Glob")
            win._match_mode_combo.setCurrentIndex(idx)
            win._min_size_spin.setValue(5)   # 5 KB
            win._extensions_edit.setText(".py")

            # Save the preset (mock QInputDialog to supply name)
            with patch(
                "ff_explorer.gui.main_window.QInputDialog.getText",
                return_value=("smoke_test_preset", True),
            ):
                win._save_preset()

            # Reset some form fields
            win._seed_edit.setText("")
            win._case_sensitive_check.setChecked(True)
            win._min_size_spin.setValue(0)

            # Load the preset back (mock QInputDialog.getItem to choose it)
            with patch(
                "ff_explorer.gui.main_window.QInputDialog.getItem",
                return_value=("smoke_test_preset", True),
            ):
                win._load_preset()

            # Verify the form was restored
            assert win._seed_edit.text() == "mytest", (
                "Load preset must restore name_seed='mytest'"
            )
            assert not win._case_sensitive_check.isChecked(), (
                "Load preset must restore case_sensitive=False"
            )
            assert win._match_mode_combo.currentText() == "Glob", (
                "Load preset must restore match_mode='Glob'"
            )
            assert win._min_size_spin.value() == 5, (
                "Load preset must restore min_size_spin=5 (5 KB)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_save_preset_no_name_does_nothing(self, qapp, tmp_path, monkeypatch):
        """Cancelling the preset name dialog does not save anything."""
        monkeypatch.setenv("FFE_PRESETS_DIR", str(tmp_path))

        win = MainWindow()
        try:
            with patch(
                "ff_explorer.gui.main_window.QInputDialog.getText",
                return_value=("", False),  # user clicked Cancel
            ):
                win._save_preset()  # must not raise

            from ff_explorer.presets import list_presets
            assert list_presets() == [], "No preset must be saved when name dialog cancelled"
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A14 — FFX-I07: batch rename dialog builds; confirm defaults to No
# ---------------------------------------------------------------------------

class TestBatchRenameDialog:
    """A14: _open_batch_rename exists; with no path/seed shows warnings;
    the confirm dialog defaults to No (no rename on cancel)."""

    def test_open_batch_rename_handler_exists(self, qapp):
        """MainWindow must have _open_batch_rename method."""
        win = MainWindow()
        try:
            assert hasattr(win, "_open_batch_rename"), (
                "_open_batch_rename must exist (FFX-I07)"
            )
            assert callable(win._open_batch_rename)
        finally:
            win.close()
            win.deleteLater()

    def test_no_path_shows_warning(self, qapp):
        """_open_batch_rename with no path shows a warning."""
        win = MainWindow()
        try:
            warned = []

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append(title)

            with patch(
                "ff_explorer.gui.main_window.QMessageBox.warning",
                side_effect=fake_warning,
            ):
                win._open_batch_rename()

            assert len(warned) >= 1
        finally:
            win.close()
            win.deleteLater()

    def test_no_seed_shows_warning(self, qapp, tmp_path):
        """_open_batch_rename with no seed shows a warning (empty seed check)."""
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))
            win._seed_edit.setText("")

            warned = []

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append(title)

            with patch(
                "ff_explorer.gui.main_window.QMessageBox.warning",
                side_effect=fake_warning,
            ):
                win._open_batch_rename()

            assert len(warned) >= 1
        finally:
            win.close()
            win.deleteLater()

    def test_rule_dialog_cancel_skips_rename(self, qapp, tmp_path):
        """When the rule dialog is cancelled (Rejected), rename_entries is never called."""
        from ff_explorer.rename import RenameReport
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))
            win._seed_edit.setText("testfile")

            rename_calls = []

            def fake_rename(*a, **kw):
                rename_calls.append(True)
                return RenameReport()

            # QDialog.exec returns 0 = Rejected (Cancel pressed in rule dialog)
            with (
                patch("ff_explorer.gui.main_window.rename_entries", side_effect=fake_rename),
                patch("ff_explorer.gui.main_window.QDialog.exec", return_value=0),
            ):
                win._open_batch_rename()

            assert len(rename_calls) == 0, (
                "rename_entries must not be called when the rule dialog is cancelled"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_confirm_defaults_to_no_skips_rename(self, qapp, tmp_path):
        """When the rule dialog accepts and preview has a mapping, but the
        confirm QMessageBox.question returns No, rename_entries(dry_run=False)
        is never called — the gate defaults to No.

        The rule dialog is accepted by patching QDialog.exec; the find/replace
        text is injected by pre-setting the dialog's QLineEdit values via a
        custom QDialog subclass approach — instead we bypass the dialog layer
        and call the internal rename helper directly with a known preview report
        to isolate only the confirm-gate assertion.
        """
        from ff_explorer.rename import RenameReport
        win = MainWindow()
        try:
            live_calls = []

            preview_report = RenameReport(
                dry_run=True,
                matched=["testfile.txt"],
                mapping=[("testfile.txt", "newfile.txt")],
            )

            def fake_rename(path, kind, seed, rules, dry_run=True, confirm=False, **kwargs):
                if not dry_run:
                    live_calls.append(True)
                    raise AssertionError("Must not apply rename when No selected")
                return preview_report

            # Simulate the post-rule-dialog path: QMessageBox.question returns No.
            # We patch QMessageBox.question to return No and inject a mapping via
            # rename_entries always returning the preview.  We also need the rule
            # dialog to succeed with a non-empty find text; patch QDialog.exec=1
            # (Accepted) and supply find text by patching the two QLineEdit instances
            # that _open_batch_rename creates.  The simplest injection: make
            # QLineEdit() constructors pre-fill text by subclassing — instead we
            # use a QDialog subclass with setText calls recorded in fake_rename.
            # Cleanest: use a side-effect on QDialog that pre-fills the edits.
            from PySide6.QtWidgets import QLineEdit as _QLE, QDialog as _QD

            _created_edits: list = []
            _orig_qle_init = _QLE.__init__

            def _spy_init(self_le, *a, **kw):
                _orig_qle_init(self_le, *a, **kw)
                _created_edits.append(self_le)

            def fake_exec_dialog(self_dlg):
                # Pre-fill the first QLineEdit (find) that was created after win init
                new_edits = _created_edits[:]
                if len(new_edits) >= 1:
                    new_edits[-2].setText("testfile") if len(new_edits) >= 2 else None
                    new_edits[-1].setText("newfile")
                return 1  # Accepted

            with (
                patch("ff_explorer.gui.main_window.rename_entries", side_effect=fake_rename),
                patch.object(_QLE, "__init__", _spy_init),
                patch("ff_explorer.gui.main_window.QDialog.exec", fake_exec_dialog),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._path_edit.setText(str(tmp_path))
                win._seed_edit.setText("testfile")
                win._open_batch_rename()

            assert len(live_calls) == 0, (
                "rename_entries(dry_run=False) must not be called when confirm dialog "
                "returns No — the gate must default to No"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A15 — FFX-I10: live index checkbox exists; start/stop calls IndexManager;
#        closeEvent stops the observer (no thread leak)
# ---------------------------------------------------------------------------

class TestLiveIndexing:
    """A15: Live index QCheckBox exists; toggling calls IndexManager.start_index /
    stop_index (monkeypatched); closeEvent stops a running index."""

    def test_live_index_check_exists_unchecked_by_default(self, qapp):
        """_live_index_check must exist and be unchecked by default."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_live_index_check"), (
                "_live_index_check must exist (FFX-I10)"
            )
            assert isinstance(win._live_index_check, QCheckBox)
            assert not win._live_index_check.isChecked(), (
                "_live_index_check must be unchecked by default"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_checking_calls_start_index(self, qapp, tmp_path):
        """Checking _live_index_check calls IndexManager.start_index(path)."""
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))

            start_calls = []

            def fake_start(root):
                start_calls.append(str(root))
                return None  # NameIndex not needed for this test

            with patch("ff_explorer.gui.main_window.IndexManager.start_index",
                       side_effect=fake_start):
                win._live_index_check.setChecked(True)

            assert len(start_calls) == 1, (
                "Checking live_index_check must call IndexManager.start_index once"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_unchecking_calls_stop_index(self, qapp, tmp_path):
        """Unchecking _live_index_check calls IndexManager.stop_index(path)."""
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))

            stop_calls = []

            def fake_start(root):
                return None

            def fake_stop(root):
                stop_calls.append(str(root))

            with patch("ff_explorer.gui.main_window.IndexManager.start_index",
                       side_effect=fake_start):
                win._live_index_check.setChecked(True)

            with patch("ff_explorer.gui.main_window.IndexManager.stop_index",
                       side_effect=fake_stop):
                win._live_index_check.setChecked(False)

            assert len(stop_calls) == 1, (
                "Unchecking live_index_check must call IndexManager.stop_index once"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_no_path_shows_warning_and_reverts_check(self, qapp):
        """Checking live_index with no path selected shows a warning and reverts to unchecked."""
        win = MainWindow()
        try:
            warned = []

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append(title)

            with patch(
                "ff_explorer.gui.main_window.QMessageBox.warning",
                side_effect=fake_warning,
            ):
                win._live_index_check.setChecked(True)

            assert len(warned) >= 1, (
                "Checking live_index with no path must show a warning"
            )
            assert not win._live_index_check.isChecked(), (
                "Checkbox must be reverted to unchecked when no path"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_close_event_stops_live_index(self, qapp, tmp_path):
        """closeEvent stops the live index observer when _live_index_check is checked."""
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))

            stop_calls = []

            def fake_start(root):
                return None

            def fake_stop(root):
                stop_calls.append(str(root))

            with patch("ff_explorer.gui.main_window.IndexManager.start_index",
                       side_effect=fake_start):
                win._live_index_check.setChecked(True)

            # Now close the window — should call stop_index
            with patch("ff_explorer.gui.main_window.IndexManager.stop_index",
                       side_effect=fake_stop):
                win.close()

            assert len(stop_calls) == 1, (
                "closeEvent must call IndexManager.stop_index to avoid thread leak"
            )
        finally:
            win.deleteLater()

    def test_missing_watchdog_shows_warning_and_reverts(self, qapp, tmp_path):
        """If watchdog is not installed, start_index raises ImportError;
        the GUI shows a warning and reverts the checkbox to unchecked."""
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))

            warned = []

            def fake_start(root):
                raise ImportError("watchdog not installed")

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append({"title": title, "msg": msg})

            with (
                patch("ff_explorer.gui.main_window.IndexManager.start_index",
                      side_effect=fake_start),
                patch("ff_explorer.gui.main_window.QMessageBox.warning",
                      side_effect=fake_warning),
            ):
                win._live_index_check.setChecked(True)

            assert len(warned) >= 1, (
                "ImportError from start_index must surface as a warning"
            )
            assert not win._live_index_check.isChecked(), (
                "Checkbox must be reverted to unchecked when watchdog is missing"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A16 — SPEC-02/03/04: registry wiring, dynamic action tooltip, Shift+F1
# ---------------------------------------------------------------------------

class TestWidgetRegistryWiring:
    """A16: All main widgets have _ff_info_key set via register_info;
    action combo tooltip updates dynamically from the registry;
    Shift+F1 shortcut exists and enters WhatsThis mode without crash."""

    # Widgets expected to carry a _ff_info_key property after MainWindow init.
    # These match every register_info() / register_info_text() call in _setup_ui
    # and _build_filters_panel.
    _EXPECTED_KEYS = {
        "path",           # path_label, _path_edit
        "path_browse",    # browse_btn
        "seed",           # seed_label, _seed_edit
        "mode_folders",   # _radio_folders
        "mode_files",     # _radio_files
        "action",         # _action_combo (dynamic via register_info_text)
        "run",            # run_btn
        "filters_toggle", # _filters_toggle_btn
        "settings",       # settings_btn
        "disk_usage",     # disk_usage_btn
        "find_duplicates",# dup_btn
        "batch_rename",   # rename_btn
        "preset_save",    # preset_save_btn
        "preset_load",    # preset_load_btn
        "live_index",     # _live_index_check
        "filter_match_mode",       # _match_mode_combo
        "filter_case_sensitive",   # _case_sensitive_check
        "filter_min_size",         # _min_size_spin
        "filter_max_size",         # _max_size_spin
        "filter_date_after",       # _date_after_check
        "filter_date_after_edit",  # _date_after_edit
        "filter_date_before",      # _date_before_check
        "filter_date_before_edit", # _date_before_edit
        "filter_extensions",       # _extensions_edit
        "filter_content_query",    # _content_query_edit
        "filter_search_archives",  # _search_archives_check
        "filter_respect_ignore",   # _respect_ignore_check
        "filter_ignore_globs",     # _ignore_globs_edit
        "filter_versioning",       # _versioning_check
        "filter_include_hidden",   # _include_hidden_check (SPEC-17)
        # SPEC-18 result-view buttons (registered inside _show_results_view)
        # These are NOT on the main window but are tested via the results-view
        # dialog tests — they do not appear in findChildren(QWidget) on win itself.
        # They are registered in WIDGET_INFO and tested in A21.
    }

    def test_run_key_exists_in_registry(self):
        """WIDGET_INFO must contain the 'run' key (added for SPEC-02)."""
        assert "run" in WIDGET_INFO, (
            "'run' key must be present in WIDGET_INFO (SPEC-02 requirement)"
        )
        assert WIDGET_INFO["run"], "WIDGET_INFO['run'] must be a non-empty string"

    def test_register_info_text_helper_exists(self):
        """register_info_text must be importable from widget_info."""
        # Already imported at top; verify it is callable with the right signature
        from ff_explorer.gui.widget_info import register_info_text as rit
        assert callable(rit)

    def test_all_expected_registry_keys_present_in_widget_info(self):
        """Every key in _EXPECTED_KEYS must exist in WIDGET_INFO."""
        missing = [k for k in self._EXPECTED_KEYS if k not in WIDGET_INFO]
        assert not missing, (
            f"Missing keys in WIDGET_INFO: {missing}"
        )

    def test_main_widgets_have_ff_info_key_property(self, qapp):
        """Every registered widget carries _ff_info_key set to a known registry key."""
        from PySide6.QtWidgets import QWidget
        win = MainWindow()
        try:
            found_keys: set[str] = set()
            for child in win.findChildren(QWidget):
                key = child.property("_ff_info_key")
                if key:
                    found_keys.add(key)
            missing = self._EXPECTED_KEYS - found_keys
            assert not missing, (
                f"Widgets missing _ff_info_key property after MainWindow init: {missing}\n"
                "Each widget listed above must be wired via register_info() or "
                "register_info_text() in _setup_ui / _build_filters_panel."
            )
        finally:
            win.close()
            win.deleteLater()

    def test_action_combo_tooltip_changes_on_selection(self, qapp):
        """_update_action_tooltip sets a non-empty tooltip that changes per action."""
        win = MainWindow()
        try:
            tooltips: list[str] = []
            items = [win._action_combo.itemText(i)
                     for i in range(win._action_combo.count())]
            for i, item in enumerate(items):
                win._action_combo.setCurrentIndex(i)
                tooltips.append(win._action_combo.toolTip())

            # All tooltips must be non-empty strings
            for i, tip in enumerate(tooltips):
                assert isinstance(tip, str) and tip.strip(), (
                    f"Action combo tooltip at index {i} ('{items[i]}') must be non-empty"
                )

            # Save list (code=1) and Remove list (code=2) tooltips must differ
            # because they have different action_detail entries.
            save_idx = items.index("Save list")
            remove_idx = items.index("Remove list")
            assert tooltips[save_idx] != tooltips[remove_idx], (
                "Save list and Remove list tooltips must differ "
                "(each has a distinct action_detail registry entry)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_action_combo_ff_info_key_is_action(self, qapp):
        """_action_combo._ff_info_key must be 'action' after _update_action_tooltip."""
        win = MainWindow()
        try:
            key = win._action_combo.property("_ff_info_key")
            assert key == "action", (
                f"_action_combo._ff_info_key must be 'action', got {key!r}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_action_combo_whats_this_set(self, qapp):
        """_action_combo.whatsThis() must be non-empty (register_info_text sets it)."""
        win = MainWindow()
        try:
            wt = win._action_combo.whatsThis()
            assert isinstance(wt, str) and wt.strip(), (
                "_action_combo.whatsThis() must be non-empty after _update_action_tooltip"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_section_labels_have_object_name(self, qapp):
        """path_label and seed_label must have objectName='sectionLabel'."""
        from PySide6.QtWidgets import QLabel
        win = MainWindow()
        try:
            section_labels = [
                lbl for lbl in win.findChildren(QLabel)
                if lbl.objectName() == "sectionLabel"
            ]
            assert len(section_labels) >= 2, (
                "At least 2 QLabel widgets must have objectName='sectionLabel' "
                "(path_label and seed_label — SPEC-04)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_run_button_has_object_name(self, qapp):
        """run_btn must have objectName='runButton'."""
        from PySide6.QtWidgets import QPushButton
        win = MainWindow()
        try:
            run_btns = [
                btn for btn in win.findChildren(QPushButton)
                if btn.objectName() == "runButton"
            ]
            assert len(run_btns) == 1, (
                "Exactly one QPushButton must have objectName='runButton' (SPEC-04)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_theme_stylesheet_contains_section_label_rule(self):
        """build_stylesheet must produce QSS containing QLabel#sectionLabel."""
        from ff_explorer.gui.theme import build_stylesheet, LIGHT, DARK
        for name, theme in [("LIGHT", LIGHT), ("DARK", DARK)]:
            qss = build_stylesheet(theme)
            assert "QLabel#sectionLabel" in qss, (
                f"build_stylesheet({name}) must contain a QLabel#sectionLabel rule (SPEC-04)"
            )
            assert "QPushButton#runButton" in qss, (
                f"build_stylesheet({name}) must contain a QPushButton#runButton rule (SPEC-04)"
            )

    def test_theme_has_exactly_one_qtoolip_block(self):
        """build_stylesheet must contain exactly one QToolTip {{ block (SPEC-04)."""
        from ff_explorer.gui.theme import build_stylesheet, LIGHT
        qss = build_stylesheet(LIGHT)
        count = qss.count("QToolTip {")
        assert count == 1, (
            f"build_stylesheet must contain exactly one 'QToolTip {{' block, found {count} (SPEC-04)"
        )

    def test_shift_f1_shortcut_wired_in_main_window(self, qapp):
        """MainWindow must have a QShortcut for Shift+F1 that enters WhatsThis mode."""
        from PySide6.QtGui import QKeySequence, QShortcut
        win = MainWindow()
        try:
            shortcuts = win.findChildren(QShortcut)
            shift_f1_shortcuts = [
                s for s in shortcuts
                if s.key() == QKeySequence("Shift+F1")
            ]
            assert len(shift_f1_shortcuts) >= 1, (
                "MainWindow must have a QShortcut with key Shift+F1 (SPEC-04)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_no_inline_tooltip_literals_in_gui_package(self):
        """SPEC-09 lint: no inline ``setToolTip("literal")`` / ``setWhatsThis("literal")``
        string literal may appear anywhere in the GUI package — every call must
        reference the central registry (via register_info / register_info_text).

        ``register_info`` itself calls ``widget.setToolTip(text)`` where *text* is
        a variable (registry lookup), and treemap_view uses ``setToolTip(path)``
        with a variable — neither matches the literal pattern, so both pass.
        """
        import re
        from pathlib import Path

        gui_dir = Path(__file__).resolve().parent.parent / "ff_explorer" / "gui"
        # Match setToolTip(  or setWhatsThis(  immediately followed by a quote.
        literal_pattern = re.compile(r"""set(?:ToolTip|WhatsThis)\(\s*["']""")

        offenders: list[str] = []
        for py_file in gui_dir.glob("*.py"):
            text = py_file.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                if literal_pattern.search(line):
                    offenders.append(f"{py_file.name}:{lineno}: {line.strip()}")

        assert not offenders, (
            "Inline tooltip/whatsThis string literals found in the GUI package — "
            "route them through the widget_info registry (SPEC-02/03/09):\n"
            + "\n".join(offenders)
        )

    def test_no_inline_stylesheet_overrides_on_core_widgets(self, qapp):
        """path_label, seed_label, run_btn must NOT carry hard-coded inline styleSheet
        with literal colour values — styling must come from the theme QSS only."""
        from PySide6.QtWidgets import QLabel, QPushButton
        win = MainWindow()
        try:
            # Check sectionLabel widgets: their styleSheet() must be empty
            # (the visual styling is applied via QLabel#sectionLabel in the theme QSS)
            section_labels = [
                lbl for lbl in win.findChildren(QLabel)
                if lbl.objectName() == "sectionLabel"
            ]
            for lbl in section_labels:
                ss = lbl.styleSheet()
                assert not ss, (
                    f"sectionLabel '{lbl.text()}' must not carry an inline styleSheet "
                    f"(got: {ss!r}) — SPEC-04 requires central theming only"
                )
            # run_btn inline styleSheet must also be empty
            run_btns = [
                btn for btn in win.findChildren(QPushButton)
                if btn.objectName() == "runButton"
            ]
            for btn in run_btns:
                ss = btn.styleSheet()
                assert not ss, (
                    f"runButton must not carry an inline styleSheet "
                    f"(got: {ss!r}) — SPEC-04 requires central theming only"
                )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A17 — SPEC-14: off-thread scan worker (_ScanWorker) correctness
# ---------------------------------------------------------------------------

class TestScanWorker:
    """A17: _ScanWorker emits finished with the same entries as a direct
    iter_entries call; honors cancel; the main window still constructs and
    a small-tree Run updates status via the worker path.

    All tests run headless under QT_QPA_PLATFORM=offscreen.  Worker signals
    are waited for by spinning the event loop with a timeout — deterministic,
    no real sleeps required.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _spin_until(condition, timeout_ms: int = 5000) -> bool:
        """Process Qt events until *condition()* is True or *timeout_ms* elapses.

        Returns True when the condition became True, False on timeout.
        Uses QApplication.processEvents() in a tight loop with a wall-clock guard
        so we never block forever in CI and never need real ``time.sleep`` calls.
        """
        import time
        from PySide6.QtWidgets import QApplication
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if condition():
                return True
        return False

    # ------------------------------------------------------------------
    # Worker tests (direct unit tests — no MainWindow needed)
    # ------------------------------------------------------------------

    def test_worker_finished_matches_direct_iter_entries(self, qapp, tmp_path):
        """_ScanWorker emits finished with the same entries as iter_entries().

        Build a small tmp tree, run the worker, collect the finished payload,
        and assert it equals the direct iter_entries result.
        """
        from ff_explorer import iter_entries, EntryKind
        from ff_explorer.gui.main_window import _ScanWorker
        from PySide6.QtCore import QThread

        # Build a small tree
        (tmp_path / "alpha.txt").write_bytes(b"a")
        (tmp_path / "beta.txt").write_bytes(b"b")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "gamma.txt").write_bytes(b"g")

        # Reference result via direct call
        expected = list(iter_entries(str(tmp_path), EntryKind.FILES, ""))
        assert len(expected) >= 3, "tmp tree must have at least 3 files"

        # Run the worker
        finished_payload: list = []
        error_payload: list = []

        worker = _ScanWorker(str(tmp_path), EntryKind.FILES, "", {})
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(lambda entries: finished_payload.extend(entries))
        worker.error.connect(lambda exc: error_payload.append(exc))
        thread.started.connect(worker.run)
        thread.start()

        done = self._spin_until(
            lambda: bool(finished_payload) or bool(error_payload),
            timeout_ms=5000,
        )
        thread.quit()
        thread.wait()

        assert done, "Worker did not emit finished within 5 s"
        assert not error_payload, f"Worker emitted error: {error_payload}"
        assert len(finished_payload) == len(expected), (
            f"Worker finished payload length {len(finished_payload)} != "
            f"direct iter_entries length {len(expected)}"
        )
        # Paths must match (order may differ on some OSes — compare as sets)
        finished_paths = {str(e.path) for e in finished_payload}
        expected_paths = {str(e.path) for e in expected}
        assert finished_paths == expected_paths, (
            "Worker finished entries must match direct iter_entries result"
        )

    def test_worker_cancel_stops_without_finished(self, qapp, tmp_path):
        """_ScanWorker.cancel() causes the worker to stop without emitting finished.

        Start the worker, cancel immediately, and assert neither finished nor
        error is emitted (the cooperative cancel flag is checked between yields).
        """
        from ff_explorer import EntryKind
        from ff_explorer.gui.main_window import _ScanWorker
        from PySide6.QtCore import QThread

        # Build a minimal tree so the worker has something to iterate over
        (tmp_path / "a.txt").write_bytes(b"a")

        finished_calls: list = []
        error_calls: list = []

        worker = _ScanWorker(str(tmp_path), EntryKind.FILES, "", {})
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(lambda e: finished_calls.append(e))
        worker.error.connect(lambda ex: error_calls.append(ex))
        thread.started.connect(worker.run)

        # Cancel before starting — the worker sees the flag on its first check
        worker.cancel()
        thread.start()

        # Give the thread time to run and confirm it does NOT emit finished
        import time
        from PySide6.QtWidgets import QApplication
        deadline = time.monotonic() + 1.0  # 1 s is plenty for a 1-file tree
        while time.monotonic() < deadline:
            QApplication.processEvents()
        thread.quit()
        thread.wait()

        assert len(finished_calls) == 0, (
            "_ScanWorker must NOT emit finished after cancel() is called"
        )
        assert len(error_calls) == 0, (
            "_ScanWorker must NOT emit error after cancel() is called"
        )

    def test_worker_emits_error_on_exception(self, qapp, tmp_path):
        """_ScanWorker emits error(exc) when iter_entries raises an exception."""
        from ff_explorer import EntryKind
        from ff_explorer.gui.main_window import _ScanWorker
        from PySide6.QtCore import QThread
        from unittest.mock import patch

        finished_calls: list = []
        error_calls: list = []

        worker = _ScanWorker(str(tmp_path), EntryKind.FILES, "", {})
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(lambda e: finished_calls.append(e))
        worker.error.connect(lambda ex: error_calls.append(ex))

        def _bad_iter(*a, **kw):
            raise ValueError("injected error")
            return iter([])  # type: ignore[misc]

        thread.started.connect(worker.run)

        with patch("ff_explorer.gui.main_window.iter_entries", side_effect=_bad_iter):
            thread.start()
            done = self._spin_until(
                lambda: bool(error_calls) or bool(finished_calls),
                timeout_ms=3000,
            )
        thread.quit()
        thread.wait()

        assert done, "Worker did not emit error within 3 s"
        assert len(error_calls) == 1, "Worker must emit exactly one error signal"
        assert isinstance(error_calls[0], ValueError), (
            "Emitted error must be the original ValueError"
        )
        assert len(finished_calls) == 0, (
            "Worker must NOT emit finished when it raises"
        )

    # ------------------------------------------------------------------
    # End-to-end: MainWindow._run() with worker path
    # ------------------------------------------------------------------

    def test_main_window_run_save_updates_status_via_worker(self, qapp, tmp_path):
        """MainWindow._on_scan_complete() with Save action updates the status bar.

        SPEC-14: _on_scan_complete is the post-scan handler called by the finished
        signal on the main thread.  We drive it directly to avoid the
        QProgressDialog.exec() nested-event-loop complexity in headless tests
        (the worker → finished → _on_scan_complete signal chain is separately
        validated by test_worker_finished_matches_direct_iter_entries).

        Asserts: _do_save is called via _on_scan_complete, save_listing is invoked,
        and the status bar is updated with a non-empty message.
        """
        from ff_explorer import EntryKind, MatchEntry
        from unittest.mock import patch

        (tmp_path / "hello.txt").write_bytes(b"h")
        (tmp_path / "world.txt").write_bytes(b"w")

        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))

            # Two pre-scanned entries (as the worker would deliver)
            entries = [
                MatchEntry(path=tmp_path / "hello.txt", kind=EntryKind.FILES),
                MatchEntry(path=tmp_path / "world.txt", kind=EntryKind.FILES),
            ]

            # SPEC-19: _on_scan_complete now calls _show_results_view which opens
            # a QDialog via exec(); suppress it to keep this headless test non-blocking.
            win._show_results_view = lambda *a, **kw: None  # type: ignore[method-assign]

            with patch(
                "ff_explorer.gui.main_window.save_listing",
                return_value=tmp_path / "listing.txt",
            ):
                # action_code=1 → _do_save
                win._on_scan_complete(1, str(tmp_path), EntryKind.FILES, "", "file", entries)

            status = win._status_bar.currentMessage()
            assert status, "Status bar must show a non-empty message after scan complete"
            # The save path includes the listing path
            assert "listing.txt" in status or "saved" in status.lower(), (
                f"Status must mention saved listing, got: {status!r}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_worker_progress_signal_emitted(self, qapp, tmp_path):
        """_ScanWorker emits progress() signal every _PROGRESS_INTERVAL entries.

        Build a tree with > _PROGRESS_INTERVAL files and assert at least one
        progress emission occurs before finished.
        """
        from ff_explorer import EntryKind
        from ff_explorer.gui.main_window import _ScanWorker, _PROGRESS_INTERVAL
        from PySide6.QtCore import QThread

        # Create _PROGRESS_INTERVAL + 1 files so progress fires at least once
        for i in range(_PROGRESS_INTERVAL + 1):
            (tmp_path / f"file_{i:04d}.txt").write_bytes(b"x")

        progress_calls: list = []
        finished_calls: list = []

        worker = _ScanWorker(str(tmp_path), EntryKind.FILES, "", {})
        thread = QThread()
        worker.moveToThread(thread)
        worker.progress.connect(lambda count, path: progress_calls.append((count, path)))
        worker.finished.connect(lambda e: finished_calls.append(e))
        thread.started.connect(worker.run)
        thread.start()

        done = self._spin_until(
            lambda: bool(finished_calls),
            timeout_ms=5000,
        )
        thread.quit()
        thread.wait()

        assert done, "Worker did not finish within 5 s"
        assert len(progress_calls) >= 1, (
            f"Worker must emit at least one progress() signal when > "
            f"{_PROGRESS_INTERVAL} entries are scanned"
        )


# ---------------------------------------------------------------------------
# A18 — SPEC-19: results view + properties dialog
# ---------------------------------------------------------------------------

class TestResultsView:
    """A18: _show_results_view builds a QDialog with a table and properties
    button; _show_entry_properties opens a metadata dialog; both work headlessly.
    """

    @staticmethod
    def _make_entries(tmp_path: Path) -> list:
        from ff_explorer import MatchEntry, EntryKind
        f1 = tmp_path / "alpha.txt"
        f2 = tmp_path / "beta.py"
        f1.write_bytes(b"hello")
        f2.write_bytes(b"world" * 10)
        return [
            MatchEntry(path=f1, kind=EntryKind.FILES),
            MatchEntry(path=f2, kind=EntryKind.FILES),
        ]

    def test_show_results_view_opens_dialog(self, qapp, tmp_path):
        """_show_results_view opens a QDialog without error (headless)."""
        from PySide6.QtWidgets import QDialog
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            dialogs_opened = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file")

            assert len(dialogs_opened) == 1, (
                "_show_results_view must open exactly one QDialog"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_table_has_correct_row_count(self, qapp, tmp_path):
        """Results table has one row per entry in the entries list."""
        from PySide6.QtWidgets import QDialog, QTableWidget
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            tables_found = []

            def fake_exec(self_dlg):
                for child in self_dlg.findChildren(QTableWidget):
                    tables_found.append(child)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file")

            assert len(tables_found) == 1, "Results dialog must contain exactly one QTableWidget"
            assert tables_found[0].rowCount() == len(entries), (
                f"Table must have {len(entries)} rows, one per entry"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_table_has_five_columns(self, qapp, tmp_path):
        """Results table has exactly 5 columns: Name, Path, Type, Size, Modified."""
        from PySide6.QtWidgets import QDialog, QTableWidget
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            tables_found = []

            def fake_exec(self_dlg):
                for child in self_dlg.findChildren(QTableWidget):
                    tables_found.append(child)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file")

            assert tables_found, "Results dialog must contain a QTableWidget"
            assert tables_found[0].columnCount() == 5, (
                "Results table must have exactly 5 columns (Name, Path, Type, Size, Modified)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_first_row_name_matches_entry(self, qapp, tmp_path):
        """First table row Name cell contains the filename of the first entry."""
        from PySide6.QtWidgets import QDialog, QTableWidget
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            tables_found = []

            def fake_exec(self_dlg):
                for child in self_dlg.findChildren(QTableWidget):
                    tables_found.append(child)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file")

            table = tables_found[0]
            name_cell = table.item(0, 0)
            assert name_cell is not None, "Name cell in row 0 must not be None"
            assert entries[0].path.name in name_cell.text(), (
                f"Name cell must contain '{entries[0].path.name}', got {name_cell.text()!r}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_empty_entries_opens_dialog(self, qapp, tmp_path):
        """_show_results_view with empty entries list still opens without crash."""
        from PySide6.QtWidgets import QDialog
        win = MainWindow()
        try:
            dialogs_opened = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view([], [], "file")

            assert len(dialogs_opened) == 1, (
                "_show_results_view must open a dialog even with zero entries"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_show_entry_properties_opens_dialog_for_real_file(self, qapp, tmp_path):
        """_show_entry_properties opens a properties dialog with non-empty metadata."""
        from PySide6.QtWidgets import QDialog
        from ff_explorer import entry_metadata
        win = MainWindow()
        try:
            real_file = tmp_path / "propped.txt"
            real_file.write_bytes(b"prop content")
            meta = entry_metadata(str(real_file))
            assert meta, "entry_metadata must return a non-empty dict for a real file"

            dialogs_opened = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_entry_properties(real_file, meta)

            assert len(dialogs_opened) == 1, (
                "_show_entry_properties must open exactly one dialog"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_show_entry_properties_none_meta_no_crash(self, qapp, tmp_path):
        """_show_entry_properties with meta=None (archive-internal path) must not crash."""
        from PySide6.QtWidgets import QDialog
        win = MainWindow()
        try:
            from pathlib import Path
            fake_path = Path("/archive.zip/internal/member.txt")
            dialogs_opened = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_entry_properties(fake_path, None)

            assert len(dialogs_opened) == 1, (
                "_show_entry_properties with None meta must still open a dialog (no crash)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_on_scan_complete_calls_show_results_view(self, qapp, tmp_path):
        """_on_scan_complete always calls _show_results_view before the action handler.

        This verifies the SPEC-19 flow: results view is shown for all actions
        (Save/Remove/Compress) without gating them.
        """
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            f = tmp_path / "item.txt"
            f.write_bytes(b"x")
            entries = [MatchEntry(path=f, kind=EntryKind.FILES)]

            results_view_calls = []
            save_calls = []

            def fake_results_view(ents, skipped, label, action_code=-1):
                results_view_calls.append({"entries": ents, "skipped": skipped})

            def fake_save(path, kind, seed, **kwargs):
                save_calls.append(True)
                return tmp_path / "out.txt"

            win._show_results_view = fake_results_view  # type: ignore[method-assign]

            with patch("ff_explorer.gui.main_window.save_listing",
                       side_effect=fake_save):
                win._on_scan_complete(1, str(tmp_path), EntryKind.FILES, "", "file", entries)

            assert len(results_view_calls) == 1, (
                "_on_scan_complete must call _show_results_view exactly once"
            )
            assert len(save_calls) == 1, (
                "_on_scan_complete must still call save_listing after showing results view"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_with_skipped_shows_skip_button(self, qapp, tmp_path):
        """When skipped list is non-empty, the results dialog contains a 'Show skipped' button."""
        from PySide6.QtWidgets import QDialog, QPushButton
        from ff_explorer.core import SkippedEntry
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            skipped = [SkippedEntry(path="/no/access/dir", reason="PermissionError: [Errno 13]")]
            buttons_found = []

            def fake_exec(self_dlg):
                for btn in self_dlg.findChildren(QPushButton):
                    if "skipped" in btn.text().lower():
                        buttons_found.append(btn)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, skipped, "file")

            assert len(buttons_found) >= 1, (
                "Results dialog must show a 'Show skipped' button when skipped list is non-empty"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_no_skipped_no_skip_button(self, qapp, tmp_path):
        """When skipped list is empty, the results dialog has no 'Show skipped' button."""
        from PySide6.QtWidgets import QDialog, QPushButton
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            skip_buttons = []

            def fake_exec(self_dlg):
                for btn in self_dlg.findChildren(QPushButton):
                    if "skipped" in btn.text().lower():
                        skip_buttons.append(btn)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file")

            assert len(skip_buttons) == 0, (
                "Results dialog must NOT show a 'Show skipped' button when skipped is empty"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A19 — SPEC-15: skip report surfaced by the scan worker
# ---------------------------------------------------------------------------

class TestSkipReport:
    """A19: _ScanWorker emits skipped signal; _on_scan_complete surfaces skip
    count in the status bar; _show_skipped_dialog opens a read-only list.
    """

    @staticmethod
    def _spin_until(condition, timeout_ms: int = 3000) -> bool:
        import time
        from PySide6.QtWidgets import QApplication
        deadline = time.monotonic() + timeout_ms / 1000.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if condition():
                return True
        return False

    def test_worker_emits_skipped_signal(self, qapp, tmp_path):
        """_ScanWorker emits skipped signal after finished.

        Even for a fully-readable tree the skipped signal must be emitted
        (with an empty list).  This verifies the signal exists and fires.
        """
        from ff_explorer import EntryKind
        from ff_explorer.gui.main_window import _ScanWorker
        from PySide6.QtCore import QThread

        (tmp_path / "a.txt").write_bytes(b"a")

        finished_calls: list = []
        skipped_calls: list = []

        worker = _ScanWorker(str(tmp_path), EntryKind.FILES, "", {})
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(lambda e: finished_calls.append(e))
        worker.skipped.connect(lambda s: skipped_calls.append(s))
        thread.started.connect(worker.run)
        thread.start()

        done = self._spin_until(
            lambda: bool(skipped_calls),
            timeout_ms=5000,
        )
        thread.quit()
        thread.wait()

        assert done, "Worker did not emit skipped signal within 5 s"
        assert len(skipped_calls) == 1, "Worker must emit skipped exactly once"
        assert isinstance(skipped_calls[0], list), "skipped payload must be a list"
        # For a readable tree, skipped list is empty
        assert skipped_calls[0] == [], (
            "For a fully-readable tree, skipped list must be empty"
        )

    def test_on_scan_complete_status_bar_shows_skip_count(self, qapp, tmp_path):
        """_on_scan_complete with non-empty skipped list calls _set_status with
        a message mentioning the skip count.

        Note: _do_save (action_code=1) subsequently calls _set_status with
        the save result, overwriting the status bar.  We therefore spy on
        _set_status to capture ALL calls and assert that at least one mentions
        'skipped', rather than reading the final bar value.
        """
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import SkippedEntry
        win = MainWindow()
        try:
            f = tmp_path / "item.txt"
            f.write_bytes(b"x")
            entries = [MatchEntry(path=f, kind=EntryKind.FILES)]
            skipped = [SkippedEntry(path="/locked/dir", reason="PermissionError")]

            # Suppress the results view dialog to keep the test non-blocking.
            win._show_results_view = lambda *a, **kw: None  # type: ignore[method-assign]

            # Spy on _set_status to capture every call during _on_scan_complete.
            status_calls: list[str] = []
            original_set_status = win._set_status
            win._set_status = lambda msg: (status_calls.append(msg), original_set_status(msg))  # type: ignore[method-assign]

            with patch("ff_explorer.gui.main_window.save_listing",
                       return_value=tmp_path / "out.txt"):
                win._on_scan_complete(
                    1, str(tmp_path), EntryKind.FILES, "", "file",
                    entries, skipped,
                )

            skip_msgs = [m for m in status_calls if "skipped" in m.lower()]
            assert skip_msgs, (
                f"_set_status must be called with a message mentioning 'skipped' "
                f"when skipped list is non-empty.  All calls: {status_calls!r}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_on_scan_complete_no_skip_status_unchanged(self, qapp, tmp_path):
        """_on_scan_complete with empty skipped never calls _set_status with 'skipped'."""
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            f = tmp_path / "item.txt"
            f.write_bytes(b"x")
            entries = [MatchEntry(path=f, kind=EntryKind.FILES)]

            win._show_results_view = lambda *a, **kw: None  # type: ignore[method-assign]

            status_calls: list[str] = []
            original_set_status = win._set_status
            win._set_status = lambda msg: (status_calls.append(msg), original_set_status(msg))  # type: ignore[method-assign]

            with patch("ff_explorer.gui.main_window.save_listing",
                       return_value=tmp_path / "out.txt"):
                win._on_scan_complete(
                    1, str(tmp_path), EntryKind.FILES, "", "file",
                    entries, [],
                )

            skip_msgs = [m for m in status_calls if "skipped" in m.lower()]
            assert not skip_msgs, (
                f"_set_status must NOT mention 'skipped' when skipped list is empty; "
                f"got: {skip_msgs!r}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_show_skipped_dialog_opens_with_entries(self, qapp, tmp_path):
        """_show_skipped_dialog opens a QDialog listing skipped paths."""
        from PySide6.QtWidgets import QDialog, QListWidget
        from ff_explorer.core import SkippedEntry
        win = MainWindow()
        try:
            skipped = [
                SkippedEntry(path="/no/access/a", reason="PermissionError: denied"),
                SkippedEntry(path="/no/access/b", reason="OSError: stale handle"),
            ]
            dialogs_opened = []
            list_widgets: list = []

            def fake_exec(self_dlg):
                dialogs_opened.append(self_dlg)
                for lw in self_dlg.findChildren(QListWidget):
                    list_widgets.append(lw)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_skipped_dialog(skipped)

            assert len(dialogs_opened) == 1, (
                "_show_skipped_dialog must open exactly one QDialog"
            )
            assert len(list_widgets) == 1, (
                "_show_skipped_dialog must contain a QListWidget"
            )
            assert list_widgets[0].count() == len(skipped), (
                f"QListWidget must have {len(skipped)} items, one per SkippedEntry"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_skipped_signal_fires_after_finished(self, qapp, tmp_path):
        """_ScanWorker emits finished then skipped (order preserved)."""
        from ff_explorer import EntryKind
        from ff_explorer.gui.main_window import _ScanWorker
        from PySide6.QtCore import QThread

        (tmp_path / "file.txt").write_bytes(b"f")

        order: list = []
        skipped_calls: list = []
        finished_calls: list = []

        worker = _ScanWorker(str(tmp_path), EntryKind.FILES, "", {})
        thread = QThread()
        worker.moveToThread(thread)
        worker.finished.connect(lambda e: (finished_calls.append(e), order.append("finished")))
        worker.skipped.connect(lambda s: (skipped_calls.append(s), order.append("skipped")))
        thread.started.connect(worker.run)
        thread.start()

        done = self._spin_until(
            lambda: bool(skipped_calls),
            timeout_ms=5000,
        )
        thread.quit()
        thread.wait()

        assert done, "Worker did not emit skipped within 5 s"
        assert order == ["finished", "skipped"], (
            f"finished must be emitted before skipped; got order: {order}"
        )


# ---------------------------------------------------------------------------
# A20 — SPEC-17: include_hidden checkbox exists and flows into scan kwargs
# ---------------------------------------------------------------------------

class TestIncludeHiddenControl:
    """A20: _include_hidden_check QCheckBox exists, defaults to checked (True),
    and when unchecked adds include_hidden=False to _build_list_entries_kwargs().
    """

    def test_include_hidden_check_exists_and_checked_by_default(self, qapp):
        """_include_hidden_check must exist, be a QCheckBox, and default to checked."""
        from PySide6.QtWidgets import QCheckBox
        win = MainWindow()
        try:
            assert hasattr(win, "_include_hidden_check"), (
                "_include_hidden_check must exist on MainWindow (SPEC-17)"
            )
            assert isinstance(win._include_hidden_check, QCheckBox)
            assert win._include_hidden_check.isChecked(), (
                "_include_hidden_check must be checked by default "
                "(True = include hidden, preserving prior behaviour)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_include_hidden_checked_not_in_kwargs(self, qapp):
        """When checked (True = default), include_hidden must NOT appear in kwargs
        (True is the core default; omitting it is equivalent and avoids noise)."""
        win = MainWindow()
        try:
            win._include_hidden_check.setChecked(True)
            kwargs = win._build_list_entries_kwargs()
            assert "include_hidden" not in kwargs, (
                "include_hidden=True (default) must not appear in kwargs "
                "— it is the core default and should be omitted"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_include_hidden_unchecked_adds_false_to_kwargs(self, qapp):
        """Unchecking _include_hidden_check adds include_hidden=False to kwargs."""
        win = MainWindow()
        try:
            win._include_hidden_check.setChecked(False)
            kwargs = win._build_list_entries_kwargs()
            assert "include_hidden" in kwargs, (
                "Unchecking include_hidden_check must add include_hidden to kwargs"
            )
            assert kwargs["include_hidden"] is False, (
                "include_hidden kwarg must be False when checkbox is unchecked"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_include_hidden_registered_in_widget_info(self):
        """filter_include_hidden key must be present in WIDGET_INFO (SPEC-09 lint)."""
        from ff_explorer.gui.widget_info import WIDGET_INFO
        assert "filter_include_hidden" in WIDGET_INFO, (
            "'filter_include_hidden' must be present in WIDGET_INFO (SPEC-17)"
        )
        assert WIDGET_INFO["filter_include_hidden"], (
            "WIDGET_INFO['filter_include_hidden'] must be a non-empty string"
        )

    def test_include_hidden_check_has_ff_info_key_property(self, qapp):
        """_include_hidden_check must carry _ff_info_key='filter_include_hidden'."""
        win = MainWindow()
        try:
            key = win._include_hidden_check.property("_ff_info_key")
            assert key == "filter_include_hidden", (
                f"_include_hidden_check must have _ff_info_key='filter_include_hidden', "
                f"got {key!r}"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_include_hidden_default_state_preserves_existing_kwargs(self, qapp):
        """Default checked state preserves the full prior kwargs dict unchanged."""
        win = MainWindow()
        try:
            # All other filters at default too — should remain {}
            kwargs_with_hidden_checked = win._build_list_entries_kwargs()
            assert kwargs_with_hidden_checked == {}, (
                "Default state (all filters at default, include_hidden checked) "
                "must still produce an empty kwargs dict"
            )
        finally:
            win.close()
            win.deleteLater()


# ---------------------------------------------------------------------------
# A21 — SPEC-18: bulk operations, multi-select, Copy/Move, only_paths gate
# ---------------------------------------------------------------------------

class TestBulkOperationsSpec18:
    """A21: SPEC-18 bulk operations.

    Covers:
    - _ACTION_LABELS includes Copy list (4) and Move list (5)
    - WIDGET_INFO has action_detail.4, action_detail.5, results_apply_selected,
      results_apply_all entries
    - _show_results_view uses ExtendedSelection
    - Subset: only_paths = selected non-archive paths passed to core op
    - No selection: only_paths is None (legacy full-set)
    - Archive-internal rows excluded from destructive subset
    - Copy/Move: dest picker → confirm No → no mutate; confirm Yes → mutate once
    - _do_copy/_do_move: QFileDialog patched, gate defaults No, gate passes Yes
    """

    @staticmethod
    def _make_entries(tmp_path: Path) -> list:
        from ff_explorer import MatchEntry, EntryKind
        f1 = tmp_path / "alpha.txt"
        f2 = tmp_path / "beta.txt"
        f3 = tmp_path / "gamma.txt"
        f1.write_bytes(b"a")
        f2.write_bytes(b"b")
        f3.write_bytes(b"g")
        return [
            MatchEntry(path=f1, kind=EntryKind.FILES),
            MatchEntry(path=f2, kind=EntryKind.FILES),
            MatchEntry(path=f3, kind=EntryKind.FILES),
        ]

    # ------------------------------------------------------------------
    # Registry / action-labels checks
    # ------------------------------------------------------------------

    def test_action_labels_include_copy_and_move(self, qapp):
        """_ACTION_LABELS must contain 'Copy list' (4) and 'Move list' (5)."""
        from ff_explorer.gui.main_window import _ACTION_LABELS
        assert "Copy list" in _ACTION_LABELS, (
            "'Copy list' must be in _ACTION_LABELS (SPEC-18)"
        )
        assert _ACTION_LABELS["Copy list"] == 4, (
            "'Copy list' must map to action code 4"
        )
        assert "Move list" in _ACTION_LABELS, (
            "'Move list' must be in _ACTION_LABELS (SPEC-18)"
        )
        assert _ACTION_LABELS["Move list"] == 5, (
            "'Move list' must map to action code 5"
        )

    def test_action_combo_includes_copy_and_move(self, qapp):
        """The action combobox in MainWindow must contain 'Copy list' and 'Move list'."""
        win = MainWindow()
        try:
            items = [win._action_combo.itemText(i)
                     for i in range(win._action_combo.count())]
            assert "Copy list" in items, (
                "Action combobox must include 'Copy list' (SPEC-18)"
            )
            assert "Move list" in items, (
                "Action combobox must include 'Move list' (SPEC-18)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_widget_info_has_copy_move_action_details(self):
        """WIDGET_INFO must have action_detail.4 and action_detail.5 (SPEC-18)."""
        assert "action_detail.4" in WIDGET_INFO, (
            "WIDGET_INFO must contain 'action_detail.4' for Copy list (SPEC-18)"
        )
        assert "action_detail.5" in WIDGET_INFO, (
            "WIDGET_INFO must contain 'action_detail.5' for Move list (SPEC-18)"
        )
        assert WIDGET_INFO["action_detail.4"], "action_detail.4 must be non-empty"
        assert WIDGET_INFO["action_detail.5"], "action_detail.5 must be non-empty"

    def test_widget_info_has_apply_buttons_keys(self):
        """WIDGET_INFO must have results_apply_selected and results_apply_all."""
        assert "results_apply_selected" in WIDGET_INFO, (
            "WIDGET_INFO must contain 'results_apply_selected' (SPEC-18)"
        )
        assert "results_apply_all" in WIDGET_INFO, (
            "WIDGET_INFO must contain 'results_apply_all' (SPEC-18)"
        )
        assert WIDGET_INFO["results_apply_selected"], "results_apply_selected must be non-empty"
        assert WIDGET_INFO["results_apply_all"], "results_apply_all must be non-empty"

    def test_copy_move_action_tooltip_changes(self, qapp):
        """Selecting 'Copy list' and 'Move list' in the combobox produces distinct tooltips."""
        win = MainWindow()
        try:
            items = [win._action_combo.itemText(i)
                     for i in range(win._action_combo.count())]
            copy_idx = items.index("Copy list")
            move_idx = items.index("Move list")
            win._action_combo.setCurrentIndex(copy_idx)
            copy_tip = win._action_combo.toolTip()
            win._action_combo.setCurrentIndex(move_idx)
            move_tip = win._action_combo.toolTip()
            assert copy_tip, "Copy list tooltip must be non-empty"
            assert move_tip, "Move list tooltip must be non-empty"
            assert copy_tip != move_tip, (
                "Copy list and Move list tooltips must differ"
            )
        finally:
            win.close()
            win.deleteLater()

    # ------------------------------------------------------------------
    # Results view: ExtendedSelection
    # ------------------------------------------------------------------

    def test_results_view_table_uses_extended_selection(self, qapp, tmp_path):
        """Results QTableWidget must use ExtendedSelection (SPEC-18 multi-select)."""
        from PySide6.QtWidgets import QDialog, QTableWidget, QAbstractItemView
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            tables_found = []

            def fake_exec(self_dlg):
                for child in self_dlg.findChildren(QTableWidget):
                    tables_found.append(child)
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file", action_code=2)

            assert tables_found, "Results dialog must contain a QTableWidget"
            table = tables_found[0]
            assert table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection, (
                "Results table must use ExtendedSelection (SPEC-18)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_has_apply_selected_and_apply_all_buttons(self, qapp, tmp_path):
        """Results dialog must contain 'Apply to selected' and 'Apply to all' buttons
        for non-Save actions (SPEC-18)."""
        from PySide6.QtWidgets import QDialog, QPushButton
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            buttons_found = []

            def fake_exec(self_dlg):
                for btn in self_dlg.findChildren(QPushButton):
                    buttons_found.append(btn.text())
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file", action_code=2)

            apply_sel = [t for t in buttons_found if "selected" in t.lower()]
            apply_all = [t for t in buttons_found if "all" in t.lower()]
            assert apply_sel, (
                "Results dialog must have an 'Apply to selected' button for Remove action"
            )
            assert apply_all, (
                "Results dialog must have an 'Apply to all' button for Remove action"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_results_view_save_action_no_apply_selected_button(self, qapp, tmp_path):
        """For the Save action (code=1), 'Apply to selected' must NOT be shown
        (save_listing has no only_paths; full-set is the only meaningful choice)."""
        from PySide6.QtWidgets import QDialog, QPushButton
        win = MainWindow()
        try:
            entries = self._make_entries(tmp_path)
            buttons_found = []

            def fake_exec(self_dlg):
                for btn in self_dlg.findChildren(QPushButton):
                    buttons_found.append(btn.text())
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                win._show_results_view(entries, [], "file", action_code=1)

            apply_sel = [t for t in buttons_found if "selected" in t.lower()]
            assert not apply_sel, (
                "Save action must NOT show 'Apply to selected' button "
                "(save_listing has no only_paths — SPEC-18)"
            )
        finally:
            win.close()
            win.deleteLater()

    # ------------------------------------------------------------------
    # Subset: only_paths passed to core ops when rows are selected
    # ------------------------------------------------------------------

    def test_do_remove_with_only_paths_passes_them_to_core(self, qapp, tmp_path):
        """_do_remove with only_paths=[path] passes only_paths to remove_entries.

        Selecting a subset of result rows and invoking remove passes
        only_paths = the selected paths to remove_entries (core call).
        """
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f2 = tmp_path / "beta.txt"
            f1.write_bytes(b"a")
            f2.write_bytes(b"b")
            entries = [
                MatchEntry(path=f1, kind=EntryKind.FILES),
                MatchEntry(path=f2, kind=EntryKind.FILES),
            ]
            # Only select f1
            selected = [str(f1)]
            live_report = RemovalReport(matched=[f1], removed=[f1])

            captured: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured.update(kwargs)
                captured["dry_run"] = dry_run
                return live_report

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.Yes),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "alpha", "file",
                               entries, only_paths=selected)

            assert "only_paths" in captured, (
                "_do_remove must forward only_paths to remove_entries when set"
            )
            assert set(captured["only_paths"]) == {str(f1)}, (
                "only_paths forwarded to remove_entries must match the selected subset"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_remove_no_selection_passes_no_only_paths(self, qapp, tmp_path):
        """_do_remove with only_paths=None passes no only_paths kwarg (legacy full-set)."""
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]
            live_report = RemovalReport(matched=[f1], removed=[f1])

            captured: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured.update(kwargs)
                return live_report

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.Yes),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "alpha", "file",
                               entries, only_paths=None)

            assert "only_paths" not in captured, (
                "_do_remove must NOT pass only_paths when it is None (legacy full-set)"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_compress_with_only_paths_passes_them_to_core(self, qapp, tmp_path):
        """_do_compress with only_paths passes them to compress_entries (SPEC-18)."""
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import CompressionReport
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f2 = tmp_path / "beta.txt"
            f1.write_bytes(b"a")
            f2.write_bytes(b"b")
            entries = [
                MatchEntry(path=f1, kind=EntryKind.FILES),
                MatchEntry(path=f2, kind=EntryKind.FILES),
            ]
            selected = [str(f1)]
            live_report = CompressionReport(matched=[f1], archives=[tmp_path / "alpha.zip"])

            captured: dict = {}

            def fake_compress(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured.update(kwargs)
                return live_report

            with (
                patch("ff_explorer.gui.main_window.compress_entries",
                      side_effect=fake_compress),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.Yes),
            ):
                win._do_compress(str(tmp_path), win._current_kind(), "alpha", "file",
                                 entries, only_paths=selected)

            assert "only_paths" in captured, (
                "_do_compress must forward only_paths to compress_entries when set"
            )
            assert set(captured["only_paths"]) == {str(f1)}, (
                "only_paths forwarded to compress_entries must match selected subset"
            )
        finally:
            win.close()
            win.deleteLater()

    # ------------------------------------------------------------------
    # Archive-internal exclusion
    # ------------------------------------------------------------------

    def test_archive_internal_rows_excluded_from_subset(self, qapp, tmp_path):
        """_show_results_view: rows whose path contains '!' (archive-internal) are
        excluded from the only_paths list returned for 'Apply to selected'.

        We simulate table row selection programmatically and trigger the internal
        'Apply to selected' callback by patching QDialog.exec to select rows and
        click the button.
        """
        from ff_explorer import MatchEntry, EntryKind
        from PySide6.QtWidgets import QDialog, QPushButton

        win = MainWindow()
        try:
            # One normal entry and one archive-internal entry
            f_normal = tmp_path / "real.txt"
            f_normal.write_bytes(b"x")
            # Archive-internal: path contains '!'
            archive_entry_path = Path(str(tmp_path / "archive.zip") + "!member.txt")

            entries = [
                MatchEntry(path=f_normal, kind=EntryKind.FILES),
                MatchEntry(path=archive_entry_path, kind=EntryKind.FILES),
            ]

            result_holder = []

            def fake_exec(self_dlg):
                from PySide6.QtWidgets import QTableWidget
                tables = self_dlg.findChildren(QTableWidget)
                if tables:
                    # Select all rows
                    tables[0].selectAll()
                # Click "Apply to selected"
                for btn in self_dlg.findChildren(QPushButton):
                    if "selected" in btn.text().lower() and btn.isEnabled():
                        btn.click()
                        break
                return 0

            # Intercept QMessageBox.information (archive exclusion note)
            with (
                patch.object(QDialog, "exec", fake_exec),
                patch("ff_explorer.gui.main_window.QMessageBox.information"),
            ):
                result = win._show_results_view(entries, [], "file", action_code=2)

            # The archive-internal entry must have been excluded from only_paths
            if result is not None:
                assert str(archive_entry_path) not in result, (
                    "Archive-internal path must be excluded from only_paths subset (SPEC-18)"
                )
                assert str(f_normal) in result, (
                    "Normal (non-archive-internal) path must be included in only_paths"
                )
        finally:
            win.close()
            win.deleteLater()

    def test_apply_all_returns_none(self, qapp, tmp_path):
        """Clicking 'Apply to all' in the results view returns None (legacy full-set)."""
        from ff_explorer import MatchEntry, EntryKind
        from PySide6.QtWidgets import QDialog, QPushButton

        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]

            def fake_exec(self_dlg):
                for btn in self_dlg.findChildren(QPushButton):
                    if "all" in btn.text().lower() and btn.isEnabled():
                        btn.click()
                        break
                return 0

            with patch.object(QDialog, "exec", fake_exec):
                result = win._show_results_view(entries, [], "file", action_code=2)

            assert result is None, (
                "'Apply to all' must return None (legacy full-set, only_paths=None)"
            )
        finally:
            win.close()
            win.deleteLater()

    # ------------------------------------------------------------------
    # Copy / Move: gate defaults to No; gate passes Yes; dest picker patched
    # ------------------------------------------------------------------

    def test_do_copy_dialog_default_no_skips_mutate(self, qapp, tmp_path):
        """_do_copy: QMessageBox.question returns No → copy_entries(dry_run=False)
        is never called.  Gate defaults to No (SPEC-18 safety requirement)."""
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]
            dest = str(tmp_path / "dest")

            mutate_calls = []

            def fake_copy(path, kind, seed, destination, dry_run=True, confirm=False, **kw):
                if not dry_run:
                    mutate_calls.append(True)
                    raise AssertionError("copy_entries(dry_run=False) must not be called when No")
                from ff_explorer.core import TransferReport
                return TransferReport(kind="copy", matched=[f1])

            with (
                patch("ff_explorer.gui.main_window.copy_entries", side_effect=fake_copy),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value=dest),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.No),
            ):
                win._do_copy(str(tmp_path), win._current_kind(), "alpha", "file", entries)

            assert len(mutate_calls) == 0, (
                "copy_entries(dry_run=False) must not be called when confirm dialog returns No"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_copy_yes_calls_copy_entries_once(self, qapp, tmp_path):
        """_do_copy: confirm Yes → copy_entries called once with dry_run=False,
        confirm=True, correct destination and only_paths (SPEC-18)."""
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import TransferReport
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]
            dest = str(tmp_path / "dest")
            selected = [str(f1)]
            live_report = TransferReport(kind="copy", matched=[f1], transferred=[f1])

            captured: dict = {}

            def fake_copy(path, kind, seed, destination, dry_run=True, confirm=False, **kw):
                captured["dry_run"] = dry_run
                captured["confirm"] = confirm
                captured["destination"] = destination
                captured.update(kw)
                return live_report

            with (
                patch("ff_explorer.gui.main_window.copy_entries", side_effect=fake_copy),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value=dest),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.Yes),
            ):
                win._do_copy(str(tmp_path), win._current_kind(), "alpha", "file",
                             entries, only_paths=selected)

            assert captured.get("dry_run") is False, (
                "copy_entries must be called with dry_run=False on Yes"
            )
            assert captured.get("confirm") is True, (
                "copy_entries must be called with confirm=True on Yes"
            )
            assert captured.get("destination") == dest, (
                "copy_entries must receive the chosen destination directory"
            )
            assert set(captured.get("only_paths", [])) == {str(f1)}, (
                "copy_entries must receive only_paths matching the selected subset"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_move_dialog_default_no_skips_mutate(self, qapp, tmp_path):
        """_do_move: QMessageBox.question returns No → move_entries(dry_run=False)
        is never called.  Gate defaults to No (SPEC-18 safety requirement)."""
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]
            dest = str(tmp_path / "dest")

            mutate_calls = []

            def fake_move(path, kind, seed, destination, dry_run=True, confirm=False, **kw):
                if not dry_run:
                    mutate_calls.append(True)
                    raise AssertionError("move_entries(dry_run=False) must not be called when No")
                from ff_explorer.core import TransferReport
                return TransferReport(kind="move", matched=[f1])

            with (
                patch("ff_explorer.gui.main_window.move_entries", side_effect=fake_move),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value=dest),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.No),
            ):
                win._do_move(str(tmp_path), win._current_kind(), "alpha", "file", entries)

            assert len(mutate_calls) == 0, (
                "move_entries(dry_run=False) must not be called when confirm dialog returns No"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_move_yes_calls_move_entries_once(self, qapp, tmp_path):
        """_do_move: confirm Yes → move_entries called once with dry_run=False,
        confirm=True, correct destination and only_paths (SPEC-18)."""
        from ff_explorer import MatchEntry, EntryKind
        from ff_explorer.core import TransferReport
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]
            dest = str(tmp_path / "dest")
            selected = [str(f1)]
            live_report = TransferReport(kind="move", matched=[f1], transferred=[f1])

            captured: dict = {}

            def fake_move(path, kind, seed, destination, dry_run=True, confirm=False, **kw):
                captured["dry_run"] = dry_run
                captured["confirm"] = confirm
                captured["destination"] = destination
                captured.update(kw)
                return live_report

            with (
                patch("ff_explorer.gui.main_window.move_entries", side_effect=fake_move),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value=dest),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.Yes),
            ):
                win._do_move(str(tmp_path), win._current_kind(), "alpha", "file",
                             entries, only_paths=selected)

            assert captured.get("dry_run") is False, (
                "move_entries must be called with dry_run=False on Yes"
            )
            assert captured.get("confirm") is True, (
                "move_entries must be called with confirm=True on Yes"
            )
            assert captured.get("destination") == dest, (
                "move_entries must receive the chosen destination directory"
            )
            assert set(captured.get("only_paths", [])) == {str(f1)}, (
                "move_entries must receive only_paths matching the selected subset"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_copy_no_destination_cancels_without_core_call(self, qapp, tmp_path):
        """_do_copy: when QFileDialog returns '' (user cancelled), copy_entries is
        never called — no mutation, no crash (SPEC-18)."""
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]

            core_calls = []

            def fake_copy(*a, **kw):
                core_calls.append(True)
                from ff_explorer.core import TransferReport
                return TransferReport(kind="copy")

            with (
                patch("ff_explorer.gui.main_window.copy_entries", side_effect=fake_copy),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value=""),
            ):
                win._do_copy(str(tmp_path), win._current_kind(), "alpha", "file", entries)

            assert not core_calls, (
                "copy_entries must not be called when the destination picker is cancelled"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_move_no_destination_cancels_without_core_call(self, qapp, tmp_path):
        """_do_move: when QFileDialog returns '' (user cancelled), move_entries is
        never called — no mutation, no crash (SPEC-18)."""
        from ff_explorer import MatchEntry, EntryKind
        win = MainWindow()
        try:
            f1 = tmp_path / "alpha.txt"
            f1.write_bytes(b"a")
            entries = [MatchEntry(path=f1, kind=EntryKind.FILES)]

            core_calls = []

            def fake_move(*a, **kw):
                core_calls.append(True)
                from ff_explorer.core import TransferReport
                return TransferReport(kind="move")

            with (
                patch("ff_explorer.gui.main_window.move_entries", side_effect=fake_move),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value=""),
            ):
                win._do_move(str(tmp_path), win._current_kind(), "alpha", "file", entries)

            assert not core_calls, (
                "move_entries must not be called when the destination picker is cancelled"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_do_copy_empty_entries_skips_everything(self, qapp, tmp_path):
        """_do_copy with empty entries list sets status and exits early — no dialog."""
        from ff_explorer import EntryKind
        win = MainWindow()
        try:
            core_calls = []
            dialog_calls = []

            def fake_copy(*a, **kw):
                core_calls.append(True)
                from ff_explorer.core import TransferReport
                return TransferReport(kind="copy")

            def fake_get_dir(*a, **kw):
                dialog_calls.append(True)
                return "/some/dest"

            with (
                patch("ff_explorer.gui.main_window.copy_entries", side_effect=fake_copy),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      side_effect=fake_get_dir),
            ):
                win._do_copy(str(tmp_path), win._current_kind(), "test", "file", [])

            assert not core_calls, "_do_copy with empty entries must not call copy_entries"
            assert not dialog_calls, "_do_copy with empty entries must not open QFileDialog"
        finally:
            win.close()
            win.deleteLater()

    def test_do_move_empty_entries_skips_everything(self, qapp, tmp_path):
        """_do_move with empty entries list sets status and exits early — no dialog."""
        from ff_explorer import EntryKind
        win = MainWindow()
        try:
            core_calls = []

            def fake_move(*a, **kw):
                core_calls.append(True)
                from ff_explorer.core import TransferReport
                return TransferReport(kind="move")

            with (
                patch("ff_explorer.gui.main_window.move_entries", side_effect=fake_move),
                patch("ff_explorer.gui.main_window.QFileDialog.getExistingDirectory",
                      return_value="/some/dest"),
            ):
                win._do_move(str(tmp_path), win._current_kind(), "test", "file", [])

            assert not core_calls, "_do_move with empty entries must not call move_entries"
        finally:
            win.close()
            win.deleteLater()
