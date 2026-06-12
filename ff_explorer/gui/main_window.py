"""
FF Explorer — PySide6 main window
Juan García Sánchez, 2023-2026
License: GPLv3

Reproduces the full control set and UX flow of the legacy FF_UI.pyw Tkinter
window on top of the WS-1 pure core (ff_explorer.core).

Controls (1-to-1 mapping with the Tkinter original):
    Root path   — QLineEdit (read-only) + "Browse..." QPushButton
    Name seed   — QLineEdit (free-text entry)
    Mode        — QRadioButton pair "Folders" / "Files" in a QButtonGroup
    Action      — QComboBox ("*Select action*" / "Save list" / "Remove list" /
                             "Compress list")
    Run         — QPushButton

Hover help     — QToolTip on each control (replaces the Tkinter Toplevel overlay)
Context menu   — QMenu via contextMenuEvent ("About..." / "Exit")
Confirmations  — QMessageBox.question for destructive actions (dry-run preview first)
Warnings       — QMessageBox.warning / .critical for error conditions

Safety gate:
    Remove list and Compress list both call the core with dry_run=True first,
    display the matched paths in a QMessageBox confirmation dialog, and only
    on explicit user acceptance call again with dry_run=False, confirm=True.
    EmptySeedError is surfaced as a clear user-visible warning (never silently
    swallowed).
"""

from __future__ import annotations

import gc
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ff_explorer import (
    EmptySeedError,
    EntryKind,
    compress_entries,
    list_entries,
    remove_entries,
    save_listing,
)
from ff_explorer.gui._resources import resource_path


# ---------------------------------------------------------------------------
# Constants / metadata
# ---------------------------------------------------------------------------

_AUTHOR = "Juan García Sánchez"
_TITLE = "FF Explorer"
_VERSION = "1.0.0"
_LICENSE = "GPLv3"

_PLACEHOLDER_PATH = "*Select path here*"

# Maps display label → action code (mirrors legacy dict_options in FF_UI.pyw)
_ACTION_LABELS: dict[str, int] = {
    "*Select action*": -1,
    "Save list": 1,
    "Remove list": 2,
    "Compress list": 3,
}

# Hover-help texts for each control (mirrors legacy text_man1..text_man5)
_HELP_PATH = "Root path in which\nfiles or folders are searched."
_HELP_SEED = "List of consecutive characters\ncontained in files/folders' name."
_HELP_FOLDERS = "Folders search."
_HELP_FILES = "Files search."
_HELP_ACTION = "Actions to be applied to the resulting directory."

