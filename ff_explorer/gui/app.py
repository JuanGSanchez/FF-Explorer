"""
FF Explorer — PySide6 GUI entry point
Juan García Sánchez, 2023-2026
License: GPLv3

Entry point declared in pyproject.toml:
    [project.gui-scripts]
    ff-explorer-gui = "ff_explorer.gui.app:main"

Usage:
    ff-explorer-gui          # installed console-script (windowless on Windows via gui-scripts)
    python -m ff_explorer.gui.app   # direct module execution
"""

import sys

from PySide6.QtWidgets import QApplication

from ff_explorer.gui.main_window import MainWindow


def main() -> int:
    """
    Create the QApplication, show the main window, and enter the event loop.

    Returns the Qt exit code so that sys.exit() can propagate it cleanly.
    High-DPI scaling is enabled by default in PySide6 6.x — no explicit
    Qt.AA_EnableHighDpiScaling attribute call is needed.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("FF Explorer")
    app.setApplicationVersion("1.0.0")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
