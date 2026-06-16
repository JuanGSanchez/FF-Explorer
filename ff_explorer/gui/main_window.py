"""
FF Explorer — PySide6 main window
Juan García Sánchez, 2023-2026
License: GPLv3

PySide6 main window for FF Explorer, built on the pure core (ff_explorer.core).

Controls (1-to-1 mapping with the Tkinter original):
    Root path   — QLineEdit (read-only) + "Browse..." QPushButton
    Name seed   — QLineEdit (free-text entry)
    Mode        — QRadioButton pair "Folders" / "Files" in a QButtonGroup
    Action      — QComboBox ("*Select action*" / "Save list" / "Remove list" /
                             "Compress list")
    Run         — QPushButton

Filter controls (FFX-I01/FFX-I02):
    Match mode  — QComboBox (Substring / Glob / Regex)
    Case sens.  — QCheckBox
    Size range  — two QSpinBox (min KB / max KB; 0 = no bound)
    Date range  — two QDateEdit with enable QCheckBox (modified after/before)
    Extensions  — QLineEdit (comma/space-separated, e.g. ".txt, .md")
    All grouped under a collapsible "Filters ▼/▶" section.

Extended filter controls (FFX-I04/I05/I09):
    Content contains — QLineEdit (FFX-I09): content_query; gated by core
    Search in archives — QCheckBox (FFX-I05): search_archives=True
    Respect .gitignore/.ignore — QCheckBox (FFX-I04): respect_ignore=True
    Extra ignore globs — QLineEdit (FFX-I04): ignore_globs (comma/space split)

Action controls (FFX-I03/I06/I07/I08/I10):
    Version (remove) — QCheckBox (FFX-I08): versioning=True on remove_entries
    Find duplicates  — QPushButton (FFX-I06): opens duplicates results dialog
    Save preset      — QPushButton (FFX-I03): saves current form state as preset
    Load preset      — QPushButton (FFX-I03): loads a preset back into the form
    Batch rename     — QPushButton (FFX-I07): opens rename rule dialog
    Live index       — QCheckBox (FFX-I10): starts/stops IndexManager observer

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
    Batch rename uses the same dry_run/confirm pattern (preview then confirm).

Filter param mapping:
    match_mode      — "substring" | "glob" | "regex"; passed to list_entries only
                      (remove/compress/save do not expose this param yet).
    case_sensitive  — bool; passed to all core functions.
    min_size        — SpinBox value × 1024 (bytes); 0 means no bound (None).
    max_size        — SpinBox value × 1024 (bytes); 0 means no bound (None).
    modified_after  — QDateEdit epoch seconds when enabled; None otherwise.
    modified_before — QDateEdit epoch seconds when enabled; None otherwise.
    extensions      — parsed list of ".ext" strings; [] means no filter (None).
    Invalid regex   — surfaced as QMessageBox.warning via the ValueError that
                      core raises on a bad re.compile().
    content_query   — passed when non-empty; ContentSearchUngatedError caught
                      and surfaced as a friendly QMessageBox.warning.
    search_archives — True when checkbox checked; default False.
    respect_ignore  — True when checkbox checked; default False.
    ignore_globs    — parsed list of glob strings from the extra-globs field.
"""

from __future__ import annotations

import gc
from pathlib import Path

from PySide6.QtCore import QDate, QDateTime, Qt, QTimeZone
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from ff_explorer.gui.theme import build_stylesheet, load_saved_theme

from ff_explorer import (
    EmptySeedError,
    EntryKind,
    compress_entries,
    list_entries,
    remove_entries,
    save_listing,
)
from ff_explorer.core import ContentSearchUngatedError
from ff_explorer.dedupe import find_duplicates
from ff_explorer.rename import RenameRule, rename_entries
from ff_explorer.presets import Preset, get_preset, list_presets, save_preset
from ff_explorer.index import IndexManager
from ff_explorer.gui._resources import resource_path


# ---------------------------------------------------------------------------
# Constants / metadata
# ---------------------------------------------------------------------------

_AUTHOR = "Juan García Sánchez"
_TITLE = "FF Explorer"
_VERSION = "1.0.0"
_LICENSE = "GPLv3"

_PLACEHOLDER_PATH = "*Select path here*"

# Maps display label → action code (mirrors legacy dict_options)
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

# Match-mode display labels → core param values
_MATCH_MODE_LABELS: dict[str, str] = {
    "Substring": "substring",
    "Glob": "glob",
    "Regex": "regex",
}

# Window heights — collapsed (no filters) and expanded (filters visible)
_WIN_HEIGHT_COLLAPSED = 560
_WIN_HEIGHT_EXPANDED = 880


# ---------------------------------------------------------------------------
# Helper widget
# ---------------------------------------------------------------------------