# Per-action supplementary help text (mirrors legacy aux_man)
_HELP_ACTION_DETAIL: dict[int, str] = {
    1: "\n   Save directory of files/folders found",
    2: "\n   Delete files/folders found",
    3: (
        "\n   For files, compress all in one .zip in root"
        "\n   For folders, compress each one in root"
    ),
}


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """PySide6 replacement for the legacy FFE_UI(Tk) class."""

    def __init__(self) -> None:
        super().__init__()
        self._setup_window()
        self._setup_ui()
        self._setup_context_menu()

    # ------------------------------------------------------------------
    # Window-level setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle(_TITLE)
        self.setFixedSize(280, 420)

        # Centre on the primary screen (replaces Tk winfo_screenwidth math)
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(
                geo.center().x() - self.width() // 2,
                geo.center().y() - self.height() // 2,
            )

        # Window icon — Logo FFE.png (sys._MEIPASS-aware path)
        icon_path = resource_path("Logo FFE.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        # Status bar (replaces print() feedback that was invisible under .pyw)
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)

        # Light grey background to match the legacy #bfbfbf Tk window colour
        self.setStyleSheet("QMainWindow { background-color: #bfbfbf; }")

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        # ---- Root path section ----
        path_label = QLabel("Root path")
        path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path_label.setStyleSheet(
            "background-color: #999999; color: blue; font: bold 12pt Arial; padding: 4px;"
        )
        path_label.setToolTip(_HELP_PATH)
        outer.addWidget(path_label)

        path_row = QHBoxLayout()
        self._path_edit = QLineEdit(_PLACEHOLDER_PATH)
        self._path_edit.setReadOnly(True)
        self._path_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._path_edit.setStyleSheet(
            "background-color: white; color: black; font: 11pt Verdana; padding: 4px;"
        )
        self._path_edit.setToolTip(_HELP_PATH)
        # Clicking the read-only field opens the folder picker (mirrors Tk <1> binding)
        self._path_edit.mousePressEvent = lambda _event: self._browse_path()
        path_row.addWidget(self._path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(72)
        browse_btn.setStyleSheet(
            "background-color: white; color: black; font: 11pt Arial;"
        )
        browse_btn.setToolTip(_HELP_PATH)
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        outer.addLayout(path_row)

        # ---- Name seed section ----
        seed_label = QLabel("Name seed")
        seed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seed_label.setStyleSheet(
            "background-color: #999999; color: blue; font: bold 12pt Arial; padding: 4px;"
        )
        seed_label.setToolTip(_HELP_SEED)
        outer.addWidget(seed_label)

        self._seed_edit = QLineEdit()
        self._seed_edit.setStyleSheet(
            "background-color: white; color: black; font: 11pt Verdana; padding: 4px;"
        )
        self._seed_edit.setToolTip(_HELP_SEED)
        self._seed_edit.returnPressed.connect(self._run)
        outer.addWidget(self._seed_edit)

        # ---- Mode radio buttons (Folders / Files) ----
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._radio_folders = QRadioButton("Folders")
        self._radio_folders.setChecked(True)  # d_type default = 0 (FOLDERS)
        self._radio_folders.setStyleSheet(
            "color: black; font: 12pt Verdana;"
        )
        self._radio_folders.setToolTip(_HELP_FOLDERS)
        self._mode_group.addButton(self._radio_folders, EntryKind.FOLDERS.value)
        mode_row.addWidget(self._radio_folders)

        self._radio_files = QRadioButton("Files")
        self._radio_files.setStyleSheet(
            "color: black; font: 12pt Verdana;"
        )
        self._radio_files.setToolTip(_HELP_FILES)
        self._mode_group.addButton(self._radio_files, EntryKind.FILES.value)
        mode_row.addWidget(self._radio_files)
        outer.addLayout(mode_row)

        # ---- Action combobox ----
        self._action_combo = QComboBox()
        self._action_combo.addItems(list(_ACTION_LABELS.keys()))
        self._action_combo.setStyleSheet(
            "background-color: #e6e6e6; font: 12pt Verdana; padding: 2px;"
        )
        # Build combined tooltip for the combobox (action name + detail)
        self._action_combo.currentIndexChanged.connect(self._update_action_tooltip)
        self._update_action_tooltip()  # set initial tooltip
        outer.addWidget(self._action_combo)

        # ---- Run button ----
        run_btn = QPushButton("Run")
        run_btn.setFixedWidth(80)
        run_btn.setStyleSheet(
            "background-color: white; color: black; font: bold 12pt Arial; padding: 6px;"
        )
        run_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        run_btn.setDefault(True)
        run_btn.clicked.connect(self._run)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        outer.addStretch()

    # ------------------------------------------------------------------
    # Context menu (right-click — mirrors legacy show_menucontext / Menu)
    # ------------------------------------------------------------------

    def _setup_context_menu(self) -> None:
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        about_action = menu.addAction("About...")
        exit_action = menu.addAction("Exit")
        action = menu.exec(self.mapToGlobal(pos))
        if action is about_action:
            QMessageBox.information(
                self,
                "About FF Explorer",
                f"Author: {_AUTHOR}\nVersion: {_VERSION}\nLicense: {_LICENSE}",
            )
        elif action is exit_action:
            self._exit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_kind(self) -> EntryKind:
        """Return the EntryKind matching the selected radio button."""
        btn_id = self._mode_group.checkedId()
        return EntryKind(btn_id)

    def _update_action_tooltip(self) -> None:
        """Update the action combobox tooltip to include per-action detail."""
        label = self._action_combo.currentText()
        code = _ACTION_LABELS.get(label, -1)
        detail = _HELP_ACTION_DETAIL.get(code, "")
        self._action_combo.setToolTip(_HELP_ACTION + detail)

    def _set_status(self, message: str) -> None:
        """Write *message* to the status bar (replaces print() calls)."""
        self._status_bar.showMessage(message, 8000)

    # ------------------------------------------------------------------
    # Slot: folder picker
    # ------------------------------------------------------------------

    def _browse_path(self) -> None:
        """Open a folder-picker dialog (replaces filedialog.askdirectory)."""
        current = self._path_edit.text()
        start = current if (current != _PLACEHOLDER_PATH and Path(current).is_dir()) else ""
        chosen = QFileDialog.getExistingDirectory(
            self,
            "FF Explorer — root path selection",
            start,
        )
        if chosen:
            self._path_edit.setText(chosen)

    # ------------------------------------------------------------------
    # Slot: Run button / Enter key
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """
        Validate inputs and dispatch to the appropriate core function.

        Mirrors the legacy accept() method in FF_UI.pyw with the safety gate
        preserved:
          - Destructive ops (Remove / Compress) always call the core with
            dry_run=True first, display the preview list, and only proceed on
            explicit user confirmation.
          - EmptySeedError is surfaced as a QMessageBox.warning.
        """
        # --- Input validation (mirrors legacy accept() guards) ---
        path_text = self._path_edit.text()
        if path_text == _PLACEHOLDER_PATH or not path_text.strip():
            QMessageBox.warning(self, "Warning!", "Source path not added")
            return

        action_label = self._action_combo.currentText()
        action_code = _ACTION_LABELS.get(action_label, -1)
        if action_code == -1:
            QMessageBox.warning(self, "Warning!", "No action selected")
            return

        path = path_text
        kind = self._current_kind()
        seed = self._seed_edit.text()
        entry_label = "file" if kind == EntryKind.FILES else "folder"

        try:
            if action_code == 1:
                self._do_save(path, kind, seed, entry_label)
            elif action_code == 2:
                self._do_remove(path, kind, seed, entry_label)
            elif action_code == 3:
                self._do_compress(path, kind, seed, entry_label)

        except EmptySeedError as exc:
            QMessageBox.warning(self, "Empty seed", str(exc))
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
        except OSError as exc:
            QMessageBox.critical(self, "File system error", str(exc))

    # ------------------------------------------------------------------
    # Action helpers (called from _run)
    # ------------------------------------------------------------------

    def _do_save(self, path: str, kind: EntryKind, seed: str, entry_label: str) -> None:
        """Save list — low risk, no confirmation required."""
        out_path = save_listing(path, kind, seed)
        entries = list_entries(path, kind, seed)
        if entries:
            self._set_status(f"Directory saved to {out_path}.")
        else:
            self._set_status(f"No {entry_label} was found — nothing was saved.")

    def _do_remove(self, path: str, kind: EntryKind, seed: str, entry_label: str) -> None:
        """
        Remove list — SAFETY GATE:
          1. Dry-run to get the preview list.
          2. Show confirmation dialog with the matched paths.
          3. Only on Yes: call with dry_run=False, confirm=True.
        """
        preview = remove_entries(path, kind, seed, dry_run=True)
        if not preview.matched:
            self._set_status(f"No {entry_label} was found — nothing was deleted.")
            return

        preview_text = self._build_preview_text(preview.matched, entry_label)
        reply = QMessageBox.question(
            self,
            "Confirm removal",
            (
                f"About to permanently remove "
                f"{len(preview.matched)} {entry_label}(s):\n\n"
                f"{preview_text}\n\nProceed?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            report = remove_entries(path, kind, seed, dry_run=False, confirm=True)
            msg = f"{len(report.removed)} {entry_label}(s) removed."
            if report.failed:
                msg += f"  {len(report.failed)} removal(s) failed."
            self._set_status(msg)
        else:
            self._set_status("Removal cancelled.")

    def _do_compress(self, path: str, kind: EntryKind, seed: str, entry_label: str) -> None:
        """
        Compress list — SAFETY GATE (same pattern as _do_remove):
          1. Dry-run to get the preview list.
          2. Show confirmation dialog (note: originals are deleted after compression).
          3. Only on Yes: call with dry_run=False, confirm=True.
        """
        preview = compress_entries(path, kind, seed, dry_run=True)
        if not preview.matched:
            self._set_status(f"No {entry_label} was found — nothing was compressed.")
            return

        preview_text = self._build_preview_text(preview.matched, entry_label)
        reply = QMessageBox.question(
            self,
            "Confirm compression",
            (
                f"About to compress {len(preview.matched)} {entry_label}(s):\n\n"
                f"{preview_text}\n\n"
                "Originals will be deleted after compression.  Proceed?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            report = compress_entries(path, kind, seed, dry_run=False, confirm=True)
            msg = f"{len(report.archives)} archive(s) created."
            if report.failed:
                msg += f"  {len(report.failed)} compression/delete(s) failed."
            self._set_status(msg)
        else:
            self._set_status("Compression cancelled.")

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _build_preview_text(paths: list[Path], entry_label: str, limit: int = 20) -> str:
        """Build a newline-separated preview string, capped at *limit* entries."""
        lines = [str(p) for p in paths[:limit]]
        text = "\n".join(lines)
        if len(paths) > limit:
            text += f"\n  ... and {len(paths) - limit} more {entry_label}(s)."
        return text

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _exit(self) -> None:
        """Clean shutdown (mirrors legacy exit() method)."""
        self.close()
        gc.collect()

    def closeEvent(self, event) -> None:
        """Handle the window close button and the context-menu Exit action."""
        gc.collect()
        event.accept()

    # ------------------------------------------------------------------
    # Keyboard shortcut: Enter → Run  (handled via returnPressed on seed_edit
    # and QDialog.setDefault on run_btn; also handle Ctrl+Right as legacy exit)
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._run()
        elif (
            event.key() == Qt.Key.Key_Control
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            # Legacy binding: <Control_R> → exit
            self._exit()
        else:
            super().keyPressEvent(event)
