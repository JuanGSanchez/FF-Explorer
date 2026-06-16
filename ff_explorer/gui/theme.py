"""
FF Explorer — centralized colour theming
Juan García Sánchez, 2023-2026
License: GPLv3

Pure colour model — no QWidget construction at import time.

Exports
-------
Theme          : dataclass of named colour roles
LIGHT / DARK   : built-in template instances
contrast_ratio : WCAG relative-luminance helper
validate_theme : returns a list of violation strings (empty = OK)
build_stylesheet: generate a QSS string from a Theme
load_saved_theme / save_theme : persistence via a JSON user-config file
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Theme dataclass — one named role per widget category
# ---------------------------------------------------------------------------

@dataclass
class Theme:
    """Named colour roles covering every widget category used by FF Explorer.

    All values are CSS hex strings (e.g. ``"#FFFFFF"``).
    """

    # ---- Window / surface backgrounds ----
    window_bg: str = "#F3F3F3"
    """Main window chrome background."""

    panel_bg: str = "#FFFFFF"
    """Central content/surface — must be visibly distinct from window_bg."""

    alt_row_bg: str = "#F0F0F0"
    """Alternating row tint in list/tree views."""

    # ---- Text colours ----
    text_primary: str = "#1A1A1A"
    """Body text — must meet WCAG AA (≥4.5:1) vs both panel_bg and window_bg."""

    text_secondary: str = "#6B6B6B"
    """Secondary/metadata text — lower contrast accepted (≥4.5:1 recommended)."""

    disabled_text: str = "#9D9D9D"
    """Greyed-out / disabled widget text."""

    label_text: str = "#1A1A1A"
    """Section header labels (QLabel used as category headings)."""

    radio_text: str = "#1A1A1A"
    """QRadioButton text colour."""

    # ---- Border / divider ----
    border: str = "#D6D6D6"
    """Widget border / separator colour."""

    # ---- Accent ----
    accent: str = "#0067C0"
    """Primary brand / selection accent (focus rings, links)."""

    # ---- Selection ----
    selection_bg: str = "#CCE4F7"
    """Item selection background in list/tree/table views."""

    selection_text: str = "#1A1A1A"
    """Text colour on a selected item."""

    # ---- Buttons ----
    button_bg: str = "#FBFBFB"
    """Default button background."""

    button_hover_bg: str = "#F0F0F0"
    """Button background on mouse hover."""

    button_border: str = "#D1D1D1"
    """Button border colour."""

    button_text: str = "#1A1A1A"
    """Button label text."""

    # ---- Input fields ----
    input_bg: str = "#FFFFFF"
    """QLineEdit / editable field background."""

    input_text: str = "#1A1A1A"
    """QLineEdit text colour."""

    # ---- Header (column headers in list/tree) ----
    header_bg: str = "#ECECEC"
    """QHeaderView section background."""

    header_text: str = "#1A1A1A"
    """QHeaderView section text."""

    # ---- Destructive affordance ----
    destructive_accent: str = "#C42B1C"
    """Colour used in the destructive-action confirm dialog affordance (border/icon tint)."""

    # ---- Status bar ----
    status_bar_bg: str = "#F0F0F0"
    """QStatusBar background."""

    status_bar_text: str = "#1A1A1A"
    """QStatusBar message text."""

    # ---- Tooltip ----
    tooltip_bg: str = "#FFFFCC"
    """QToolTip background."""

    tooltip_text: str = "#1A1A1A"
    """QToolTip text colour."""

    # ---- Scrollbars ----
    scrollbar_bg: str = "#F0F0F0"
    """Scrollbar track (trough) background."""

    scrollbar_handle: str = "#C1C1C1"
    """Scrollbar handle (thumb) colour."""


# ---------------------------------------------------------------------------
# Built-in templates
# ---------------------------------------------------------------------------

#: Light theme — File Explorer / Chrome light idiom
LIGHT = Theme(
    window_bg="#F3F3F3",
    panel_bg="#FFFFFF",
    alt_row_bg="#F0F0F0",      # contrast ratio vs panel_bg #FFFFFF = 1.14 (distinct)
    text_primary="#1A1A1A",    # contrast vs panel_bg = 17.40, vs window_bg = 15.68 (WCAG AA)
    text_secondary="#6B6B6B",  # contrast vs panel_bg = 5.33 (WCAG AA)
    disabled_text="#9D9D9D",
    label_text="#1A1A1A",
    radio_text="#1A1A1A",
    border="#D6D6D6",
    accent="#0067C0",
    selection_bg="#CCE4F7",    # contrast ratio vs panel_bg = 1.31 (distinct)
    selection_text="#1A1A1A",
    button_bg="#FBFBFB",
    button_hover_bg="#F0F0F0",
    button_border="#D1D1D1",
    button_text="#1A1A1A",
    input_bg="#FFFFFF",
    input_text="#1A1A1A",
    header_bg="#ECECEC",
    header_text="#1A1A1A",
    destructive_accent="#C42B1C",
    status_bar_bg="#F0F0F0",
    status_bar_text="#1A1A1A",
    tooltip_bg="#FFFFCC",
    tooltip_text="#1A1A1A",
    scrollbar_bg="#F0F0F0",
    scrollbar_handle="#C1C1C1",
)

#: Dark theme — Chrome / Win11 dark idiom
DARK = Theme(
    window_bg="#161616",       # deep base; contrast vs panel_bg = 1.30 (distinct)
    panel_bg="#2C2C2C",        # main surface
    alt_row_bg="#212121",      # contrast ratio vs panel_bg = 1.15 (distinct banding)
    text_primary="#E8E8E8",    # contrast vs panel_bg = 11.40, vs window_bg = 14.77 (WCAG AA)
    text_secondary="#9E9E9E",  # contrast vs panel_bg = 5.21 (WCAG AA)
    disabled_text="#6B6B6B",
    label_text="#E8E8E8",
    radio_text="#E8E8E8",
    border="#4D4D4D",          # contrast ratio vs panel_bg = 1.65 (clearly visible)
    accent="#4CC2FF",
    selection_bg="#193D6A",    # contrast ratio vs panel_bg = 1.27 (distinct)
    selection_text="#FFFFFF",
    button_bg="#333333",
    button_hover_bg="#404040",
    button_border="#505050",
    button_text="#E8E8E8",
    input_bg="#232323",
    input_text="#E8E8E8",
    header_bg="#1E1E1E",
    header_text="#E8E8E8",
    destructive_accent="#F1707B",
    status_bar_bg="#101010",
    status_bar_text="#E8E8E8",
    tooltip_bg="#333333",
    tooltip_text="#E8E8E8",
    scrollbar_bg="#1E1E1E",
    scrollbar_handle="#555555",
)

#: Registry of built-in template names → Theme instances
BUILTIN_THEMES: dict[str, Theme] = {
    "Light": LIGHT,
    "Dark": DARK,
}


# ---------------------------------------------------------------------------
# Colour-theory helpers
# ---------------------------------------------------------------------------

def _linearise(c: float) -> float:
    """sRGB → linear light component (IEC 61966-2-1)."""
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(hex_color: str) -> float:
    """WCAG 2.1 relative luminance for a CSS hex colour string."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = h[0] * 2 + h[1] * 2 + h[2] * 2
    r = _linearise(int(h[0:2], 16) / 255.0)
    g = _linearise(int(h[2:4], 16) / 255.0)
    b = _linearise(int(h[4:6], 16) / 255.0)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Return the WCAG contrast ratio between two CSS hex colour strings.

    Range: 1.0 (identical) … 21.0 (black on white).
    WCAG AA requires ≥4.5 for body text, ≥3.0 for large text.
    """
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# validate_theme
# ---------------------------------------------------------------------------

#: Minimum WCAG contrast ratio for body text (WCAG AA level).
_MIN_TEXT_CONTRAST = 4.5

#: Minimum contrast ratio between adjacent surfaces (ensures visible distinction).
#: 1.10 = 10% lighter/darker, perceptible at typical viewing distances.
_MIN_ADJACENCY_RATIO = 1.10


def validate_theme(theme: Theme) -> list[str]:
    """Check colour-theory constraints; return a list of violation strings.

    An empty list means the theme is fully compliant.

    Checks
    ------
    1. ``text_primary`` vs ``panel_bg`` and ``window_bg`` must be ≥ 4.5:1 (WCAG AA).
    2. ``text_secondary`` vs ``panel_bg`` must be ≥ 4.5:1 (WCAG AA body text).
    3. Adjacent surfaces must have a contrast ratio ≥ 1.10 so they are not
       indistinguishable: window_bg vs panel_bg, panel_bg vs alt_row_bg,
       selection_bg vs panel_bg, border vs panel_bg.
    """
    violations: list[str] = []

    # 1 & 2 — text contrast
    text_checks = [
        ("text_primary", "panel_bg", _MIN_TEXT_CONTRAST),
        ("text_primary", "window_bg", _MIN_TEXT_CONTRAST),
        ("text_secondary", "panel_bg", _MIN_TEXT_CONTRAST),
    ]
    theme_dict = asdict(theme)
    for fg_role, bg_role, minimum in text_checks:
        cr = contrast_ratio(theme_dict[fg_role], theme_dict[bg_role])
        if cr < minimum:
            violations.append(
                f"Contrast {fg_role} vs {bg_role} = {cr:.2f} (need ≥ {minimum})"
            )

    # 3 — adjacent surface distinction
    adjacency_pairs = [
        ("window_bg", "panel_bg"),
        ("panel_bg", "alt_row_bg"),
        ("selection_bg", "panel_bg"),
        ("border", "panel_bg"),
    ]
    for role_a, role_b in adjacency_pairs:
        cr = contrast_ratio(theme_dict[role_a], theme_dict[role_b])
        if cr < _MIN_ADJACENCY_RATIO:
            violations.append(
                f"Adjacent surfaces {role_a} vs {role_b} are too similar: "
                f"ratio = {cr:.2f} (need ≥ {_MIN_ADJACENCY_RATIO})"
            )

    return violations


# ---------------------------------------------------------------------------
# build_stylesheet
# ---------------------------------------------------------------------------

def build_stylesheet(theme: Theme) -> str:
    """Generate a Qt Style Sheet (QSS) string from *theme*.

    Styles every widget category present in FF Explorer's main window:
    QMainWindow, QWidget, QPushButton (+:hover, :disabled), QLineEdit,
    QTreeView/QListView/QTableView (+::item:selected, alternate-row),
    QHeaderView, QLabel, QComboBox, QCheckBox, QRadioButton, QStatusBar,
    QToolTip, QScrollBar, QMenu.
    """
    t = theme  # alias for brevity

    return f"""
