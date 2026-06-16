"""
FF Explorer — Largest-files disk-usage view (FFX-I11)
Juan García Sánchez, 2023-2026
License: GPLv3

Provides a self-contained PySide6 widget that displays the N largest files
found by ``ff_explorer.core.largest_entries`` as a bar-chart list:
each file is shown as a row with a proportional size bar, the filename, and
a human-readable size label.

Public API
----------
``LargestEntriesView(parent=None)``
    Construct the widget.  Attach to any layout or show as a standalone window.

``LargestEntriesView.set_entries(entries)``
    Populate the view from a list of objects/named-tuples/dataclasses each
    carrying ``.path`` (str) and ``.size`` (int, bytes).  Clears previous
    contents.  Safe to call with an empty list.

``LargestEntriesView.entry_count() -> int``
    Return the number of entries currently displayed.

``LargestEntriesView.entry_at(index) -> tuple[str, int]``
    Return the (path, size) pair for the entry at *index*.  Entries are in
    descending size order (largest first) as received from the data source.

Design note
-----------
Uses a QScrollArea containing a vertical stack of fixed-height row widgets.
Each row is painted directly in its ``paintEvent`` to draw the proportional
bar without requiring additional Qt model/view classes.  This is reliable and
fully headless-safe under QT_QPA_PLATFORM=offscreen.
"""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ---------------------------------------------------------------------------
# Internal data record
# ---------------------------------------------------------------------------

class _Entry(NamedTuple):
    path: str
    size: int  # bytes


# ---------------------------------------------------------------------------
# Size formatter
# ---------------------------------------------------------------------------

def _fmt_size(n: int) -> str:
    """Return a human-readable size string for *n* bytes.

    Examples
    --------
    >>> _fmt_size(0)
    '0 B'
    >>> _fmt_size(1023)
    '1023 B'
    >>> _fmt_size(1024)
    '1.00 KB'
    >>> _fmt_size(1_048_576)
    '1.00 MB'
    >>> _fmt_size(1_073_741_824)
    '1.00 GB'
    """
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.2f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.2f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


# ---------------------------------------------------------------------------
# Row widget — one file entry with a proportional bar
# ---------------------------------------------------------------------------

_ROW_HEIGHT = 28       # px — fixed height for each row
_BAR_COLOR = QColor(70, 130, 180)      # steel-blue bar
_BAR_BG_COLOR = QColor(220, 220, 220)  # light-grey background for bar area
_TEXT_COLOR = QColor(20, 20, 20)       # near-black text
_BAR_AREA_WIDTH = 120  # px — width reserved for the proportional bar


