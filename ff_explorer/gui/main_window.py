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

Extended filter controls (FFX-I04/I05/I09/SPEC-17):
    Content contains — QLineEdit (FFX-I09): content_query; gated by core
    Search in archives — QCheckBox (FFX-I05): search_archives=True
    Respect .gitignore/.ignore — QCheckBox (FFX-I04): respect_ignore=True
    Extra ignore globs — QLineEdit (FFX-I04): ignore_globs (comma/space split)
    Include hidden/system — QCheckBox (SPEC-17): include_hidden=False when unchecked

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

from PySide6.QtCore import QDate, QDateTime, QObject, QThread, Qt, QTimeZone, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
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
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWhatsThis,
    QWidget,
)

from ff_explorer.gui.theme import build_stylesheet, load_saved_theme
from ff_explorer.gui.widget_info import info_text, register_info, register_info_text

from ff_explorer import (
    EmptySeedError,
    EntryKind,
    ListingResult,
    MatchEntry,
    SkippedEntry,
    compress_entries,
    copy_entries,
    entry_metadata,
    iter_entries,
    list_entries,
    move_entries,
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
# Off-thread scan worker (SPEC-14)
# ---------------------------------------------------------------------------

# Number of entries between progress() signal emissions during the scan.
_PROGRESS_INTERVAL = 50


class _ScanWorker(QObject):
    """Consumes :func:`iter_entries` on a background QThread.

    Communicates exclusively via Qt signals — no QWidget access ever occurs
    from the worker thread.  The worker is designed to be moved onto a QThread
    via ``moveToThread``; its ``run`` slot is invoked by connecting it to the
    thread's ``started`` signal.

    Signals
    -------
    progress(int count, str current_path)
        Emitted every ``_PROGRESS_INTERVAL`` entries during the scan.
        ``count`` is the number of entries collected so far; ``current_path``
        is the string representation of the most-recently yielded entry.
    finished(list)
        Emitted when the scan completes normally (not cancelled).
        Carries the full list of :class:`MatchEntry` objects.
    error(object)
        Emitted when the generator raises an exception.
        Carries the exception instance so the main thread can handle it.

    Cancel contract
    ---------------
    Call :meth:`cancel` from the main thread at any time before or during the
    scan.  The worker checks the flag between every ``yield``; once cancelled,
    neither ``finished`` nor ``error`` is emitted — the worker returns silently.
    Cancellation targets only the *scan/preview* phase.  A confirmed mutation
    (dry_run=False) is never launched from this worker, so there is nothing
    to cancel there.
    """

    progress = Signal(int, str)
    finished = Signal(list)
    # SPEC-15: emitted after finished with a (possibly empty) list of SkippedEntry
    # objects for every path that could not be accessed during the walk.
    skipped = Signal(list)
    error = Signal(object)

    def __init__(
        self,
        path: str,
        kind: EntryKind,
        seed: str,
        list_kwargs: dict,
    ) -> None:
        super().__init__()
        self._path = path
        self._kind = kind
        self._seed = seed
        self._list_kwargs = list_kwargs
        self._cancelled: bool = False

    # ------------------------------------------------------------------
    # Public API — called from the main thread only
    # ------------------------------------------------------------------

    def cancel(self) -> None:
        """Set the cooperative cancel flag.  Thread-safe (simple bool write)."""
        self._cancelled = True

    # ------------------------------------------------------------------
    # Slot — invoked by QThread.started signal on the worker thread
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Consume ``iter_entries`` and emit progress/finished/skipped/error.

        No QWidget access occurs here.  All results are marshalled to the
        main thread via signals.

        SPEC-15: collects skipped paths via the iter_entries ``_skipped``
        parameter.  When the scan completes normally, ``finished`` is emitted
        with the matched entries list, then ``skipped`` is emitted with the
        (possibly empty) list of SkippedEntry objects.
        """
        try:
            collected: list[MatchEntry] = []
            skipped_entries: list[SkippedEntry] = []
            gen = iter_entries(
                self._path, self._kind, self._seed,
                _skipped=skipped_entries,
                **self._list_kwargs,
            )
            for entry in gen:
                if self._cancelled:
                    return  # silent exit — neither finished nor error emitted
                collected.append(entry)
                if len(collected) % _PROGRESS_INTERVAL == 0:
                    self.progress.emit(len(collected), str(entry.path))
            if not self._cancelled:
                self.finished.emit(collected)
                self.skipped.emit(skipped_entries)
        except Exception as exc:  # noqa: BLE001
            if not self._cancelled:
                self.error.emit(exc)


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
    "Copy list": 4,
    "Move list": 5,
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
        path_label.setObjectName("sectionLabel")
        register_info(path_label, "path")
        outer.addWidget(path_label)

        path_row = QHBoxLayout()
        self._path_edit = _ClickableLineEdit(
            _PLACEHOLDER_PATH, on_click=lambda: self._browse_path()
        )
        self._path_edit.setReadOnly(True)
        self._path_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        register_info(self._path_edit, "path")
        # Clicking the read-only field opens the folder picker — handled by
        # _ClickableLineEdit.mousePressEvent (calls super() then on_click)
        path_row.addWidget(self._path_edit)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(72)
        register_info(browse_btn, "path_browse")
        browse_btn.clicked.connect(self._browse_path)
        path_row.addWidget(browse_btn)
        outer.addLayout(path_row)

        # ---- Name seed section ----
        seed_label = QLabel("Name seed")
        seed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        seed_label.setObjectName("sectionLabel")
        register_info(seed_label, "seed")
        outer.addWidget(seed_label)

        self._seed_edit = QLineEdit()
        register_info(self._seed_edit, "seed")
        self._seed_edit.returnPressed.connect(self._run)
        outer.addWidget(self._seed_edit)

        # ---- Mode radio buttons (Folders / Files) ----
        mode_row = QHBoxLayout()
        self._mode_group = QButtonGroup(self)
        self._radio_folders = QRadioButton("Folders")
        self._radio_folders.setChecked(True)  # d_type default = 0 (FOLDERS)
        register_info(self._radio_folders, "mode_folders")
        self._mode_group.addButton(self._radio_folders, EntryKind.FOLDERS.value)
        mode_row.addWidget(self._radio_folders)

        self._radio_files = QRadioButton("Files")
        register_info(self._radio_files, "mode_files")
        self._mode_group.addButton(self._radio_files, EntryKind.FILES.value)
        mode_row.addWidget(self._radio_files)
        outer.addLayout(mode_row)

        # ---- Action combobox ----
        self._action_combo = QComboBox()
        self._action_combo.addItems(list(_ACTION_LABELS.keys()))
        # Build combined tooltip for the combobox (action name + detail)
        self._action_combo.currentIndexChanged.connect(self._update_action_tooltip)
        self._update_action_tooltip()  # set initial tooltip
        outer.addWidget(self._action_combo)

        # ---- Run button ----
        run_btn = QPushButton("Run")
        run_btn.setFixedWidth(80)
        run_btn.setObjectName("runButton")
        run_btn.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        run_btn.setDefault(True)
        register_info(run_btn, "run")
        run_btn.clicked.connect(self._run)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(run_btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        # ---- Filters toggle button (FFX-I01 / FFX-I02) ----
        self._filters_toggle_btn = QPushButton("Filters ▶")
        register_info(self._filters_toggle_btn, "filters_toggle")
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
        register_info(settings_btn, "settings")
        settings_btn.clicked.connect(self._open_settings)

        settings_row = QHBoxLayout()
        settings_row.addStretch()
        settings_row.addWidget(settings_btn)
        outer.addLayout(settings_row)

        # ---- Disk usage button (FFX-I11) ----
        disk_usage_btn = QPushButton("Disk usage")
        disk_usage_btn.setFixedWidth(100)
        register_info(disk_usage_btn, "disk_usage")
        disk_usage_btn.clicked.connect(self._open_disk_usage)

        disk_usage_row = QHBoxLayout()
        disk_usage_row.addStretch()
        disk_usage_row.addWidget(disk_usage_btn)
        outer.addLayout(disk_usage_row)

        # ---- Find duplicates button (FFX-I06) ----
        dup_btn = QPushButton("Find duplicates")
        dup_btn.setFixedWidth(130)
        register_info(dup_btn, "find_duplicates")
        dup_btn.clicked.connect(self._open_find_duplicates)

        dup_row = QHBoxLayout()
        dup_row.addStretch()
        dup_row.addWidget(dup_btn)
        outer.addLayout(dup_row)

        # ---- Batch rename button (FFX-I07) ----
        rename_btn = QPushButton("Batch rename")
        rename_btn.setFixedWidth(130)
        register_info(rename_btn, "batch_rename")
        rename_btn.clicked.connect(self._open_batch_rename)

        rename_row = QHBoxLayout()
        rename_row.addStretch()
        rename_row.addWidget(rename_btn)
        outer.addLayout(rename_row)

        # ---- Preset save/load row (FFX-I03) ----
        preset_save_btn = QPushButton("Save preset")
        preset_save_btn.setFixedWidth(110)
        register_info(preset_save_btn, "preset_save")
        preset_save_btn.clicked.connect(self._save_preset)

        preset_load_btn = QPushButton("Load preset")
        preset_load_btn.setFixedWidth(110)
        register_info(preset_load_btn, "preset_load")
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
        register_info(self._live_index_check, "live_index")
        self._live_index_check.toggled.connect(self._toggle_live_index)

        # ---- Shift+F1 shortcut: enter WhatsThis mode (SPEC-04) ----
        whats_this_shortcut = QShortcut(QKeySequence("Shift+F1"), self)
        whats_this_shortcut.activated.connect(QWhatsThis.enterWhatsThisMode)

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
        register_info(self._match_mode_combo, "filter_match_mode")
        match_row.addWidget(self._match_mode_combo)

        self._case_sensitive_check = QCheckBox("Case sensitive")
        self._case_sensitive_check.setChecked(True)
        register_info(self._case_sensitive_check, "filter_case_sensitive")
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
        register_info(self._min_size_spin, "filter_min_size")
        size_row.addWidget(self._min_size_spin)

        size_row.addWidget(QLabel("–"))

        self._max_size_spin = QSpinBox()
        self._max_size_spin.setRange(0, 10_000_000)
        self._max_size_spin.setValue(0)
        self._max_size_spin.setSpecialValueText("–")  # 0 displays as "–" (no bound)
        register_info(self._max_size_spin, "filter_max_size")
        size_row.addWidget(self._max_size_spin)

        layout.addLayout(size_row)

        # ---- Date filters (modified after / before) ----
        after_row = QHBoxLayout()
        self._date_after_check = QCheckBox("Modified after:")
        self._date_after_check.setChecked(False)
        register_info(self._date_after_check, "filter_date_after")
        after_row.addWidget(self._date_after_check)

        self._date_after_edit = QDateEdit()
        self._date_after_edit.setCalendarPopup(True)
        self._date_after_edit.setDate(QDate.currentDate().addDays(-30))
        self._date_after_edit.setEnabled(False)
        register_info(self._date_after_edit, "filter_date_after_edit")
        after_row.addWidget(self._date_after_edit)

        layout.addLayout(after_row)

        self._date_after_check.toggled.connect(self._date_after_edit.setEnabled)

        before_row = QHBoxLayout()
        self._date_before_check = QCheckBox("Modified before:")
        self._date_before_check.setChecked(False)
        register_info(self._date_before_check, "filter_date_before")
        before_row.addWidget(self._date_before_check)

        self._date_before_edit = QDateEdit()
        self._date_before_edit.setCalendarPopup(True)
        self._date_before_edit.setDate(QDate.currentDate())
        self._date_before_edit.setEnabled(False)
        register_info(self._date_before_edit, "filter_date_before_edit")
        before_row.addWidget(self._date_before_edit)

        layout.addLayout(before_row)

        self._date_before_check.toggled.connect(self._date_before_edit.setEnabled)

        # ---- Extensions filter ----
        ext_row = QHBoxLayout()
        ext_label = QLabel("Extensions:")
        ext_row.addWidget(ext_label)

        self._extensions_edit = QLineEdit()
        self._extensions_edit.setPlaceholderText(".txt, .md, .log")
        register_info(self._extensions_edit, "filter_extensions")
        ext_row.addWidget(self._extensions_edit)

        layout.addLayout(ext_row)

        # ---- Content search (FFX-I09) ----
        content_row = QHBoxLayout()
        content_label = QLabel("Content contains:")
        content_row.addWidget(content_label)

        self._content_query_edit = QLineEdit()
        self._content_query_edit.setPlaceholderText("grep pattern (requires name/type/size pre-filter)")
        register_info(self._content_query_edit, "filter_content_query")
        content_row.addWidget(self._content_query_edit)

        layout.addLayout(content_row)

        # ---- Archive transparency (FFX-I05) ----
        self._search_archives_check = QCheckBox("Search inside archives")
        self._search_archives_check.setChecked(False)
        register_info(self._search_archives_check, "filter_search_archives")
        layout.addWidget(self._search_archives_check)

        # ---- Ignore-file awareness (FFX-I04) ----
        self._respect_ignore_check = QCheckBox("Respect .gitignore/.ignore")
        self._respect_ignore_check.setChecked(False)
        register_info(self._respect_ignore_check, "filter_respect_ignore")
        layout.addWidget(self._respect_ignore_check)

        ignore_globs_row = QHBoxLayout()
        ignore_globs_label = QLabel("Extra ignore globs:")
        ignore_globs_row.addWidget(ignore_globs_label)

        self._ignore_globs_edit = QLineEdit()
        self._ignore_globs_edit.setPlaceholderText("*.pyc, __pycache__/")
        register_info(self._ignore_globs_edit, "filter_ignore_globs")
        ignore_globs_row.addWidget(self._ignore_globs_edit)

        layout.addLayout(ignore_globs_row)

        # ---- Versioned delete checkbox (FFX-I08) — shown only for Remove action ----
        self._versioning_check = QCheckBox("Version (move to .ffe-versions) instead of recycle bin")
        self._versioning_check.setChecked(False)
        register_info(self._versioning_check, "filter_versioning")
        layout.addWidget(self._versioning_check)

        # ---- Include hidden/system entries (SPEC-17) ----
        self._include_hidden_check = QCheckBox("Include hidden/system entries")
        self._include_hidden_check.setChecked(True)  # default True = current behaviour
        register_info(self._include_hidden_check, "filter_include_hidden")
        layout.addWidget(self._include_hidden_check)

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

        # SPEC-17: include_hidden — only add param when False (True is the default)
        if not self._include_hidden_check.isChecked():
            kwargs["include_hidden"] = False

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
        """Update the action combobox tooltip to include per-action detail.

        Sources both parts from the registry:
          base  = info_text("action")
          detail = info_text("action_detail.<code>"), falls back to "" if absent.
        Uses register_info_text so the _ff_info_key property is set to "action"
        and all four widget-info setters (tooltip, accessible description,
        whatsThis, _ff_info_key) are applied consistently.
        """
        label = self._action_combo.currentText()
        code = _ACTION_LABELS.get(label, -1)
        base = info_text("action")
        try:
            detail = info_text(f"action_detail.{code}")
        except KeyError:
            detail = ""
        register_info_text(self._action_combo, base + detail, "action")

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
        Validate inputs and start an off-thread scan (SPEC-14).

        Input validation is performed synchronously on the main thread.
        The actual scan is delegated to a ``_ScanWorker`` moved onto a
        ``QThread``; a ``QProgressDialog`` keeps the window responsive and
        lets the user cancel.

        Safety gate is preserved:
          - The worker always performs the *scan* phase only.
          - For Remove/Compress, the main thread shows the dry-run preview
            and only on explicit Yes performs the mutation (inline, on the
            main thread, after ``QMessageBox.question`` returns).
          - EmptySeedError / ContentSearchUngatedError / ValueError / OSError
            from the worker are routed back via the ``error`` signal and
            surfaced by the same ``QMessageBox`` calls as before.
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

        self._start_scan(action_code, path, kind, seed, entry_label)

    # ------------------------------------------------------------------
    # Off-thread scan orchestration (SPEC-14)
    # ------------------------------------------------------------------

    def _start_scan(
        self,
        action_code: int,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
    ) -> None:
        """Launch a ``_ScanWorker`` on a background ``QThread``.

        Shows a ``QProgressDialog`` with a Cancel button that sets the
        worker's cooperative cancel flag.  Wires ``finished`` and ``error``
        signals to main-thread handlers that complete the action.  The
        thread and worker are cleaned up automatically on completion.
        """
        list_kwargs = self._build_list_entries_kwargs()

        # Build the worker and move it to a background thread.
        worker = _ScanWorker(path, kind, seed, list_kwargs)
        thread = QThread(self)
        worker.moveToThread(thread)

        # ---- Progress dialog ----
        progress_dlg = QProgressDialog(
            f"Scanning for {entry_label}(s)…",
            "Cancel",
            0,
            0,          # maximum=0 → indeterminate busy bar
            self,
        )
        progress_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        progress_dlg.setMinimumDuration(0)  # show immediately
        progress_dlg.setValue(0)

        # Cancel button wires the worker's cooperative flag.
        # Note: ``canceled`` (US spelling) is the PySide6 signal name.
        progress_dlg.canceled.connect(worker.cancel)

        # ---- Update progress label on each progress emission ----
        def _on_progress(count: int, current: str) -> None:
            progress_dlg.setLabelText(
                f"Scanning for {entry_label}(s)… {count} found\n{current}"
            )

        # SPEC-15: accumulate the skipped signal payload here so that
        # _on_finished (which fires first) can close the progress dialog, then
        # _on_skipped (which fires second) can forward the collected skips to
        # _on_scan_complete.  A simple list cell acts as mutable state shared
        # between the two closures.
        _pending: dict = {"entries": [], "skipped_done": False, "skipped": []}

        # ---- Finished: close progress dialog, then dispatch post-scan action ----
        def _on_finished(entries: list) -> None:
            progress_dlg.close()
            _pending["entries"] = entries
            # The skipped signal may arrive in the same event-loop tick or the
            # next; we wait for it before dispatching.  In practice both signals
            # are emitted synchronously inside run() before the thread exits, so
            # the skipped slot fires immediately after this one in the same
            # processEvents() sweep.
            _pending.setdefault("finished_called", True)

        # ---- Skipped: fires immediately after finished (SPEC-15) ----
        def _on_skipped(skipped: list) -> None:
            _cleanup()
            self._on_scan_complete(
                action_code, path, kind, seed, entry_label,
                _pending["entries"], skipped,
            )

        # ---- Error: close progress dialog, surface the exception ----
        def _on_error(exc: object) -> None:
            progress_dlg.close()
            _cleanup()
            self._handle_scan_error(exc)

        # ---- Thread lifecycle cleanup ----
        def _cleanup() -> None:
            thread.quit()
            thread.wait()
            # Lifecycle tidiness: drop the worker and thread once the thread has
            # fully stopped (wait() guarantees run() returned — no use-after-free).
            worker.deleteLater()
            thread.deleteLater()

        # Wire signals (all delivered on the main thread via the Qt event loop).
        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.skipped.connect(_on_skipped)  # SPEC-15
        worker.error.connect(_on_error)

        # Start thread → triggers worker.run() via started signal.
        thread.started.connect(worker.run)
        thread.start()

        progress_dlg.exec()   # enters a local event loop; returns when closed

    def _handle_scan_error(self, exc: object) -> None:
        """Route worker error signal back to the same QMessageBox handlers as before."""
        if isinstance(exc, EmptySeedError):
            QMessageBox.warning(self, "Empty seed", str(exc))
        elif isinstance(exc, ContentSearchUngatedError):
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
        elif isinstance(exc, ValueError):
            QMessageBox.warning(self, "Invalid input", str(exc))
        elif isinstance(exc, OSError):
            QMessageBox.critical(self, "File system error", str(exc))
        else:
            QMessageBox.critical(self, "Unexpected error", str(exc))

    def _on_scan_complete(
        self,
        action_code: int,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
        entries: list[MatchEntry],
        skipped: "list[SkippedEntry] | None" = None,
    ) -> None:
        """Dispatch to the correct post-scan handler on the main thread.

        Flow (SPEC-19 design):
          1. Surface skip report in status bar (SPEC-15).
          2. Open the results view dialog showing the matched entries (SPEC-19).
             The dialog is non-blocking for the chosen action — it opens, lets
             the user inspect entries and properties, then returns to allow
             Save / Remove / Compress to proceed.  It does NOT gate the action;
             the existing safety dialogs (QMessageBox.question for Remove/Compress)
             remain the gate.  This way Save/Remove/Compress flows are preserved.
          3. Dispatch to the action handler (unchanged).
        """
        # SPEC-15: surface skip count
        skipped = skipped or []
        if skipped:
            self._set_status(
                f"{len(skipped)} path(s) skipped (permission/access errors). "
                "Click 'Show skipped' in the results view for details."
            )

        # SPEC-19: show results view (always, for any action including Save/Remove/Compress)
        # SPEC-18: results view now returns the subset of user-selected paths (or None
        # when "Apply to all" was chosen or for non-selectable actions like Save).
        selected_paths = self._show_results_view(entries, skipped, entry_label, action_code)

        if action_code == 1:
            # Save: always acts on the full set (save_listing has no only_paths);
            # subset-apply for Save would just save the selected paths which is
            # surprising — full-set behaviour is the least-surprising choice here.
            self._do_save(path, kind, seed, entry_label, entries)
        elif action_code == 2:
            self._do_remove(path, kind, seed, entry_label, entries, only_paths=selected_paths)
        elif action_code == 3:
            self._do_compress(path, kind, seed, entry_label, entries, only_paths=selected_paths)
        elif action_code == 4:
            self._do_copy(path, kind, seed, entry_label, entries, only_paths=selected_paths)
        elif action_code == 5:
            self._do_move(path, kind, seed, entry_label, entries, only_paths=selected_paths)

    # ------------------------------------------------------------------
    # Results / properties view (SPEC-19)
    # ------------------------------------------------------------------

    def _show_results_view(
        self,
        entries: list[MatchEntry],
        skipped: "list[SkippedEntry]",
        entry_label: str,
        action_code: int = -1,
    ) -> "list[str] | None":
        """Open the results dialog (SPEC-19 / SPEC-18) after a scan completes.

        Shows matched entries in a QTableWidget with columns:
          Name | Path | Type | Size | Modified

        SPEC-18 multi-select:
          The table supports extended multi-row selection.  When the user has
          rows selected and clicks "Apply to selected (N)", this method returns
          a list of absolute path strings for those rows (excluding any
          archive-internal entries, which cannot be acted on destructively or
          copied/moved).  When the user clicks "Apply to all" or closes the
          dialog without selecting an action, ``None`` is returned, preserving
          the legacy full-set behaviour.

          For the Save action (action_code == 1) only "Apply to all" is shown
          because save_listing has no only_paths parameter.

        Parameters
        ----------
        entries:
            Matched entries from the scan worker.
        skipped:
            Entries that could not be accessed during the scan (SPEC-15).
        entry_label:
            "file" or "folder" for display strings.
        action_code:
            The selected action code from _ACTION_LABELS.  Governs which
            apply buttons are shown.

        Returns
        -------
        list[str] | None
            The list of selected (non-archive-internal) absolute path strings
            when the user chose "Apply to selected", or ``None`` for "Apply to
            all" / close-without-action (legacy full-set behaviour).
        """
        # Mutable container shared by closures for the return value.
        _result: dict = {"only_paths": None}

        dlg = QDialog(self)
        dlg.setWindowTitle(
            f"Results — {len(entries)} {entry_label}(s) found"
            + (f"  ({len(skipped)} skipped)" if skipped else "")
        )
        dlg.resize(780, 520)
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # Summary label
        summary_lbl = QLabel(
            f"{len(entries)} {entry_label}(s) found."
            + (f"  {len(skipped)} path(s) skipped." if skipped else "")
            + "\n(Ctrl+click or Shift+click to select multiple rows for subset action.)"
        )
        outer.addWidget(summary_lbl)

        # Table: Name | Path | Type | Size | Modified
        _COL_NAME = 0
        _COL_PATH = 1
        _COL_TYPE = 2
        _COL_SIZE = 3
        _COL_MODIFIED = 4
        _HEADERS = ["Name", "Path", "Type", "Size (bytes)", "Modified"]

        table = QTableWidget(len(entries), len(_HEADERS), dlg)
        table.setHorizontalHeaderLabels(_HEADERS)
        # SPEC-18: ExtendedSelection enables Ctrl+click and Shift+click multi-select
        table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        from PySide6.QtWidgets import QAbstractItemView
        table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(
            _COL_PATH, QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)

        for row, entry in enumerate(entries):
            p = entry.path
            name_item = QTableWidgetItem(p.name if hasattr(p, "name") else str(p).rsplit("/", 1)[-1])
            path_item = QTableWidgetItem(str(p))
            # Type, Size, Modified deferred — populated on row selection via
            # currentRowChanged; pre-fill with placeholder dashes for now.
            table.setItem(row, _COL_NAME, name_item)
            table.setItem(row, _COL_PATH, path_item)
            table.setItem(row, _COL_TYPE, QTableWidgetItem(""))
            table.setItem(row, _COL_SIZE, QTableWidgetItem(""))
            table.setItem(row, _COL_MODIFIED, QTableWidgetItem(""))

        # Lazy metadata fetch: populate Type/Size/Modified for the selected row.
        _meta_cache: dict[int, dict] = {}

        def _fetch_meta_for_row(row: int) -> dict | None:
            if row in _meta_cache:
                return _meta_cache[row]
            if row < 0 or row >= len(entries):
                return None
            try:
                meta = entry_metadata(str(entries[row].path))
                _meta_cache[row] = meta
                return meta
            except (OSError, FileNotFoundError):
                return None

        def _on_row_changed(current_row: int) -> None:
            meta = _fetch_meta_for_row(current_row)
            if meta is None:
                return
            import datetime as _dt
            size_str = str(meta.get("size_bytes", ""))
            mtime = meta.get("mtime")
            if mtime is not None:
                try:
                    mtime_str = _dt.datetime.fromtimestamp(
                        mtime, tz=_dt.timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")
                except (OSError, OverflowError, ValueError):
                    mtime_str = str(mtime)
            else:
                mtime_str = ""
            table.item(current_row, _COL_TYPE).setText(str(meta.get("type", "")))
            table.item(current_row, _COL_SIZE).setText(size_str)
            table.item(current_row, _COL_MODIFIED).setText(mtime_str)

        # currentCellChanged(currentRow, currentCol, previousRow, previousCol)
        # is the correct QTableWidget signal for row-change notification.
        table.currentCellChanged.connect(
            lambda cur_row, _cc, _pr, _pc: _on_row_changed(cur_row)
        )
        # Pre-select first row so properties are visible immediately
        if entries:
            table.selectRow(0)

        outer.addWidget(table)

        # ------------------------------------------------------------------
        # SPEC-18: Apply-to-selected / Apply-to-all button row
        # ------------------------------------------------------------------
        # Helper: collect selected paths, excluding archive-internal entries.
        def _collect_selected_paths() -> "tuple[list[str], int]":
            """Return (non_archive_paths, excluded_archive_count)."""
            selected_rows = {idx.row() for idx in table.selectedIndexes()}
            non_archive: list[str] = []
            excluded = 0
            for row in sorted(selected_rows):
                if row < 0 or row >= len(entries):
                    continue
                p = entries[row].path
                p_str = str(p)
                # Archive-internal entries have '!' in their path (zip-internal notation)
                # or carry in_archive=True if the MatchEntry has that attribute.
                is_archive_internal = (
                    "!" in p_str
                    or getattr(entries[row], "in_archive", False)
                )
                if is_archive_internal:
                    excluded += 1
                else:
                    non_archive.append(p_str)
            return non_archive, excluded

        # The "Apply to selected" button (disabled when no rows are selected)
        apply_selected_btn = QPushButton("Apply to selected (0)")
        register_info(apply_selected_btn, "results_apply_selected")
        apply_selected_btn.setEnabled(False)

        # The "Apply to all" button (always enabled)
        apply_all_btn = QPushButton(f"Apply to all ({len(entries)})")
        register_info(apply_all_btn, "results_apply_all")
        apply_all_btn.setEnabled(bool(entries))

        # Keep "Apply to selected" label and enabled state in sync with selection.
        def _update_apply_selected_btn() -> None:
            selected_rows = {idx.row() for idx in table.selectedIndexes()}
            n = len(selected_rows)
            apply_selected_btn.setText(f"Apply to selected ({n})")
            apply_selected_btn.setEnabled(n > 0)

        table.itemSelectionChanged.connect(_update_apply_selected_btn)

        def _on_apply_selected() -> None:
            paths, excluded = _collect_selected_paths()
            if excluded > 0:
                QMessageBox.information(
                    dlg,
                    "Archive-internal entries excluded",
                    f"{excluded} archive-internal entry/entries were excluded from the "
                    "selection — they cannot be acted on destructively or copied/moved.",
                )
            if not paths:
                # All selected rows were archive-internal; nothing to act on.
                self._set_status(
                    "All selected entries are archive-internal; no action was taken."
                )
                dlg.accept()
                return
            _result["only_paths"] = paths
            dlg.accept()

        def _on_apply_all() -> None:
            _result["only_paths"] = None  # None = legacy full-set
            dlg.accept()

        apply_selected_btn.clicked.connect(_on_apply_selected)
        apply_all_btn.clicked.connect(_on_apply_all)

        # Button rows
        action_btn_row = QHBoxLayout()
        # For Save (code=1), only "Apply to all" is meaningful because save_listing
        # has no only_paths — show only that button to avoid a misleading "Apply to
        # selected" that would silently act on the full set anyway.
        if action_code != 1:
            action_btn_row.addWidget(apply_selected_btn)
        action_btn_row.addWidget(apply_all_btn)
        action_btn_row.addStretch()

        # Properties / skipped / close row
        btn_row = QHBoxLayout()

        props_btn = QPushButton("Properties")
        register_info(props_btn, "results_properties")
        props_btn.setEnabled(bool(entries))

        def _open_properties() -> None:
            row = table.currentRow()
            if row < 0 or row >= len(entries):
                return
            meta = _fetch_meta_for_row(row)
            self._show_entry_properties(entries[row].path, meta)

        props_btn.clicked.connect(_open_properties)
        btn_row.addWidget(props_btn)

        if skipped:
            skip_btn = QPushButton(f"Show skipped ({len(skipped)})")
            register_info(skip_btn, "results_show_skipped")

            def _open_skipped() -> None:
                self._show_skipped_dialog(skipped)

            skip_btn.clicked.connect(_open_skipped)
            btn_row.addWidget(skip_btn)

        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)

        outer.addLayout(action_btn_row)
        outer.addLayout(btn_row)
        dlg.exec()

        return _result["only_paths"]

    def _show_entry_properties(self, path, meta: "dict | None") -> None:
        """Open a small read-only properties dialog for *path* (SPEC-19 §2).

        Shows: path, type, size, created/modified times, permission summary.
        ``meta`` is the dict from ``entry_metadata``; when None (e.g. path is
        archive-internal or unreadable) the dialog shows blanks gracefully.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Properties — {path}")
        dlg.resize(480, 260)
        form = QFormLayout()
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        def _row(label: str, value: str) -> None:
            lbl = QLabel(value)
            lbl.setWordWrap(True)
            form.addRow(QLabel(label), lbl)

        _row("Path:", str(path))

        if meta:
            import datetime as _dt
            _row("Type:", str(meta.get("type", "")))
            size_bytes = meta.get("size_bytes", 0)
            _row("Size:", f"{size_bytes:,} bytes")
            mtime = meta.get("mtime")
            if mtime is not None:
                try:
                    mtime_str = _dt.datetime.fromtimestamp(
                        mtime, tz=_dt.timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")
                except (OSError, OverflowError, ValueError):
                    mtime_str = str(mtime)
            else:
                mtime_str = "(unavailable)"
            _row("Modified:", mtime_str)
            _row("Exists:", str(meta.get("exists", True)))
        else:
            _row("Metadata:", "(unavailable — path may be archive-internal or unreadable)")

        outer_v = QVBoxLayout()
        outer_v.addLayout(form)
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        outer_v.addLayout(btn_row)
        dlg.setLayout(outer_v)
        dlg.exec()

    def _show_skipped_dialog(self, skipped: "list[SkippedEntry]") -> None:
        """Open a read-only dialog listing skipped paths and reasons (SPEC-15)."""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Skipped paths ({len(skipped)})")
        dlg.resize(640, 400)
        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        outer.addWidget(QLabel(
            f"{len(skipped)} path(s) could not be accessed during the scan:"
        ))

        list_wgt = QListWidget()
        list_wgt.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        for se in skipped:
            list_wgt.addItem(f"{se.path}  —  {se.reason}")
        outer.addWidget(list_wgt)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)
        dlg.exec()

    # ------------------------------------------------------------------
    # Action helpers (called from _on_scan_complete — main thread only)
    # ------------------------------------------------------------------

    def _do_save(
        self,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
        entries: list[MatchEntry],
    ) -> None:
        """Save list — low risk, no confirmation required.

        Receives the pre-scanned *entries* from the worker so the save call
        never re-scans the tree.  Passes case_sensitive to save_listing.
        """
        core_kwargs = self._build_core_kwargs()
        out_path = save_listing(path, kind, seed, **core_kwargs)
        if entries:
            self._set_status(f"Directory saved to {out_path}.")
        else:
            self._set_status(f"No {entry_label} was found — nothing was saved.")

    def _do_remove(
        self,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
        entries: list[MatchEntry],
        only_paths: "list[str] | None" = None,
    ) -> None:
        """
        Remove list — SAFETY GATE (SPEC-14 / SPEC-18 update):
          1. The off-thread worker already scanned and collected matched entries
             (scan played the role of the dry-run preview).
          2. Show confirmation dialog with the acted-on paths (main thread).
             When only_paths is set (subset mode), the dialog lists the subset;
             when None, the full matched set is listed.
          3. Only on Yes: call remove_entries(dry_run=False, confirm=True) on the
             main thread.  Cancel of a *confirmed* mutation is out of scope; the
             scan/preview phase is the only cancellable step.

        SPEC-18: only_paths narrows the acted-on set.  None = legacy full-set.
        Passes case_sensitive to remove_entries.
        Passes versioning=True when the versioning checkbox is checked (FFX-I08).
        """
        if not entries:
            self._set_status(f"No {entry_label} was found — nothing was deleted.")
            return

        core_kwargs = self._build_core_kwargs()
        versioning = self._versioning_check.isChecked()
        if versioning:
            core_kwargs["versioning"] = True

        # SPEC-18: determine the display set for the confirmation dialog.
        if only_paths is not None:
            from pathlib import Path as _Path
            display_paths = [_Path(p) for p in only_paths]
            subset_note = f"\n(Subset: {len(only_paths)} of {len(entries)} matched entries)"
        else:
            display_paths = [e.path for e in entries]
            subset_note = ""

        preview_text = self._build_preview_text(display_paths, entry_label)
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
                f"{len(display_paths)} {entry_label}(s):{subset_note}\n\n"
                f"{preview_text}\n\nProceed?{versioning_note}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            extra: dict = {}
            if only_paths is not None:
                extra["only_paths"] = only_paths
            report = remove_entries(path, kind, seed, dry_run=False, confirm=True, **core_kwargs, **extra)
            msg = f"{len(report.removed)} {entry_label}(s) removed."
            if versioning and report.versioned_to:
                msg += f"  Versions saved to: {report.versioned_to}"
            if report.failed:
                msg += f"  {len(report.failed)} removal(s) failed."
            self._set_status(msg)
        else:
            self._set_status("Removal cancelled.")

    def _do_compress(
        self,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
        entries: list[MatchEntry],
        only_paths: "list[str] | None" = None,
    ) -> None:
        """
        Compress list — SAFETY GATE (SPEC-14 / SPEC-18 update, same pattern as _do_remove):
          1. The off-thread worker already scanned and collected matched entries.
          2. Show confirmation dialog on the main thread (originals deleted after
             compression — note this clearly).
          3. Only on Yes: call compress_entries(dry_run=False, confirm=True) on the
             main thread.

        SPEC-18: only_paths narrows the acted-on set.  None = legacy full-set.
        Passes case_sensitive to compress_entries.
        """
        if not entries:
            self._set_status(f"No {entry_label} was found — nothing was compressed.")
            return

        core_kwargs = self._build_core_kwargs()

        # SPEC-18: determine the display set for the confirmation dialog.
        if only_paths is not None:
            from pathlib import Path as _Path
            display_paths = [_Path(p) for p in only_paths]
            subset_note = f"\n(Subset: {len(only_paths)} of {len(entries)} matched entries)"
        else:
            display_paths = [e.path for e in entries]
            subset_note = ""

        preview_text = self._build_preview_text(display_paths, entry_label)
        reply = QMessageBox.question(
            self,
            "Confirm compression",
            (
                f"About to compress {len(display_paths)} {entry_label}(s):{subset_note}\n\n"
                f"{preview_text}\n\n"
                "Originals will be deleted after compression.  Proceed?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            extra: dict = {}
            if only_paths is not None:
                extra["only_paths"] = only_paths
            report = compress_entries(path, kind, seed, dry_run=False, confirm=True, **core_kwargs, **extra)
            msg = f"{len(report.archives)} archive(s) created."
            if report.failed:
                msg += f"  {len(report.failed)} compression/delete(s) failed."
            self._set_status(msg)
        else:
            self._set_status("Compression cancelled.")

    def _do_copy(
        self,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
        entries: list[MatchEntry],
        only_paths: "list[str] | None" = None,
    ) -> None:
        """
        Copy list — SAFETY GATE (SPEC-18):
          1. Prompt for a destination directory via QFileDialog.
          2. Dry-run copy_entries to build the preview list.
          3. Show QMessageBox.question (default No) with preview + destination.
          4. Only on Yes: call copy_entries(dry_run=False, confirm=True).

        SPEC-18: only_paths narrows the acted-on set.  None = legacy full-set.
        Passes case_sensitive via core_kwargs.
        """
        if not entries:
            self._set_status(f"No {entry_label} was found — nothing was copied.")
            return

        destination = QFileDialog.getExistingDirectory(
            self,
            "FF Explorer — destination for Copy",
            "",
        )
        if not destination:
            self._set_status("Copy cancelled — no destination selected.")
            return

        core_kwargs = self._build_core_kwargs()
        extra: dict = {}
        if only_paths is not None:
            extra["only_paths"] = only_paths

        # SPEC-18: determine the display set for the confirmation dialog.
        if only_paths is not None:
            from pathlib import Path as _Path
            display_paths = [_Path(p) for p in only_paths]
            subset_note = f"\n(Subset: {len(only_paths)} of {len(entries)} matched entries)"
        else:
            display_paths = [e.path for e in entries]
            subset_note = ""

        preview_text = self._build_preview_text(display_paths, entry_label)
        reply = QMessageBox.question(
            self,
            "Confirm copy",
            (
                f"About to copy {len(display_paths)} {entry_label}(s){subset_note}\n"
                f"to: {destination}\n\n"
                f"{preview_text}\n\nProceed?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            report = copy_entries(
                path, kind, seed,
                destination=destination,
                dry_run=False,
                confirm=True,
                **core_kwargs,
                **extra,
            )
            msg = f"{len(report.transferred)} {entry_label}(s) copied to {destination}."
            if report.failed:
                msg += f"  {len(report.failed)} copy failure(s)."
            self._set_status(msg)
        else:
            self._set_status("Copy cancelled.")

    def _do_move(
        self,
        path: str,
        kind: EntryKind,
        seed: str,
        entry_label: str,
        entries: list[MatchEntry],
        only_paths: "list[str] | None" = None,
    ) -> None:
        """
        Move list — SAFETY GATE (SPEC-18, same pattern as _do_copy):
          1. Prompt for a destination directory via QFileDialog.
          2. Show QMessageBox.question (default No) with preview + destination.
          3. Only on Yes: call move_entries(dry_run=False, confirm=True).

        SPEC-18: only_paths narrows the acted-on set.  None = legacy full-set.
        Passes case_sensitive via core_kwargs.
        """
        if not entries:
            self._set_status(f"No {entry_label} was found — nothing was moved.")
            return

        destination = QFileDialog.getExistingDirectory(
            self,
            "FF Explorer — destination for Move",
            "",
        )
        if not destination:
            self._set_status("Move cancelled — no destination selected.")
            return

        core_kwargs = self._build_core_kwargs()
        extra: dict = {}
        if only_paths is not None:
            extra["only_paths"] = only_paths

        # SPEC-18: determine the display set for the confirmation dialog.
        if only_paths is not None:
            from pathlib import Path as _Path
            display_paths = [_Path(p) for p in only_paths]
            subset_note = f"\n(Subset: {len(only_paths)} of {len(entries)} matched entries)"
        else:
            display_paths = [e.path for e in entries]
            subset_note = ""

        preview_text = self._build_preview_text(display_paths, entry_label)
        reply = QMessageBox.question(
            self,
            "Confirm move",
            (
                f"About to move {len(display_paths)} {entry_label}(s){subset_note}\n"
                f"to: {destination}\n\n"
                f"{preview_text}\n\nProceed?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            report = move_entries(
                path, kind, seed,
                destination=destination,
                dry_run=False,
                confirm=True,
                **core_kwargs,
                **extra,
            )
            msg = f"{len(report.transferred)} {entry_label}(s) moved to {destination}."
            if report.failed:
                msg += f"  {len(report.failed)} move failure(s)."
            self._set_status(msg)
        else:
            self._set_status("Move cancelled.")

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