class _ClickableLineEdit(QLineEdit):
    """Read-only QLineEdit that fires a callback on mouse press.

    Calls the base implementation first (preserving focus/cursor behaviour)
    and then invokes *on_click*, replacing the non-idiomatic instance
    monkey-patch that was previously used.
    """

    def __init__(self, text: str = "", on_click=None) -> None:
        super().__init__(text)
        self._on_click = on_click

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if self._on_click is not None:
            self._on_click()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    """PySide6 replacement for the legacy FFE_UI(Tk) class."""

    def __init__(self) -> None:
        super().__init__()
        # Load and apply the persisted theme before any widget is styled.
        self._active_theme, self._active_template_name = load_saved_theme()
        self._setup_window()
        self._setup_ui()
        self._setup_context_menu()
        # Apply the loaded theme stylesheet globally (after widgets are built).
        QApplication.instance().setStyleSheet(  # type: ignore[union-attr]
            build_stylesheet(self._active_theme)
        )

    # ------------------------------------------------------------------
    # Window-level setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle(_TITLE)
        self.setFixedSize(280, _WIN_HEIGHT_COLLAPSED)

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

        # Background is now managed by the centralized theme stylesheet applied
        # in __init__ via build_stylesheet(); the per-widget inline styles below
        # remain for legacy sizing/font but are overridden by the QSS theme.

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
        self._path_edit = _ClickableLineEdit(
            _PLACEHOLDER_PATH, on_click=lambda: self._browse_path()
        )
        self._path_edit.setReadOnly(True)
        self._path_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._path_edit.setStyleSheet(
            "background-color: white; color: black; font: 11pt Verdana; padding: 4px;"
        )
        self._path_edit.setToolTip(_HELP_PATH)
        # Clicking the read-only field opens the folder picker — handled by
        # _ClickableLineEdit.mousePressEvent (calls super() then on_click)
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

        # ---- Filters toggle button (FFX-I01 / FFX-I02) ----
        self._filters_toggle_btn = QPushButton("Filters ▶")
        self._filters_toggle_btn.setToolTip(
            "Expand to set match mode, size/date/extension filters."
        )
        self._filters_toggle_btn.setCheckable(True)
        self._filters_toggle_btn.setChecked(False)
        self._filters_toggle_btn.clicked.connect(self._toggle_filters)

        filters_toggle_row = QHBoxLayout()
        filters_toggle_row.addStretch()
        filters_toggle_row.addWidget(self._filters_toggle_btn)
        filters_toggle_row.addStretch()
        outer.addLayout(filters_toggle_row)

        # ---- Filters panel (hidden by default) ----
        self._filters_panel = self._build_filters_panel()
        self._filters_panel.setVisible(False)
        outer.addWidget(self._filters_panel)

        # ---- Settings button ----
        settings_btn = QPushButton("⚙ Settings")  # gear unicode
        settings_btn.setFixedWidth(100)
        settings_btn.setToolTip(
            "Open Settings to configure the application colour theme."
        )
        settings_btn.clicked.connect(self._open_settings)

        settings_row = QHBoxLayout()
        settings_row.addStretch()
        settings_row.addWidget(settings_btn)
        outer.addLayout(settings_row)

        # ---- Disk usage button (FFX-I11) ----
        disk_usage_btn = QPushButton("Disk usage")
        disk_usage_btn.setFixedWidth(100)
        disk_usage_btn.setToolTip(
            "Show the largest files under the current root path."
        )
        disk_usage_btn.clicked.connect(self._open_disk_usage)

        disk_usage_row = QHBoxLayout()
        disk_usage_row.addStretch()
        disk_usage_row.addWidget(disk_usage_btn)
        outer.addLayout(disk_usage_row)

        # ---- Find duplicates button (FFX-I06) ----
        dup_btn = QPushButton("Find duplicates")
        dup_btn.setFixedWidth(130)
        dup_btn.setToolTip(
            "Find groups of files with identical content under the current root path.\n"
            "Results are shown in a read-only dialog."
        )
        dup_btn.clicked.connect(self._open_find_duplicates)

        dup_row = QHBoxLayout()
        dup_row.addStretch()
        dup_row.addWidget(dup_btn)
        outer.addLayout(dup_row)

        # ---- Batch rename button (FFX-I07) ----
        rename_btn = QPushButton("Batch rename")
        rename_btn.setFixedWidth(130)
        rename_btn.setToolTip(
            "Open the batch rename dialog to define a rule, preview changes,\n"
            "and apply renaming to matched entries."
        )
        rename_btn.clicked.connect(self._open_batch_rename)

        rename_row = QHBoxLayout()
        rename_row.addStretch()
        rename_row.addWidget(rename_btn)
        outer.addLayout(rename_row)

        # ---- Preset save/load row (FFX-I03) ----
        preset_save_btn = QPushButton("Save preset")
        preset_save_btn.setFixedWidth(110)
        preset_save_btn.setToolTip(
            "Save the current search form state as a named preset."
        )
        preset_save_btn.clicked.connect(self._save_preset)

        preset_load_btn = QPushButton("Load preset")
        preset_load_btn.setFixedWidth(110)
        preset_load_btn.setToolTip(
            "Load a saved preset back into the search form."
        )
        preset_load_btn.clicked.connect(self._load_preset)

        preset_row = QHBoxLayout()
        preset_row.addStretch()
        preset_row.addWidget(preset_save_btn)
        preset_row.addWidget(preset_load_btn)
        preset_row.addStretch()
        outer.addLayout(preset_row)

        # ---- Live index checkbox (FFX-I10) ----
        self._live_index_check = QCheckBox("Live index this root")
        self._live_index_check.setChecked(False)
        self._live_index_check.setToolTip(
            "Build an in-memory name index for the current root and watch for\n"
            "filesystem changes in real time.  Queries use the index instead of\n"
            "walking the tree.  Uncheck to stop and release the observer thread."
        )
        self._live_index_check.toggled.connect(self._toggle_live_index)

        index_row = QHBoxLayout()
        index_row.addStretch()
        index_row.addWidget(self._live_index_check)
        index_row.addStretch()
        outer.addLayout(index_row)

        outer.addStretch()

    def _build_filters_panel(self) -> QGroupBox:
        """Build the collapsible Filters panel (FFX-I01 / FFX-I02).

        Returns a QGroupBox containing:
          - Match mode QComboBox (Substring / Glob / Regex)
          - Case sensitive QCheckBox
          - Min/max size QSpinBox (KB; 0 = no bound)
          - Modified-after / modified-before QDateEdit with enable checkboxes
          - Extensions QLineEdit (comma/space-separated)

        All widgets are styled only via the centralised QSS theme (no
        hard-coded colours) so they adapt to Light/Dark themes automatically.
        """
        box = QGroupBox("Filters")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ---- Match mode + case sensitive ----
        match_row = QHBoxLayout()

        match_label = QLabel("Match:")
        match_row.addWidget(match_label)

        self._match_mode_combo = QComboBox()
        self._match_mode_combo.addItems(list(_MATCH_MODE_LABELS.keys()))
        self._match_mode_combo.setToolTip(
            "Substring: seed 'in' name (default).\n"
            "Glob: fnmatch pattern (*, ?, […]).\n"
            "Regex: full regular expression."
        )
        match_row.addWidget(self._match_mode_combo)

        self._case_sensitive_check = QCheckBox("Case sensitive")
        self._case_sensitive_check.setChecked(True)
        self._case_sensitive_check.setToolTip(
            "When unchecked, the name match ignores case.\n"
            "For Regex mode, re.IGNORECASE is applied."
        )
        match_row.addWidget(self._case_sensitive_check)

        layout.addLayout(match_row)

        # ---- Size filters (KB; 0 = no bound) ----
        size_row = QHBoxLayout()

        size_label = QLabel("Size (KB):")
        size_row.addWidget(size_label)

        self._min_size_spin = QSpinBox()
        self._min_size_spin.setRange(0, 10_000_000)  # up to ~10 GB in KB
        self._min_size_spin.setValue(0)
        self._min_size_spin.setSpecialValueText("–")  # 0 displays as "–" (no bound)
        self._min_size_spin.setToolTip("Minimum file size in KB (0 = no lower bound).")
        size_row.addWidget(self._min_size_spin)

        size_row.addWidget(QLabel("–"))

        self._max_size_spin = QSpinBox()
        self._max_size_spin.setRange(0, 10_000_000)
        self._max_size_spin.setValue(0)
        self._max_size_spin.setSpecialValueText("–")  # 0 displays as "–" (no bound)
        self._max_size_spin.setToolTip("Maximum file size in KB (0 = no upper bound).")
        size_row.addWidget(self._max_size_spin)

        layout.addLayout(size_row)

        # ---- Date filters (modified after / before) ----
        after_row = QHBoxLayout()
        self._date_after_check = QCheckBox("Modified after:")
        self._date_after_check.setChecked(False)
        self._date_after_check.setToolTip(
            "Only include entries modified strictly after this date."
        )
        after_row.addWidget(self._date_after_check)

        self._date_after_edit = QDateEdit()
        self._date_after_edit.setCalendarPopup(True)
        self._date_after_edit.setDate(QDate.currentDate().addDays(-30))
        self._date_after_edit.setEnabled(False)
        self._date_after_edit.setToolTip("Lower bound on modification date.")
        after_row.addWidget(self._date_after_edit)

        layout.addLayout(after_row)

        self._date_after_check.toggled.connect(self._date_after_edit.setEnabled)

        before_row = QHBoxLayout()
        self._date_before_check = QCheckBox("Modified before:")
        self._date_before_check.setChecked(False)
        self._date_before_check.setToolTip(
            "Only include entries modified strictly before this date."
        )
        before_row.addWidget(self._date_before_check)

        self._date_before_edit = QDateEdit()
        self._date_before_edit.setCalendarPopup(True)
        self._date_before_edit.setDate(QDate.currentDate())
        self._date_before_edit.setEnabled(False)
        self._date_before_edit.setToolTip("Upper bound on modification date.")
        before_row.addWidget(self._date_before_edit)

        layout.addLayout(before_row)

        self._date_before_check.toggled.connect(self._date_before_edit.setEnabled)

        # ---- Extensions filter ----
        ext_row = QHBoxLayout()
        ext_label = QLabel("Extensions:")
        ext_row.addWidget(ext_label)

        self._extensions_edit = QLineEdit()
        self._extensions_edit.setPlaceholderText(".txt, .md, .log")
        self._extensions_edit.setToolTip(
            "Comma or space-separated extensions to include.\n"
            "Example: .txt, .md\n"
            "Leave empty for no extension filter."
        )
        ext_row.addWidget(self._extensions_edit)

        layout.addLayout(ext_row)

        # ---- Content search (FFX-I09) ----
        content_row = QHBoxLayout()
        content_label = QLabel("Content contains:")
        content_row.addWidget(content_label)

        self._content_query_edit = QLineEdit()
        self._content_query_edit.setPlaceholderText("grep pattern (requires name/type/size pre-filter)")
        self._content_query_edit.setToolTip(
            "Grep-style search inside file contents.\n"
            "Only files whose content matches this query are returned.\n"
            "REQUIRES at least one name/extension/size filter to be set\n"
            "to limit the candidate set (performance gate)."
        )
        content_row.addWidget(self._content_query_edit)

        layout.addLayout(content_row)

        # ---- Archive transparency (FFX-I05) ----
        self._search_archives_check = QCheckBox("Search inside archives")
        self._search_archives_check.setChecked(False)
        self._search_archives_check.setToolTip(
            "When checked, open matching ZIP/TAR/GZ archives and search their\n"
            "internal member names against the name seed.\n"
            "Archive-internal results are read-only and cannot be removed/compressed."
        )
        layout.addWidget(self._search_archives_check)

        # ---- Ignore-file awareness (FFX-I04) ----
        self._respect_ignore_check = QCheckBox("Respect .gitignore/.ignore")
        self._respect_ignore_check.setChecked(False)
        self._respect_ignore_check.setToolTip(
            "When checked, .gitignore and .ignore files found during the walk\n"
            "are honoured; matching paths are excluded from results."
        )
        layout.addWidget(self._respect_ignore_check)

        ignore_globs_row = QHBoxLayout()
        ignore_globs_label = QLabel("Extra ignore globs:")
        ignore_globs_row.addWidget(ignore_globs_label)

        self._ignore_globs_edit = QLineEdit()
        self._ignore_globs_edit.setPlaceholderText("*.pyc, __pycache__/")
        self._ignore_globs_edit.setToolTip(
            "Extra gitwildmatch glob patterns to exclude (comma or space separated).\n"
            "Applied regardless of the .gitignore checkbox above."
        )
        ignore_globs_row.addWidget(self._ignore_globs_edit)

        layout.addLayout(ignore_globs_row)

        # ---- Versioned delete checkbox (FFX-I08) — shown only for Remove action ----
        self._versioning_check = QCheckBox("Version (move to .ffe-versions) instead of recycle bin")
        self._versioning_check.setChecked(False)
        self._versioning_check.setToolTip(
            "When checked, removed entries are moved into a timestamped\n"
            "<root>/.ffe-versions/<YYYYMMDD-HHMMSS>/ directory instead of the\n"
            "recycle bin.  Provides a stronger, auditable recovery trail.\n"
            "Applies only to the 'Remove list' action."
        )
        layout.addWidget(self._versioning_check)

        return box

    # ------------------------------------------------------------------
    # Filters toggle
    # ------------------------------------------------------------------

    def _toggle_filters(self, checked: bool) -> None:
        """Show or hide the filters panel and resize the window accordingly."""
        self._filters_panel.setVisible(checked)
        self._filters_toggle_btn.setText("Filters ▼" if checked else "Filters ▶")
        new_height = _WIN_HEIGHT_EXPANDED if checked else _WIN_HEIGHT_COLLAPSED
        self.setFixedSize(280, new_height)

    # ------------------------------------------------------------------
    # Filter param collectors (FFX-I01 / FFX-I02)
    # ------------------------------------------------------------------

    def _get_match_mode(self) -> str:
        """Return the core match_mode string for the selected combo item."""
        label = self._match_mode_combo.currentText()
        return _MATCH_MODE_LABELS.get(label, "substring")

    def _get_case_sensitive(self) -> bool:
        """Return the case-sensitive checkbox state."""
        return self._case_sensitive_check.isChecked()

    def _get_min_size(self) -> int | None:
        """Return min_size in bytes, or None when the spinbox is at 0 (no bound)."""
        val = self._min_size_spin.value()
        return val * 1024 if val > 0 else None

    def _get_max_size(self) -> int | None:
        """Return max_size in bytes, or None when the spinbox is at 0 (no bound)."""
        val = self._max_size_spin.value()
        return val * 1024 if val > 0 else None

    def _get_modified_after(self) -> float | None:
        """Return epoch seconds for the 'modified after' date, or None if disabled."""
        if not self._date_after_check.isChecked():
            return None
        from PySide6.QtCore import QTime
        date = self._date_after_edit.date()
        # Start of the selected date: 00:00:00 UTC — use QTimeZone.utc() to
        # avoid the deprecated Qt.TimeSpec overload.
        dt = QDateTime(date, QTime(0, 0, 0), QTimeZone.utc())
        return float(dt.toSecsSinceEpoch())

    def _get_modified_before(self) -> float | None:
        """Return epoch seconds for the 'modified before' date, or None if disabled.

        Uses end-of-day (23:59:59 UTC) so the chosen date is inclusive.
        """
        if not self._date_before_check.isChecked():
            return None
        from PySide6.QtCore import QTime
        date = self._date_before_edit.date()
        # End of the selected date: 23:59:59 UTC — use QTimeZone.utc() to
        # avoid the deprecated Qt.TimeSpec overload.
        dt = QDateTime(date, QTime(23, 59, 59), QTimeZone.utc())
        return float(dt.toSecsSinceEpoch())

    def _get_extensions(self) -> list[str] | None:
        """Parse extensions QLineEdit → list[str] with leading dot, or None if empty.

        Accepts comma and/or space-separated input.  Each token is normalised to
        have a single leading dot and is lower-cased.  Returns None (no filter)
        when the field is empty or all-whitespace.

        Examples
        --------
        ".txt, .md"  → [".txt", ".md"]
        "txt md"     → [".txt", ".md"]
        ""           → None
        """
        raw = self._extensions_edit.text().strip()
        if not raw:
            return None
        # Split on commas and whitespace
        import re as _re
        tokens = _re.split(r"[,\s]+", raw)
        result: list[str] = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if not token.startswith("."):
                token = "." + token
            result.append(token.lower())
        return result if result else None

    def _build_list_entries_kwargs(self) -> dict:
        """Collect all filter params for a list_entries call.

        Returns a dict of only the non-default kwargs so callers that pass
        **kwargs through are not affected by default-value noise.
        When all filters are at their defaults, returns {} (empty dict),
        preserving identical behaviour to the pre-filter codebase.
        """
        kwargs: dict = {}

        match_mode = self._get_match_mode()
        if match_mode != "substring":
            kwargs["match_mode"] = match_mode

        case_sensitive = self._get_case_sensitive()
        if not case_sensitive:
            kwargs["case_sensitive"] = False

        min_size = self._get_min_size()
        if min_size is not None:
            kwargs["min_size"] = min_size

        max_size = self._get_max_size()
        if max_size is not None:
            kwargs["max_size"] = max_size

        modified_after = self._get_modified_after()
        if modified_after is not None:
            kwargs["modified_after"] = modified_after

        modified_before = self._get_modified_before()
        if modified_before is not None:
            kwargs["modified_before"] = modified_before

        extensions = self._get_extensions()
        if extensions is not None:
            kwargs["extensions"] = extensions

        # FFX-I09: content search
        content_query = self._content_query_edit.text().strip()
        if content_query:
            kwargs["content_query"] = content_query

        # FFX-I05: archive transparency
        if self._search_archives_check.isChecked():
            kwargs["search_archives"] = True

        # FFX-I04: ignore-file awareness
        if self._respect_ignore_check.isChecked():
            kwargs["respect_ignore"] = True

        ignore_globs = self._get_ignore_globs()
        if ignore_globs is not None:
            kwargs["ignore_globs"] = ignore_globs

        return kwargs

    def _get_ignore_globs(self) -> list[str] | None:
        """Parse extra ignore globs QLineEdit → list[str] or None if empty."""
        raw = self._ignore_globs_edit.text().strip()
        if not raw:
            return None
        import re as _re
        tokens = _re.split(r"[,\s]+", raw)
        result = [t.strip() for t in tokens if t.strip()]
        return result if result else None

    def _build_core_kwargs(self) -> dict:
        """Collect params shared by all core functions (case_sensitive only).

        remove_entries / compress_entries / save_listing do not accept the
        structured filter params; they only accept case_sensitive.
        """
        kwargs: dict = {}
        case_sensitive = self._get_case_sensitive()
        if not case_sensitive:
            kwargs["case_sensitive"] = False
        return kwargs

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

        Validate inputs and dispatch to the core, with the safety gate preserved:
          - Destructive ops (Remove / Compress) always call the core with
            dry_run=True first, display the preview list, and only proceed on
            explicit user confirmation.
          - EmptySeedError is surfaced as a QMessageBox.warning.
          - ValueError (including invalid regex from core) is surfaced as a
            QMessageBox.warning with the error text.
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
        except ContentSearchUngatedError as exc:
            QMessageBox.warning(
                self,
                "Content search requires a pre-filter",
                (
                    "Content search cannot run without at least one name, extension,\n"
                    "or size pre-filter — it would scan every file in the tree.\n\n"
                    "Please set a name seed, extension, or size range first, then\n"
                    "add the content query.\n\n"
                    f"Details: {exc}"
                ),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid input", str(exc))
        except OSError as exc:
            QMessageBox.critical(self, "File system error", str(exc))

    # ------------------------------------------------------------------
    # Action helpers (called from _run)
    # ------------------------------------------------------------------

    def _do_save(self, path: str, kind: EntryKind, seed: str, entry_label: str) -> None:
        """Save list — low risk, no confirmation required.

        Passes case_sensitive to save_listing; passes all filter params to the
        supplementary list_entries call used for the result count.
        """
        core_kwargs = self._build_core_kwargs()
        list_kwargs = self._build_list_entries_kwargs()
        out_path = save_listing(path, kind, seed, **core_kwargs)
        entries = list_entries(path, kind, seed, **list_kwargs)
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

        Passes case_sensitive to remove_entries.
        Passes versioning=True when the versioning checkbox is checked (FFX-I08).
        """
        core_kwargs = self._build_core_kwargs()
        versioning = self._versioning_check.isChecked()
        if versioning:
            core_kwargs["versioning"] = True

        preview = remove_entries(path, kind, seed, dry_run=True, **core_kwargs)
        if not preview.matched:
            self._set_status(f"No {entry_label} was found — nothing was deleted.")
            return

        preview_text = self._build_preview_text(preview.matched, entry_label)
        versioning_note = (
            "\n\nFiles will be moved to .ffe-versions/ (recoverable)."
            if versioning else
            ""
        )
        reply = QMessageBox.question(
            self,
            "Confirm removal",
            (
                f"About to remove "
                f"{len(preview.matched)} {entry_label}(s):\n\n"
                f"{preview_text}\n\nProceed?{versioning_note}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            report = remove_entries(path, kind, seed, dry_run=False, confirm=True, **core_kwargs)
            msg = f"{len(report.removed)} {entry_label}(s) removed."
            if versioning and report.versioned_to:
                msg += f"  Versions saved to: {report.versioned_to}"
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

        Passes case_sensitive to compress_entries (which does not expose
        structured filters yet).
        """
        core_kwargs = self._build_core_kwargs()
        preview = compress_entries(path, kind, seed, dry_run=True, **core_kwargs)
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
            report = compress_entries(path, kind, seed, dry_run=False, confirm=True, **core_kwargs)
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
    # Settings / theme
    # ------------------------------------------------------------------

    def _apply_theme(self, theme, template_name: str) -> None:
        """Apply *theme* to the entire application and update stored state."""
        self._active_theme = theme
        self._active_template_name = template_name
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(theme))

    def _open_settings(self) -> None:
        """Open the Settings dialog; apply theme live on Apply / OK."""
        from ff_explorer.gui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(
            initial_theme=self._active_theme,
            initial_template_name=self._active_template_name,
            apply_callback=self._apply_theme,
            parent=self,
        )
        dlg.exec()
        # After OK the callback has already applied + persisted;
        # after Cancel the callback reverted to the original theme.

    def _open_disk_usage(self) -> None:
        """Open the Disk Usage / Largest Files view for the current root path (FFX-I11).

        Validates that a real root path is selected, calls
        ``largest_entries`` from the core, and presents the result in a
        ``LargestEntriesView`` embedded inside a non-modal QDialog.
        Non-destructive: no confirmation dialog is needed.
        """
        path_text = self._path_edit.text()
        if path_text == _PLACEHOLDER_PATH or not path_text.strip():
            QMessageBox.warning(self, "Warning!", "Select a root path first.")
            return

        from ff_explorer.core import largest_entries
        from ff_explorer.gui.treemap_view import LargestEntriesView

        try:
            entries = largest_entries(path_text, top_n=50)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Disk Usage", str(exc))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Disk Usage — Largest Files")
        dlg.resize(680, 520)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(4, 4, 4, 4)

        view = LargestEntriesView(parent=dlg)
        view.set_entries(entries)
        layout.addWidget(view)

        dlg.exec()

    # ------------------------------------------------------------------
    # Find duplicates (FFX-I06)
    # ------------------------------------------------------------------

    def _open_find_duplicates(self) -> None:
        """Open the Find Duplicates dialog for the current root path (FFX-I06).

        Calls dedupe.find_duplicates headlessly, then presents results grouped
        by content hash in a simple non-modal read-only QDialog.
        Non-destructive: no confirmation dialog is needed.
        """
        path_text = self._path_edit.text()
        if path_text == _PLACEHOLDER_PATH or not path_text.strip():
            QMessageBox.warning(self, "Warning!", "Select a root path first.")
            return

        try:
            groups = find_duplicates(path_text)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Find Duplicates", str(exc))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Find Duplicates")
        dlg.resize(700, 480)
        outer_layout = QVBoxLayout(dlg)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(6)

        if not groups:
            outer_layout.addWidget(QLabel("No duplicate files found."))
        else:
            total_wasted = sum(g.size * (len(g.paths) - 1) for g in groups)
            from ff_explorer.gui.treemap_view import _fmt_size
            summary = QLabel(
                f"{len(groups)} duplicate group(s) found.  "
                f"Wasted space: {_fmt_size(total_wasted)}"
            )
            outer_layout.addWidget(summary)

            list_widget = QListWidget()
            list_widget.setSelectionMode(
                QListWidget.SelectionMode.NoSelection
            )
            for grp in groups:
                list_widget.addItem(
                    f"--- Group (size {_fmt_size(grp.size)}, hash {grp.hash[:12]}...) ---"
                )
                for fpath in grp.paths:
                    list_widget.addItem(f"    {fpath}")
            outer_layout.addWidget(list_widget)

        dlg.exec()

    # ------------------------------------------------------------------
    # Batch rename (FFX-I07)
    # ------------------------------------------------------------------

    def _open_batch_rename(self) -> None:
        """Open the Batch Rename dialog (FFX-I07).

        Uses the same dry_run/confirm two-step safety pattern as remove/compress:
          1. Define a find/replace rule.
          2. Preview the old→new mapping (dry_run=True).
          3. Confirm → apply (dry_run=False, confirm=True).

        Destructive path: dialog defaults to No when confirming the apply.
        """
        path_text = self._path_edit.text()
        if path_text == _PLACEHOLDER_PATH or not path_text.strip():
            QMessageBox.warning(self, "Warning!", "Select a root path first.")
            return

        seed = self._seed_edit.text()
        if not seed.strip():
            QMessageBox.warning(
                self, "Batch Rename", "Set a name seed to select files to rename."
            )
            return

        # ---- Rule definition dialog ----
        rule_dlg = QDialog(self)
        rule_dlg.setWindowTitle("Batch Rename — Define Rule")
        rule_dlg.resize(420, 180)
        form = QFormLayout()

        find_edit = QLineEdit()
        find_edit.setPlaceholderText("Text to find in filename")
        replace_edit = QLineEdit()
        replace_edit.setPlaceholderText("Replacement text (empty = delete)")

        form.addRow("Find:", find_edit)
        form.addRow("Replace with:", replace_edit)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(rule_dlg.accept)
        btns.rejected.connect(rule_dlg.reject)

        outer_v = QVBoxLayout()
        outer_v.addLayout(form)
        outer_v.addWidget(btns)
        rule_dlg.setLayout(outer_v)

        if rule_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        find_text = find_edit.text()
        replace_text = replace_edit.text()

        if not find_text:
            QMessageBox.warning(self, "Batch Rename", "Find text must not be empty.")
            return

        rule = RenameRule(kind="find_replace", params={"find": find_text, "replace": replace_text})
        kind = self._current_kind()
        core_kwargs = self._build_core_kwargs()

        try:
            preview_report = rename_entries(
                path_text, kind, seed,
                rules=[rule],
                dry_run=True,
                **core_kwargs,
            )
        except EmptySeedError as exc:
            QMessageBox.warning(self, "Batch Rename", str(exc))
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Batch Rename", str(exc))
            return

        if not preview_report.mapping:
            self._set_status("Batch rename: no matching entries found.")
            return

        if preview_report.collisions:
            collision_text = "\n".join(preview_report.collisions[:10])
            QMessageBox.warning(
                self,
                "Batch Rename — Collision Detected",
                f"The rename cannot proceed due to collisions:\n\n{collision_text}",
            )
            return

        # ---- Preview dialog (shows mapping; confirm defaults to No) ----
        preview_lines = [
            f"{old}  →  {new}" for old, new in preview_report.mapping[:30]
        ]
        if len(preview_report.mapping) > 30:
            preview_lines.append(
                f"  ... and {len(preview_report.mapping) - 30} more"
            )
        preview_text = "\n".join(preview_lines)

        reply = QMessageBox.question(
            self,
            "Confirm Batch Rename",
            (
                f"About to rename {len(preview_report.mapping)} file(s):\n\n"
                f"{preview_text}\n\nApply?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._set_status("Batch rename cancelled.")
            return

        try:
            live_report = rename_entries(
                path_text, kind, seed,
                rules=[rule],
                dry_run=False,
                confirm=True,
                **core_kwargs,
            )
        except (EmptySeedError, ValueError) as exc:
            QMessageBox.warning(self, "Batch Rename", str(exc))
            return
        except OSError as exc:
            QMessageBox.critical(self, "Batch Rename — File system error", str(exc))
            return

        msg = f"Batch rename: {len(live_report.renamed)} file(s) renamed."
        if live_report.undo_file:
            msg += f"  Undo file: {live_report.undo_file}"
        if live_report.failed:
            msg += f"  {len(live_report.failed)} failure(s)."
        self._set_status(msg)

    # ------------------------------------------------------------------
    # Presets (FFX-I03)
    # ------------------------------------------------------------------

    def _save_preset(self) -> None:
        """Save the current form state as a named preset (FFX-I03)."""
        name, ok = QInputDialog.getText(
            self, "Save Preset", "Preset name:"
        )
        if not ok or not name.strip():
            return

        path_text = self._path_edit.text()
        if path_text == _PLACEHOLDER_PATH:
            path_text = ""

        action_label = self._action_combo.currentText()
        action_code = _ACTION_LABELS.get(action_label, -1)
        operation_map = {1: "list", 2: "remove", 3: "compress", -1: "list"}
        operation = operation_map.get(action_code, "list")

        preset = Preset(
            name=name.strip(),
            path=path_text,
            kind=self._current_kind().value,
            name_seed=self._seed_edit.text(),
            case_sensitive=self._get_case_sensitive(),
            match_mode=self._get_match_mode(),
            min_size=self._get_min_size(),
            max_size=self._get_max_size(),
            modified_after=self._get_modified_after(),
            modified_before=self._get_modified_before(),
            extensions=self._get_extensions(),
            respect_ignore=self._respect_ignore_check.isChecked(),
            ignore_globs=self._get_ignore_globs(),
            operation=operation,
        )

        try:
            save_preset(preset)
            self._set_status(f"Preset '{name.strip()}' saved.")
        except ValueError as exc:
            QMessageBox.warning(self, "Save Preset", str(exc))

    def _load_preset(self) -> None:
        """Load a saved preset back into the form (FFX-I03)."""
        presets = list_presets()
        if not presets:
            QMessageBox.information(
                self, "Load Preset", "No saved presets found."
            )
            return

        names = [p.name for p in presets]
        name, ok = QInputDialog.getItem(
            self, "Load Preset", "Select preset:", names, 0, False
        )
        if not ok or not name:
            return

        try:
            preset = get_preset(name)
        except KeyError as exc:
            QMessageBox.warning(self, "Load Preset", str(exc))
            return

        # Apply preset back into form fields
        if preset.path:
            self._path_edit.setText(preset.path)
        self._seed_edit.setText(preset.name_seed)

        # Kind: 0=FOLDERS → radio_folders; 1=FILES → radio_files
        if preset.kind == EntryKind.FILES.value:
            self._radio_files.setChecked(True)
        else:
            self._radio_folders.setChecked(True)

        # Match mode
        for label, core_val in _MATCH_MODE_LABELS.items():
            if core_val == preset.match_mode:
                idx = list(_MATCH_MODE_LABELS.keys()).index(label)
                self._match_mode_combo.setCurrentIndex(idx)
                break

        # Case sensitive
        self._case_sensitive_check.setChecked(preset.case_sensitive)

        # Size
        self._min_size_spin.setValue(
            (preset.min_size // 1024) if preset.min_size is not None else 0
        )
        self._max_size_spin.setValue(
            (preset.max_size // 1024) if preset.max_size is not None else 0
        )

        # Extensions
        self._extensions_edit.setText(
            ", ".join(preset.extensions) if preset.extensions else ""
        )

        # Ignore
        self._respect_ignore_check.setChecked(preset.respect_ignore)
        self._ignore_globs_edit.setText(
            ", ".join(preset.ignore_globs) if preset.ignore_globs else ""
        )

        # Action
        action_code_map = {"list": 1, "remove": 2, "compress": 3}
        target_code = action_code_map.get(preset.operation, -1)
        for label, code in _ACTION_LABELS.items():
            if code == target_code:
                idx = list(_ACTION_LABELS.keys()).index(label)
                self._action_combo.setCurrentIndex(idx)
                break

        self._set_status(f"Preset '{name}' loaded.")

    # ------------------------------------------------------------------
    # Live index toggle (FFX-I10)
    # ------------------------------------------------------------------

    def _toggle_live_index(self, checked: bool) -> None:
        """Start or stop the IndexManager observer for the current root (FFX-I10)."""
        path_text = self._path_edit.text()
        if path_text == _PLACEHOLDER_PATH or not path_text.strip():
            # Silently revert the checkbox — no path selected
            self._live_index_check.blockSignals(True)
            self._live_index_check.setChecked(False)
            self._live_index_check.blockSignals(False)
            QMessageBox.warning(
                self, "Live Index", "Select a root path before enabling live indexing."
            )
            return

        if checked:
            try:
                IndexManager.start_index(path_text)
                self._set_status(f"Live index started for: {path_text}")
            except ImportError as exc:
                self._live_index_check.blockSignals(True)
                self._live_index_check.setChecked(False)
                self._live_index_check.blockSignals(False)
                QMessageBox.warning(
                    self,
                    "Live Index — dependency missing",
                    f"Real-time indexing requires 'watchdog'.\n\n{exc}",
                )
            except (ValueError, OSError) as exc:
                self._live_index_check.blockSignals(True)
                self._live_index_check.setChecked(False)
                self._live_index_check.blockSignals(False)
                QMessageBox.warning(self, "Live Index", str(exc))
        else:
            try:
                IndexManager.stop_index(path_text)
                self._set_status(f"Live index stopped for: {path_text}")
            except Exception:
                pass  # stop is best-effort; always uncheck

    # ------------------------------------------------------------------
    # Exit
    # ------------------------------------------------------------------

    def _exit(self) -> None:
        """Clean shutdown (mirrors legacy exit() method)."""
        self.close()
        gc.collect()

    def closeEvent(self, event) -> None:
        """Handle the window close button and the context-menu Exit action.

        Stops the live index observer (FFX-I10) if active so no background
        thread leaks after the window is closed.
        """
        # FFX-I10: stop any active live index observer for the current root.
        path_text = self._path_edit.text()
        if (
            hasattr(self, "_live_index_check")
            and self._live_index_check.isChecked()
            and path_text != _PLACEHOLDER_PATH
            and path_text.strip()
        ):
            try:
                IndexManager.stop_index(path_text)
            except Exception:
                pass  # best-effort; never block close
        gc.collect()
        event.accept()

    # ------------------------------------------------------------------
    # Keyboard shortcut: Enter → Run  (handled via returnPressed on seed_edit
    # and QDialog.setDefault on run_btn)
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
            self._run()
        else:
            super().keyPressEvent(event)