class _EntryRow(QWidget):
    """A single row: [bar_area | filename label | size label].

    The bar fills *ratio* × _BAR_AREA_WIDTH pixels proportionally to the
    largest entry in the set.
    """

    def __init__(
        self,
        path: str,
        size: int,
        size_label: str,
        ratio: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ratio = ratio
        self._path = path
        self.setFixedHeight(_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip(path)

        # Layout: bar placeholder (fixed width) + filename + size
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QHBoxLayout
        row = QHBoxLayout()
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        # Fixed-width spacer for the bar area (drawn in paintEvent)
        bar_spacer = QWidget()
        bar_spacer.setFixedWidth(_BAR_AREA_WIDTH)
        bar_spacer.setFixedHeight(_ROW_HEIGHT - 4)
        bar_spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bar_spacer.setAutoFillBackground(False)
        self._bar_widget = bar_spacer
        row.addWidget(bar_spacer)

        # Filename (truncated to basename for readability; full path in tooltip)
        name = Path(path).name
        name_lbl = QLabel(name)
        name_lbl.setToolTip(path)
        name_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        name_lbl.setStyleSheet("font: 10pt Verdana; color: #141414;")
        row.addWidget(name_lbl)

        # Human-readable size (right-aligned)
        size_lbl = QLabel(size_label)
        size_lbl.setFixedWidth(80)
        size_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        size_lbl.setStyleSheet("font: 10pt Verdana; color: #444444;")
        row.addWidget(size_lbl)

        outer.addLayout(row)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Draw the proportional size bar behind the bar-spacer area."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Bar area rect (matches the bar_spacer widget position)
        bar_rect = self._bar_widget.geometry()
        bar_x = bar_rect.x()
        bar_y = bar_rect.y()
        bar_h = bar_rect.height()
        bar_w = bar_rect.width()

        # Background
        painter.fillRect(bar_x, bar_y, bar_w, bar_h, _BAR_BG_COLOR)

        # Filled portion
        filled_w = max(1, int(bar_w * self._ratio)) if self._ratio > 0 else 0
        if filled_w > 0:
            painter.fillRect(bar_x, bar_y, filled_w, bar_h, _BAR_COLOR)

        # Border
        painter.setPen(QPen(QColor(160, 160, 160), 1))
        painter.drawRect(bar_x, bar_y, bar_w - 1, bar_h - 1)

        painter.end()


# ---------------------------------------------------------------------------
# Main public widget
# ---------------------------------------------------------------------------

class LargestEntriesView(QWidget):
    """Display the N largest files as a proportional bar list.

    Consume data from ``ff_explorer.core.largest_entries`` (or any iterable
    of objects with ``.path: str`` and ``.size: int`` attributes).

    Usage::

        view = LargestEntriesView()
        entries = largest_entries("/some/path", top_n=20)
        view.set_entries(entries)
        view.show()
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_Entry] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Disk Usage — Largest Files")
        self.setMinimumSize(560, 320)
        self.resize(640, 480)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(4)

        # Header row
        header = QLabel("Largest files (by size, descending)")
        header.setStyleSheet("font: bold 11pt Arial; color: #222222; padding: 4px;")
        outer.addWidget(header)

        # Column headers
        from PySide6.QtWidgets import QHBoxLayout
        col_row = QHBoxLayout()
        col_row.setContentsMargins(4, 0, 4, 0)
        col_row.setSpacing(6)

        bar_hdr = QLabel("Size (relative)")
        bar_hdr.setFixedWidth(_BAR_AREA_WIDTH)
        bar_hdr.setStyleSheet("font: bold 9pt Arial; color: #555555;")
        col_row.addWidget(bar_hdr)

        name_hdr = QLabel("File name")
        name_hdr.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        name_hdr.setStyleSheet("font: bold 9pt Arial; color: #555555;")
        col_row.addWidget(name_hdr)

        size_hdr = QLabel("Size")
        size_hdr.setFixedWidth(80)
        size_hdr.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        size_hdr.setStyleSheet("font: bold 9pt Arial; color: #555555;")
        col_row.addWidget(size_hdr)

        outer.addLayout(col_row)

        # Scroll area for entry rows
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        outer.addWidget(self._scroll_area)

        # Container widget inside the scroll area
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(1)
        self._container_layout.addStretch()
        self._scroll_area.setWidget(self._container)

        # Status label (shows count)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font: 9pt Arial; color: #666666; padding: 2px;")
        outer.addWidget(self._status_label)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_entries(self, entries: list) -> None:
        """Populate the view with *entries*.

        Parameters
        ----------
        entries:
            Any iterable of objects with ``.path: str`` and ``.size: int``
            attributes (e.g. ``SizedEntry`` from ``ff_explorer.core``).
            The caller is responsible for ordering (``largest_entries``
            returns descending by size).  An empty list clears the view.
        """
        # Convert to internal records (validates attributes, copies data)
        self._entries = [_Entry(path=e.path, size=e.size) for e in entries]
        self._rebuild_rows()

    def entry_count(self) -> int:
        """Return the number of entries currently displayed."""
        return len(self._entries)

    def entry_at(self, index: int) -> tuple[str, int]:
        """Return the (path, size) tuple for *index* (0-based, descending by size)."""
        e = self._entries[index]
        return (e.path, e.size)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rebuild_rows(self) -> None:
        """Clear old rows and build fresh ones from self._entries."""
        # Remove all items from the container layout (except the trailing stretch)
        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        if not self._entries:
            self._status_label.setText("No entries to display.")
            return

        max_size = self._entries[0].size  # already sorted descending

        for entry in self._entries:
            ratio = (entry.size / max_size) if max_size > 0 else 0.0
            row = _EntryRow(
                path=entry.path,
                size=entry.size,
                size_label=_fmt_size(entry.size),
                ratio=ratio,
                parent=self._container,
            )
            # Insert before the trailing stretch
            insert_pos = self._container_layout.count() - 1
            self._container_layout.insertWidget(insert_pos, row)

        n = len(self._entries)
        self._status_label.setText(
            f"{n} file{'s' if n != 1 else ''} listed  |  "
            f"Largest: {_fmt_size(self._entries[0].size)}"
        )
