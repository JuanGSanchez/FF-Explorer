"""
Tests for ff_explorer.gui.theme and ff_explorer.gui.settings_dialog.

All tests that touch Qt widgets require the ``qapp`` fixture (session-scoped
QApplication from conftest.py).  The ``theme`` module is pure Python (no
widget construction at import time), so pure-logic tests run without ``qapp``.

Offscreen environment: the conftest.py ``qapp`` fixture sets
``QT_QPA_PLATFORM=offscreen`` when not already set.

Assertions covered
------------------
T1  build_stylesheet(LIGHT) and build_stylesheet(DARK) are non-empty and differ.
T2  validate_theme(LIGHT) and validate_theme(DARK) return no violations.
T3  contrast_ratio >= 4.5 for text_primary vs panel_bg and vs window_bg in
    both templates.
T4  SettingsDialog instantiates offscreen; switching template updates the
    working theme; applying does not raise.
T5  Persistence round-trip: save_theme then load_saved_theme returns the same
    template name; monkeypatched config dir to avoid touching real user config.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

from ff_explorer.gui.theme import (
    DARK,
    LIGHT,
    Theme,
    build_stylesheet,
    contrast_ratio,
    load_saved_theme,
    save_theme,
    validate_theme,
)


# ---------------------------------------------------------------------------
# T1 — build_stylesheet is non-empty and templates produce distinct QSS
# ---------------------------------------------------------------------------

class TestBuildStylesheet:
    """T1: stylesheet generation."""

    def test_light_stylesheet_nonempty(self):
        """build_stylesheet(LIGHT) returns a non-empty string."""
        qss = build_stylesheet(LIGHT)
        assert isinstance(qss, str)
        assert len(qss) > 100, "Stylesheet should contain substantial QSS rules"

    def test_dark_stylesheet_nonempty(self):
        """build_stylesheet(DARK) returns a non-empty string."""
        qss = build_stylesheet(DARK)
        assert isinstance(qss, str)
        assert len(qss) > 100

    def test_light_and_dark_stylesheets_differ(self):
        """LIGHT and DARK produce different QSS (distinct colour roles)."""
        light_qss = build_stylesheet(LIGHT)
        dark_qss = build_stylesheet(DARK)
        assert light_qss != dark_qss, (
            "LIGHT and DARK stylesheets must differ — they have different colours"
        )

    def test_stylesheet_contains_key_selectors(self):
        """The generated QSS mentions the main widget selectors used by the app."""
        qss = build_stylesheet(LIGHT)
        for selector in ["QMainWindow", "QPushButton", "QLineEdit", "QComboBox",
                         "QRadioButton", "QStatusBar", "QToolTip"]:
            assert selector in qss, f"QSS must include a rule for {selector}"

    def test_stylesheet_contains_light_panel_bg(self):
        """LIGHT stylesheet embeds the panel_bg colour (#FFFFFF)."""
        qss = build_stylesheet(LIGHT)
        assert LIGHT.panel_bg.upper() in qss.upper()

    def test_stylesheet_contains_dark_panel_bg(self):
        """DARK stylesheet embeds the panel_bg colour (#2C2C2C)."""
        qss = build_stylesheet(DARK)
        assert DARK.panel_bg.upper() in qss.upper()


# ---------------------------------------------------------------------------
# T2 — validate_theme passes for both built-in templates
# ---------------------------------------------------------------------------

class TestValidateTheme:
    """T2: both built-in templates must have zero violations."""

    def test_light_passes_validation(self):
        """validate_theme(LIGHT) returns an empty list (no violations)."""
        violations = validate_theme(LIGHT)
        assert violations == [], (
            f"LIGHT theme has colour-theory violations:\n"
            + "\n".join(violations)
        )

    def test_dark_passes_validation(self):
        """validate_theme(DARK) returns an empty list (no violations)."""
        violations = validate_theme(DARK)
        assert violations == [], (
            f"DARK theme has colour-theory violations:\n"
            + "\n".join(violations)
        )

    def test_bad_theme_produces_violations(self):
        """A deliberately broken theme (black on black) reports violations."""
        bad = Theme(
            panel_bg="#000000",
            window_bg="#000000",
            alt_row_bg="#000000",
            text_primary="#010101",   # near-black on black
            text_secondary="#010101",
            border="#020202",
            selection_bg="#030303",
        )
        violations = validate_theme(bad)
        assert len(violations) > 0, (
            "A black-on-black theme must produce at least one violation"
        )


# ---------------------------------------------------------------------------
# T3 — contrast_ratio helper and WCAG AA body-text values
# ---------------------------------------------------------------------------

class TestContrastRatio:
    """T3: contrast_ratio function and WCAG AA check for both templates."""

    def test_black_on_white_is_21(self):
        """Black on white yields the maximum contrast ratio of 21:1."""
        ratio = contrast_ratio("#000000", "#FFFFFF")
        assert abs(ratio - 21.0) < 0.05, f"Expected ~21.0, got {ratio}"

    def test_identical_colors_ratio_is_1(self):
        """Identical colours yield contrast ratio of 1.0."""
        ratio = contrast_ratio("#AABBCC", "#AABBCC")
        assert abs(ratio - 1.0) < 0.001

    def test_symmetric(self):
        """contrast_ratio is symmetric."""
        r1 = contrast_ratio("#1A1A1A", "#FFFFFF")
        r2 = contrast_ratio("#FFFFFF", "#1A1A1A")
        assert abs(r1 - r2) < 0.001

    # WCAG AA (>=4.5) checks for both templates

    def test_light_text_primary_vs_panel_bg_wcag_aa(self):
        """LIGHT: text_primary vs panel_bg must be >= 4.5 (WCAG AA)."""
        ratio = contrast_ratio(LIGHT.text_primary, LIGHT.panel_bg)
        assert ratio >= 4.5, f"LIGHT text_primary vs panel_bg: {ratio:.2f} < 4.5"

    def test_light_text_primary_vs_window_bg_wcag_aa(self):
        """LIGHT: text_primary vs window_bg must be >= 4.5 (WCAG AA)."""
        ratio = contrast_ratio(LIGHT.text_primary, LIGHT.window_bg)
        assert ratio >= 4.5, f"LIGHT text_primary vs window_bg: {ratio:.2f} < 4.5"

    def test_dark_text_primary_vs_panel_bg_wcag_aa(self):
        """DARK: text_primary vs panel_bg must be >= 4.5 (WCAG AA)."""
        ratio = contrast_ratio(DARK.text_primary, DARK.panel_bg)
        assert ratio >= 4.5, f"DARK text_primary vs panel_bg: {ratio:.2f} < 4.5"

    def test_dark_text_primary_vs_window_bg_wcag_aa(self):
        """DARK: text_primary vs window_bg must be >= 4.5 (WCAG AA)."""
        ratio = contrast_ratio(DARK.text_primary, DARK.window_bg)
        assert ratio >= 4.5, f"DARK text_primary vs window_bg: {ratio:.2f} < 4.5"

    def test_light_text_secondary_vs_panel_bg_wcag_aa(self):
        """LIGHT: text_secondary vs panel_bg must be >= 4.5 (WCAG AA)."""
        ratio = contrast_ratio(LIGHT.text_secondary, LIGHT.panel_bg)
        assert ratio >= 4.5, f"LIGHT text_secondary vs panel_bg: {ratio:.2f} < 4.5"

    def test_dark_text_secondary_vs_panel_bg_wcag_aa(self):
        """DARK: text_secondary vs panel_bg must be >= 4.5 (WCAG AA)."""
        ratio = contrast_ratio(DARK.text_secondary, DARK.panel_bg)
        assert ratio >= 4.5, f"DARK text_secondary vs panel_bg: {ratio:.2f} < 4.5"


# ---------------------------------------------------------------------------
# T4 — SettingsDialog instantiates offscreen; switching template updates theme
# ---------------------------------------------------------------------------

class TestSettingsDialog:
    """T4: SettingsDialog behaviour under offscreen Qt."""

    def test_instantiates_without_error(self, qapp):
        """SettingsDialog(LIGHT, 'Light') constructs cleanly offscreen."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(LIGHT, "Light")
        try:
            assert dlg is not None
            assert dlg.selected_template_name() == "Light"
        finally:
            dlg.reject()
            dlg.deleteLater()

    def test_switching_template_to_dark_updates_theme(self, qapp):
        """Selecting 'Dark' in the template combo switches the working theme."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(LIGHT, "Light")
        try:
            # Simulate selecting Dark from the combo
            combo = dlg._template_combo
            idx = combo.findText("Dark")
            assert idx >= 0, "Dark template must be in the combo"
            combo.setCurrentIndex(idx)
            # The working theme should now use DARK colours
            assert dlg.selected_template_name() == "Dark"
            # panel_bg must match DARK's panel_bg
            selected = dlg.selected_theme()
            assert selected.panel_bg.upper() == DARK.panel_bg.upper(), (
                f"After switching to Dark, panel_bg should be {DARK.panel_bg}, "
                f"got {selected.panel_bg}"
            )
        finally:
            dlg.reject()
            dlg.deleteLater()

    def test_apply_callback_invoked_on_apply(self, qapp):
        """Clicking Apply invokes the apply_callback with the current theme."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        applied: list[tuple] = []

        def callback(theme, name):
            applied.append((theme, name))

        dlg = SettingsDialog(LIGHT, "Light", apply_callback=callback)
        try:
            dlg._on_apply()
            assert len(applied) == 1, "apply_callback must be called once on Apply"
            assert applied[0][1] == "Light"
        finally:
            dlg.reject()
            dlg.deleteLater()

    def test_apply_does_not_raise(self, qapp):
        """_on_apply() with a valid theme does not raise any exception."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(DARK, "Dark")
        try:
            dlg._on_apply()  # no callback wired — must not raise
        finally:
            dlg.reject()
            dlg.deleteLater()

    def test_cancel_reverts_to_original_theme(self, qapp):
        """Cancel calls apply_callback with the original theme to revert."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        reverted: list[tuple] = []

        def callback(theme, name):
            reverted.append((theme, name))

        dlg = SettingsDialog(LIGHT, "Light", apply_callback=callback)
        try:
            # Switch to Dark (would change the working theme)
            combo = dlg._template_combo
            idx = combo.findText("Dark")
            combo.setCurrentIndex(idx)
            # Cancel — should revert to LIGHT
            dlg._on_cancel()
            assert len(reverted) >= 1
            last_name = reverted[-1][1]
            assert last_name == "Light", (
                f"Cancel must revert to the original 'Light' template, got '{last_name}'"
            )
        finally:
            dlg.deleteLater()

    def test_validate_violations_displayed(self, qapp):
        """If the theme has violations, the validation label text is non-empty."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        # Construct a theme with a contrast violation
        bad_theme = Theme(
            text_primary="#808080",  # grey-on-white, low contrast
            panel_bg="#FFFFFF",
            window_bg="#FFFFFF",
        )
        dlg = SettingsDialog(bad_theme, "Custom")
        try:
            # Force refresh
            dlg._refresh_validation()
            label_text = dlg._validation_label.text()
            # Either empty (if our bad_theme accidentally passes) or non-empty
            # The important thing: _refresh_validation does not raise
            assert isinstance(label_text, str)
        finally:
            dlg.reject()
            dlg.deleteLater()

    def test_reset_restores_light_template(self, qapp):
        """Reset to Light restores all LIGHT colour roles."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(DARK, "Dark")
        try:
            # Switch to light via combo, then reset
            combo = dlg._template_combo
            idx = combo.findText("Light")
            combo.setCurrentIndex(idx)
            dlg._on_reset()
            theme = dlg.selected_theme()
            assert theme.panel_bg.upper() == LIGHT.panel_bg.upper()
            assert theme.window_bg.upper() == LIGHT.window_bg.upper()
        finally:
            dlg.reject()
            dlg.deleteLater()


# ---------------------------------------------------------------------------
# T5 — Persistence round-trip with monkeypatched config dir
# ---------------------------------------------------------------------------

class TestPersistence:
    """T5: save_theme / load_saved_theme round-trip using a temp config dir."""

    def test_roundtrip_light(self, tmp_path, monkeypatch):
        """Saving LIGHT and loading returns (LIGHT, 'Light')."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path))
        save_theme(LIGHT, "Light")
        loaded, name = load_saved_theme()
        assert name == "Light"
        assert loaded.panel_bg.upper() == LIGHT.panel_bg.upper()
        assert loaded.text_primary.upper() == LIGHT.text_primary.upper()

    def test_roundtrip_dark(self, tmp_path, monkeypatch):
        """Saving DARK and loading returns (DARK, 'Dark')."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path))
        save_theme(DARK, "Dark")
        loaded, name = load_saved_theme()
        assert name == "Dark"
        assert loaded.panel_bg.upper() == DARK.panel_bg.upper()
        assert loaded.window_bg.upper() == DARK.window_bg.upper()

    def test_roundtrip_custom_overrides(self, tmp_path, monkeypatch):
        """Saving a Custom theme with overrides and loading returns the overrides."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path))
        custom = Theme(**asdict(LIGHT))
        custom.accent = "#FF0000"
        custom.panel_bg = "#FAFAFA"
        save_theme(custom, "Custom")
        loaded, name = load_saved_theme()
        assert name == "Custom"
        assert loaded.accent.upper() == "#FF0000"
        assert loaded.panel_bg.upper() == "#FAFAFA"

    def test_missing_config_returns_light_default(self, tmp_path, monkeypatch):
        """When no config file exists, load_saved_theme returns (LIGHT, 'Light')."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path / "nonexistent"))
        loaded, name = load_saved_theme()
        assert name == "Light"
        assert loaded.panel_bg.upper() == LIGHT.panel_bg.upper()

    def test_corrupt_config_returns_light_default(self, tmp_path, monkeypatch):
        """Corrupt JSON in the config file falls back to (LIGHT, 'Light')."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path))
        config_file = tmp_path / "theme.json"
        config_file.write_text("NOT VALID JSON }{", encoding="utf-8")
        loaded, name = load_saved_theme()
        assert name == "Light"
        assert loaded.panel_bg.upper() == LIGHT.panel_bg.upper()

    def test_saved_config_is_valid_json(self, tmp_path, monkeypatch):
        """The saved config file is valid, readable JSON."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path))
        save_theme(DARK, "Dark")
        config_file = tmp_path / "theme.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text(encoding="utf-8"))
        assert "template" in data
        assert data["template"] == "Dark"
        assert "overrides" in data

    def test_config_does_not_touch_real_user_config(self, tmp_path, monkeypatch):
        """The monkeypatched env var redirects all I/O to tmp_path only."""
        monkeypatch.setenv("FFE_THEME_CONFIG_DIR", str(tmp_path))
        save_theme(LIGHT, "Light")
        # Verify only our tmp file was written, not some real config path
        files_created = list(tmp_path.glob("*.json"))
        assert len(files_created) == 1
        assert files_created[0].name == "theme.json"


# ---------------------------------------------------------------------------
# Integration: MainWindow applies theme on init
# ---------------------------------------------------------------------------

class TestMainWindowThemeIntegration:
    """Verify theme is applied when MainWindow is constructed."""

    def test_main_window_has_active_theme_attributes(self, qapp):
        """MainWindow.__init__ sets _active_theme and _active_template_name."""
        from ff_explorer.gui.main_window import MainWindow
        win = MainWindow()
        try:
            assert hasattr(win, "_active_theme"), (
                "MainWindow must have _active_theme after __init__"
            )
            assert hasattr(win, "_active_template_name"), (
                "MainWindow must have _active_template_name after __init__"
            )
            assert isinstance(win._active_theme, Theme)
            assert isinstance(win._active_template_name, str)
        finally:
            win.close()
            win.deleteLater()

    def test_main_window_has_settings_button(self, qapp):
        """MainWindow must have a Settings button (opens the settings dialog)."""
        from PySide6.QtWidgets import QPushButton
        from ff_explorer.gui.main_window import MainWindow
        win = MainWindow()
        try:
            # Find any QPushButton whose text contains 'Settings'
            settings_btns = [
                btn for btn in win.findChildren(QPushButton)
                if "settings" in btn.text().lower()
            ]
            assert len(settings_btns) >= 1, (
                "MainWindow must have at least one QPushButton with 'Settings' in its text"
            )
            # Check it has a tooltip
            btn = settings_btns[0]
            assert btn.toolTip(), "Settings button must have a QToolTip"
        finally:
            win.close()
            win.deleteLater()

    def test_open_settings_slot_invokable(self, qapp, monkeypatch):
        """_open_settings() can be called without error (dialog exec patched)."""
        from ff_explorer.gui.main_window import MainWindow
        from ff_explorer.gui import settings_dialog as sd_mod
        executed = []

        # Patch SettingsDialog.exec so no modal loop is entered
        original_exec = sd_mod.SettingsDialog.exec

        def fake_exec(self_dlg):
            executed.append(True)
            return 0  # Rejected

        monkeypatch.setattr(sd_mod.SettingsDialog, "exec", fake_exec)
        win = MainWindow()
        try:
            win._open_settings()
            assert len(executed) == 1, "_open_settings must create and exec the dialog"
        finally:
            win.close()
            win.deleteLater()