/* ---- Window chrome / base surfaces ---- */
QMainWindow {{
    background-color: {t.window_bg};
}}
QWidget {{
    background-color: {t.panel_bg};
    color: {t.text_primary};
}}

/* ---- Labels ---- */
QLabel {{
    color: {t.label_text};
    background-color: transparent;
}}

/* ---- Buttons ---- */
QPushButton {{
    background-color: {t.button_bg};
    color: {t.button_text};
    border: 1px solid {t.button_border};
    border-radius: 4px;
    padding: 4px 10px;
}}
QPushButton:hover {{
    background-color: {t.button_hover_bg};
    border-color: {t.accent};
}}
QPushButton:disabled {{
    background-color: {t.button_bg};
    color: {t.disabled_text};
    border-color: {t.border};
}}
QPushButton:pressed {{
    background-color: {t.button_hover_bg};
}}

/* ---- Input fields ---- */
QLineEdit {{
    background-color: {t.input_bg};
    color: {t.input_text};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 3px;
    selection-background-color: {t.selection_bg};
    selection-color: {t.selection_text};
}}
QLineEdit:focus {{
    border-color: {t.accent};
}}
QLineEdit:disabled {{
    color: {t.disabled_text};
}}

/* ---- ComboBox ---- */
QComboBox {{
    background-color: {t.button_bg};
    color: {t.text_primary};
    border: 1px solid {t.button_border};
    border-radius: 3px;
    padding: 2px 6px;
}}
QComboBox:hover {{
    border-color: {t.accent};
}}
QComboBox QAbstractItemView {{
    background-color: {t.panel_bg};
    color: {t.text_primary};
    selection-background-color: {t.selection_bg};
    selection-color: {t.selection_text};
    border: 1px solid {t.border};
}}

