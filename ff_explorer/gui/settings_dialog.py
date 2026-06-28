"""
FF Explorer — Settings dialog (theme configuration)
Juan García Sánchez, 2023-2026
License: GPLv3

Provides a QDialog that lets the user choose a colour template (Light / Dark /
Custom) and fine-tune individual colour roles.  Changes can be applied live or
reverted on Cancel.

Usage (from MainWindow or elsewhere):
    from ff_explorer.gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(current_theme, current_template_name, parent=self)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        apply_theme(dlg.selected_theme(), dlg.selected_template_name())
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ff_explorer.gui.theme import (
    BUILTIN_THEMES,
    LIGHT,
    Theme,
    build_stylesheet,
    save_theme,
    validate_theme,
)
from ff_explorer.gui.widget_info import register_info


# ---------------------------------------------------------------------------
# Human-readable labels for each Theme role
# ---------------------------------------------------------------------------

_ROLE_LABELS: dict[str, str] = {
    "window_bg": "Window background",
    "panel_bg": "Panel / surface background",
    "alt_row_bg": "Alternate row background",
    "text_primary": "Primary text",
    "text_secondary": "Secondary / metadata text",
    "disabled_text": "Disabled text",
    "label_text": "Section header labels",
    "radio_text": "Radio button text",
    "border": "Border / divider",
    "accent": "Accent (focus / selection ring)",
    "selection_bg": "Selection background",
    "selection_text": "Selected item text",
    "button_bg": "Button background",
    "button_hover_bg": "Button hover background",
    "button_border": "Button border",
    "button_text": "Button text",
    "input_bg": "Input field background",
    "input_text": "Input field text",
    "header_bg": "Column header background",
    "header_text": "Column header text",
    "destructive_accent": "Destructive action accent",
    "status_bar_bg": "Status bar background",
    "status_bar_text": "Status bar text",
    "tooltip_bg": "Tooltip background",
    "tooltip_text": "Tooltip text",
    "scrollbar_bg": "Scrollbar track",
    "scrollbar_handle": "Scrollbar handle",
}


# ---------------------------------------------------------------------------
# Colour swatch button
# ---------------------------------------------------------------------------

class _SwatchButton(QPushButton):
    """A small coloured square button that opens QColorDialog on click."""

    def __init__(self, hex_color: str, on_changed: Callable[[str], None]) -> None:
        super().__init__()
        self._on_changed = on_changed
        self.setFixedSize(28, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        register_info(self, "settings_swatch")
        self._set_color(hex_color)
        self.clicked.connect(self._pick_color)

    # ------------------------------------------------------------------
    def current_hex(self) -> str:
        """Return the current colour as a ``#RRGGBB`` string."""
        return self._hex

    def set_hex(self, hex_color: str) -> None:
        """Update the swatch to *hex_color* without opening the picker."""
        self._set_color(hex_color)

    # ------------------------------------------------------------------
    def _set_color(self, hex_color: str) -> None:
        self._hex = hex_color
        # Set background via inline style; use a border for visibility
        self.setStyleSheet(
            f"QPushButton {{ background-color: {hex_color}; "
            f"border: 1px solid #888888; border-radius: 2px; }}"
        )

    def _pick_color(self) -> None:
        initial = QColor(self._hex)
        chosen = QColorDialog.getColor(initial, self, "Choose colour")
        if chosen.isValid():
            new_hex = chosen.name().upper()
            self._set_color(new_hex)
            self._on_changed(new_hex)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """Settings window: template selector + per-role colour editor.

    Parameters
    ----------
    initial_theme:
        The Theme that was active when the dialog was opened.
    initial_template_name:
        ``"Light"``, ``"Dark"``, or ``"Custom"``.
    apply_callback:
        Optional callable invoked with ``(Theme, str)`` on live-apply so the
        main window can update ``QApplication.instance().setStyleSheet(…)``
        without the dialog needing to know about the app.
    parent:
        Parent widget (the main window).
    """

    def __init__(
        self,
        initial_theme: Theme,
        initial_template_name: str,
        apply_callback: Optional[Callable[[Theme, str], None]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("FF Explorer — Settings")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._apply_callback = apply_callback
        self._original_theme = initial_theme
        self._original_template_name = initial_template_name

        # Working copy — mutated by swatch clicks
        self._current_theme: Theme = _copy_theme(initial_theme)
        self._current_template: str = initial_template_name

        self._swatches: dict[str, _SwatchButton] = {}

        self._build_ui()
        self._populate_swatches(self._current_theme)
        self._refresh_validation()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def selected_theme(self) -> Theme:
        """Return the theme currently configured in the dialog."""
        return _copy_theme(self._current_theme)

    def selected_template_name(self) -> str:
        """Return ``"Light"``, ``"Dark"``, or ``"Custom"``."""
        return self._current_template

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ---- Template selector row ----
        tpl_row = QHBoxLayout()
        tpl_label = QLabel("Template:")
        tpl_label.setFixedWidth(80)
        tpl_row.addWidget(tpl_label)

        self._template_combo = QComboBox()
        for name in list(BUILTIN_THEMES.keys()) + ["Custom"]:
            self._template_combo.addItem(name)
        # Set current
        idx = self._template_combo.findText(self._current_template)
        if idx >= 0:
            self._template_combo.setCurrentIndex(idx)
        self._template_combo.currentTextChanged.connect(self._on_template_changed)
        tpl_row.addWidget(self._template_combo)
        root.addLayout(tpl_row)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # ---- Scrollable role editor ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(6)
        grid.setContentsMargins(4, 4, 4, 4)

        role_names = list(_ROLE_LABELS.keys())
        for row, role in enumerate(role_names):
            label = QLabel(_ROLE_LABELS[role])
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            swatch = _SwatchButton("#000000", self._make_role_handler(role))
            self._swatches[role] = swatch
            grid.addWidget(label, row, 0)
            grid.addWidget(swatch, row, 1)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)  # stretch

        # ---- Validation note ----
        self._validation_label = QLabel("")
        self._validation_label.setWordWrap(True)
        self._validation_label.setStyleSheet("color: #C42B1C; font-size: 9pt;")
        root.addWidget(self._validation_label)

        # ---- Buttons: Reset | Apply | Cancel | OK ----
        btn_row = QHBoxLayout()

        self._reset_btn = QPushButton(f"Reset to {self._current_template}")
        register_info(self._reset_btn, "settings_reset")
        self._reset_btn.clicked.connect(self._on_reset)
        btn_row.addWidget(self._reset_btn)

        btn_row.addStretch()

        self._apply_btn = QPushButton("Apply")
        register_info(self._apply_btn, "settings_apply")
        self._apply_btn.clicked.connect(self._on_apply)
        btn_row.addWidget(self._apply_btn)

        cancel_btn = QPushButton("Cancel")
        register_info(cancel_btn, "settings_cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(cancel_btn)

        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        register_info(ok_btn, "settings_ok")
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Swatch helpers
    # ------------------------------------------------------------------

    def _make_role_handler(self, role: str) -> Callable[[str], None]:
        """Return a handler that updates *role* in the working theme."""
        def handler(new_hex: str) -> None:
            setattr(self._current_theme, role, new_hex)
            # Any manual edit → "Custom"
            if self._current_template in BUILTIN_THEMES:
                self._current_template = "Custom"
                self._template_combo.blockSignals(True)
                idx = self._template_combo.findText("Custom")
                if idx >= 0:
                    self._template_combo.setCurrentIndex(idx)
                self._template_combo.blockSignals(False)
                self._reset_btn.setText(f"Reset to {self._current_template}")
            self._refresh_validation()
        return handler

    def _populate_swatches(self, theme: Theme) -> None:
        """Update all swatch buttons to reflect *theme*."""
        theme_dict = asdict(theme)
        for role, swatch in self._swatches.items():
            swatch.set_hex(theme_dict.get(role, "#000000"))

    # ------------------------------------------------------------------
    # Validation display
    # ------------------------------------------------------------------

    def _refresh_validation(self) -> None:
        violations = validate_theme(self._current_theme)
        if violations:
            msg = "Colour warnings:\n" + "\n".join(f"  • {v}" for v in violations)
            self._validation_label.setText(msg)
        else:
            self._validation_label.setText("")

    # ------------------------------------------------------------------
    # Slot: template selector changed
    # ------------------------------------------------------------------

    def _on_template_changed(self, name: str) -> None:
        if name in BUILTIN_THEMES:
            self._current_theme = _copy_theme(BUILTIN_THEMES[name])
            self._current_template = name
            self._populate_swatches(self._current_theme)
            self._refresh_validation()
        else:
            # "Custom" selected manually — keep current colours
            self._current_template = "Custom"
        self._reset_btn.setText(f"Reset to {self._current_template}")

    # ------------------------------------------------------------------
    # Slots: buttons
    # ------------------------------------------------------------------

    def _on_reset(self) -> None:
        """Reset to the built-in template matching the current selection."""
        tpl = self._current_template
        if tpl not in BUILTIN_THEMES:
            tpl = "Light"
        self._current_theme = _copy_theme(BUILTIN_THEMES[tpl])
        self._current_template = tpl
        self._populate_swatches(self._current_theme)
        self._refresh_validation()
        # Update combo
        self._template_combo.blockSignals(True)
        idx = self._template_combo.findText(tpl)
        if idx >= 0:
            self._template_combo.setCurrentIndex(idx)
        self._template_combo.blockSignals(False)

    def _on_apply(self) -> None:
        """Apply the current theme live without closing the dialog."""
        if self._apply_callback is not None:
            self._apply_callback(self._current_theme, self._current_template)

    def _on_ok(self) -> None:
        """Apply, persist, then accept the dialog."""
        self._on_apply()
        try:
            save_theme(self._current_theme, self._current_template)
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Settings",
                f"Could not save settings: {exc}",
            )
        self.accept()

    def _on_cancel(self) -> None:
        """Revert the live theme to the one active on open, then reject."""
        if self._apply_callback is not None:
            self._apply_callback(self._original_theme, self._original_template_name)
        self.reject()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _copy_theme(theme: Theme) -> Theme:
    """Return a shallow copy of *theme*."""
    return Theme(**asdict(theme))
