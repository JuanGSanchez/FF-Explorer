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

    def _make_remove_preview(self, tmp_path: Path):
        """Return a fake dry-run preview report with one matched entry."""
        from ff_explorer.core import RemovalReport
        fake_path = tmp_path / "target.txt"
        fake_path.write_text("x")
        report = RemovalReport(matched=[fake_path])
        return report

    def test_remove_dialog_default_no_skips_destructive_call(self, qapp, tmp_path):
        """
        _do_remove: when QMessageBox.question returns No, the live
        remove_entries(dry_run=False, confirm=True) is never called.
        """
        win = MainWindow()
        try:
            preview_report = self._make_remove_preview(tmp_path)

            calls = []

            def fake_remove(path, kind, seed, dry_run=True, confirm=False):
                calls.append({"dry_run": dry_run, "confirm": confirm})
                if dry_run:
                    return preview_report
                raise AssertionError("Destructive remove must not be called when user clicks No")

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "target", "file")

            # Dry-run preview call must have occurred; destructive call must NOT.
            dry_run_calls = [c for c in calls if c["dry_run"]]
            destructive_calls = [c for c in calls if not c["dry_run"]]
            assert len(dry_run_calls) == 1, "Expected exactly one dry-run preview call"
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
        """
        win = MainWindow()
        try:
            from ff_explorer.core import CompressionReport
            fake_path = tmp_path / "target_folder"
            fake_path.mkdir()
            preview_report = CompressionReport(matched=[fake_path])

            calls = []

            def fake_compress(path, kind, seed, dry_run=True, confirm=False):
                calls.append({"dry_run": dry_run, "confirm": confirm})
                if dry_run:
                    return preview_report
                raise AssertionError("Destructive compress must not be called when user clicks No")

            with (
                patch("ff_explorer.gui.main_window.compress_entries", side_effect=fake_compress),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_compress(str(tmp_path), win._current_kind(), "target", "folder")

            dry_run_calls = [c for c in calls if c["dry_run"]]
            destructive_calls = [c for c in calls if not c["dry_run"]]
            assert len(dry_run_calls) == 1, "Expected exactly one dry-run preview call"
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
            from ff_explorer.core import RemovalReport
            fake_path = tmp_path / "yes_target.txt"
            fake_path.write_text("x")
            preview_report = RemovalReport(matched=[fake_path])
            live_report = RemovalReport(matched=[fake_path], removed=[fake_path])

            calls = []

            def fake_remove(path, kind, seed, dry_run=True, confirm=False):
                calls.append({"dry_run": dry_run, "confirm": confirm})
                return preview_report if dry_run else live_report

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "yes_target", "file")

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
    """A6: When Run is triggered with non-default filters, list_entries receives them."""

    def test_run_save_passes_match_mode_regex_to_list_entries(self, qapp, tmp_path):
        """_do_save passes match_mode='regex' to list_entries when Regex is selected."""
        win = MainWindow()
        try:
            idx = [win._match_mode_combo.itemText(i)
                   for i in range(win._match_mode_combo.count())].index("Regex")
            win._match_mode_combo.setCurrentIndex(idx)

            captured = {}

            def fake_list_entries(path, kind, seed, **kwargs):
                captured.update(kwargs)
                return []

            def fake_save_listing(path, kind, seed, **kwargs):
                return tmp_path / "out.txt"

            with (
                patch("ff_explorer.gui.main_window.list_entries",
                      side_effect=fake_list_entries),
                patch("ff_explorer.gui.main_window.save_listing",
                      side_effect=fake_save_listing),
            ):
                win._do_save(str(tmp_path), win._current_kind(), ".*", "file")

            assert captured.get("match_mode") == "regex", (
                "_do_save must pass match_mode='regex' to list_entries "
                "when Regex mode is selected"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_run_save_passes_case_insensitive_when_unchecked(self, qapp, tmp_path):
        """_do_save passes case_sensitive=False to save_listing and list_entries."""
        win = MainWindow()
        try:
            win._case_sensitive_check.setChecked(False)

            save_kwargs: dict = {}
            list_kwargs: dict = {}

            def fake_save_listing(path, kind, seed, **kwargs):
                save_kwargs.update(kwargs)
                return tmp_path / "out.txt"

            def fake_list_entries(path, kind, seed, **kwargs):
                list_kwargs.update(kwargs)
                return []

            with (
                patch("ff_explorer.gui.main_window.save_listing",
                      side_effect=fake_save_listing),
                patch("ff_explorer.gui.main_window.list_entries",
                      side_effect=fake_list_entries),
            ):
                win._do_save(str(tmp_path), win._current_kind(), "test", "file")

            assert save_kwargs.get("case_sensitive") is False, (
                "case_sensitive=False must be passed to save_listing"
            )
            assert list_kwargs.get("case_sensitive") is False, (
                "case_sensitive=False must be passed to list_entries"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_run_save_default_filters_no_extra_kwargs(self, qapp, tmp_path):
        """_do_save with default filters passes no extra kwargs to save_listing."""
        win = MainWindow()
        try:
            save_kwargs: dict = {}

            def fake_save_listing(path, kind, seed, **kwargs):
                save_kwargs.update(kwargs)
                return tmp_path / "out.txt"

            def fake_list_entries(path, kind, seed, **kwargs):
                return []

            with (
                patch("ff_explorer.gui.main_window.save_listing",
                      side_effect=fake_save_listing),
                patch("ff_explorer.gui.main_window.list_entries",
                      side_effect=fake_list_entries),
            ):
                win._do_save(str(tmp_path), win._current_kind(), "test", "file")

            assert save_kwargs == {}, (
                "Default filters must produce no extra kwargs to save_listing"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_invalid_regex_surfaced_as_warning_not_crash(self, qapp, tmp_path):
        """An invalid regex raises ValueError from core, shown as QMessageBox.warning."""
        win = MainWindow()
        try:
            idx = [win._match_mode_combo.itemText(i)
                   for i in range(win._match_mode_combo.count())].index("Regex")
            win._match_mode_combo.setCurrentIndex(idx)

            win._path_edit.setText(str(tmp_path))
            win._action_combo.setCurrentIndex(
                list(win._action_combo.itemText(i)
                     for i in range(win._action_combo.count())).index("Save list")
            )
            win._seed_edit.setText("[invalid(")

            warning_shown = []

            def fake_list_entries(path, kind, seed, **kwargs):
                raise ValueError("bad regex: [invalid(")

            def fake_save_listing(path, kind, seed, **kwargs):
                return tmp_path / "out.txt"

            def fake_warning(parent, title, message, *args, **kwargs):
                warning_shown.append({"title": title, "message": message})

            with (
                patch("ff_explorer.gui.main_window.list_entries",
                      side_effect=fake_list_entries),
                patch("ff_explorer.gui.main_window.save_listing",
                      side_effect=fake_save_listing),
                patch("ff_explorer.gui.main_window.QMessageBox.warning",
                      side_effect=fake_warning),
            ):
                win._run()

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
        """_do_remove passes case_sensitive=False to remove_entries when unchecked."""
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            win._case_sensitive_check.setChecked(False)
            fake_path = tmp_path / "target.txt"
            fake_path.write_text("x")
            preview_report = RemovalReport(matched=[fake_path])

            remove_kwargs: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                remove_kwargs.update(kwargs)
                remove_kwargs["dry_run"] = dry_run
                return preview_report

            with (
                patch("ff_explorer.gui.main_window.remove_entries",
                      side_effect=fake_remove),
                patch("ff_explorer.gui.main_window.QMessageBox.question",
                      return_value=QMessageBox.StandardButton.No),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "target", "file")

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
        """ContentSearchUngatedError from core is caught and shown as QMessageBox.warning
        with a clear, friendly message — no crash."""
        from ff_explorer.core import ContentSearchUngatedError as _CSUE
        win = MainWindow()
        try:
            win._path_edit.setText(str(tmp_path))
            action_items = [
                win._action_combo.itemText(i)
                for i in range(win._action_combo.count())
            ]
            win._action_combo.setCurrentIndex(action_items.index("Save list"))
            win._seed_edit.setText("")  # empty seed — list_entries accepts it
            win._content_query_edit.setText("some content")

            warned = []

            def fake_save(path, kind, seed, **kwargs):
                return tmp_path / "out.txt"

            def fake_list(path, kind, seed, **kwargs):
                raise _CSUE()

            def fake_warning(parent, title, msg, *a, **kw):
                warned.append({"title": title, "msg": msg})

            with (
                patch("ff_explorer.gui.main_window.save_listing", side_effect=fake_save),
                patch("ff_explorer.gui.main_window.list_entries", side_effect=fake_list),
                patch("ff_explorer.gui.main_window.QMessageBox.warning",
                      side_effect=fake_warning),
            ):
                win._run()

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
        """_do_remove with versioning checked passes versioning=True to remove_entries."""
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            fake_target = tmp_path / "old_file.txt"
            fake_target.write_text("x")
            preview = RemovalReport(matched=[fake_target])
            live_report = RemovalReport(matched=[fake_target], removed=[fake_target])

            captured_kwargs: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured_kwargs.update(kwargs)
                captured_kwargs["dry_run"] = dry_run
                return preview if dry_run else live_report

            win._versioning_check.setChecked(True)

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.Yes,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "old_file", "file")

            assert captured_kwargs.get("versioning") is True, (
                "_do_remove with versioning checked must pass versioning=True to remove_entries"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_versioning_unchecked_no_versioning_kwarg(self, qapp, tmp_path):
        """_do_remove with versioning unchecked does NOT pass versioning kwarg."""
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            fake_target = tmp_path / "file.txt"
            fake_target.write_text("x")
            preview = RemovalReport(matched=[fake_target])

            captured_kwargs: dict = {}

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                captured_kwargs.update(kwargs)
                return preview

            win._versioning_check.setChecked(False)

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "file", "file")

            assert "versioning" not in captured_kwargs, (
                "_do_remove with unchecked versioning must not pass versioning kwarg"
            )
        finally:
            win.close()
            win.deleteLater()

    def test_versioning_gate_still_defaults_to_no(self, qapp, tmp_path):
        """Even with versioning=True, the confirm dialog must default to No."""
        from ff_explorer.core import RemovalReport
        win = MainWindow()
        try:
            fake_target = tmp_path / "versioned.txt"
            fake_target.write_text("x")
            preview = RemovalReport(matched=[fake_target])

            destructive_calls = []

            def fake_remove(path, kind, seed, dry_run=True, confirm=False, **kwargs):
                if not dry_run:
                    destructive_calls.append(True)
                    raise AssertionError("Must not run destructive when No selected")
                return preview

            win._versioning_check.setChecked(True)

            with (
                patch("ff_explorer.gui.main_window.remove_entries", side_effect=fake_remove),
                patch(
                    "ff_explorer.gui.main_window.QMessageBox.question",
                    return_value=QMessageBox.StandardButton.No,
                ),
            ):
                win._do_remove(str(tmp_path), win._current_kind(), "versioned", "file")

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