/* ---- Radio buttons / checkboxes ---- */
QRadioButton {{
    color: {t.radio_text};
    spacing: 6px;
}}
QRadioButton:disabled {{
    color: {t.disabled_text};
}}
QCheckBox {{
    color: {t.text_primary};
    spacing: 6px;
}}
QCheckBox:disabled {{
    color: {t.disabled_text};
}}

/* ---- List / Tree / Table views ---- */
QTreeView, QListView, QTableView {{
    background-color: {t.panel_bg};
    alternate-background-color: {t.alt_row_bg};
    color: {t.text_primary};
    border: 1px solid {t.border};
    gridline-color: {t.border};
    selection-background-color: {t.selection_bg};
    selection-color: {t.selection_text};
}}
QTreeView::item:selected, QListView::item:selected, QTableView::item:selected {{
    background-color: {t.selection_bg};
    color: {t.selection_text};
}}
QTreeView::item:hover, QListView::item:hover {{
    background-color: {t.button_hover_bg};
}}

/* ---- Column headers ---- */
QHeaderView {{
    background-color: {t.header_bg};
}}
QHeaderView::section {{
    background-color: {t.header_bg};
    color: {t.header_text};
    border: 1px solid {t.border};
    padding: 3px 6px;
}}

/* ---- Status bar ---- */
QStatusBar {{
    background-color: {t.status_bar_bg};
    color: {t.status_bar_text};
    border-top: 1px solid {t.border};
}}

/* ---- Tooltip ---- */
QToolTip {{
    background-color: {t.tooltip_bg};
    color: {t.tooltip_text};
    border: 1px solid {t.border};
    padding: 2px 4px;
}}

/* ---- Menu ---- */
QMenu {{
    background-color: {t.panel_bg};
    color: {t.text_primary};
    border: 1px solid {t.border};
}}
QMenu::item:selected {{
    background-color: {t.selection_bg};
    color: {t.selection_text};
}}

/* ---- Scrollbars ---- */
QScrollBar:vertical {{
    background-color: {t.scrollbar_bg};
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background-color: {t.scrollbar_handle};
    min-height: 20px;
    border-radius: 6px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {t.accent};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background-color: {t.scrollbar_bg};
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background-color: {t.scrollbar_handle};
    min-width: 20px;
    border-radius: 6px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {t.accent};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---- Dialog base ---- */
QDialog {{
    background-color: {t.window_bg};
    color: {t.text_primary};
}}
""".strip()


# ---------------------------------------------------------------------------
# Persistence — load / save to JSON user-config file
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    """Return the path to the theme JSON config file.

    Uses ``QT_CONF_DIR`` env-var override for tests; otherwise falls back to
    the platform user-config directory via ``QStandardPaths`` if Qt is
    available, or ``~/.config/ff-explorer`` as a stdlib fallback.
    """
    override = os.environ.get("FFE_THEME_CONFIG_DIR")
    if override:
        return Path(override) / "theme.json"

    try:
        from PySide6.QtCore import QStandardPaths
        dirs = QStandardPaths.standardLocations(
            QStandardPaths.StandardLocation.AppConfigLocation
        )
        if dirs:
            return Path(dirs[0]) / "ff-explorer" / "theme.json"
    except Exception:
        pass

    return Path.home() / ".config" / "ff-explorer" / "theme.json"


def load_saved_theme() -> tuple[Theme, str]:
    """Load the saved theme from the user config file.

    Returns
    -------
    (Theme, template_name)
        The loaded theme and the template name (``"Light"``, ``"Dark"``, or
        ``"Custom"``).  Defaults to ``(LIGHT, "Light")`` if no config exists
        or the file is invalid.
    """
    path = _config_path()
    if not path.exists():
        return LIGHT, "Light"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        template_name: str = data.get("template", "Light")
        overrides: dict = data.get("overrides", {})

        # Start from a built-in base if named, else Light
        base = BUILTIN_THEMES.get(template_name, LIGHT)
        base_dict = asdict(base)
        # Apply saved overrides (only recognised field names)
        valid_fields = {f for f in base_dict}
        for k, v in overrides.items():
            if k in valid_fields and isinstance(v, str):
                base_dict[k] = v
        return Theme(**base_dict), template_name
    except Exception:
        return LIGHT, "Light"


def save_theme(theme: Theme, template_name: str = "Custom") -> None:
    """Persist *theme* to the user config file.

    Parameters
    ----------
    theme:
        The theme to save.
    template_name:
        ``"Light"``, ``"Dark"``, or ``"Custom"``.
    """
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Compute overrides relative to the built-in base (or store all if Custom)
    base = BUILTIN_THEMES.get(template_name, LIGHT)
    base_dict = asdict(base)
    theme_dict = asdict(theme)
    overrides = {k: v for k, v in theme_dict.items() if v != base_dict.get(k)}

    data = {
        "template": template_name,
        "overrides": overrides,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
