"""
FF Explorer — Qt translation helper (SPEC-21)
Juan García Sánchez, 2023-2026
License: GPLv3

Thin i18n seam for the FF Explorer PySide6 GUI.  All user-facing strings in
the GUI are wrapped with :func:`tr` so that:

  1. Without a QTranslator installed, ``QCoreApplication.translate`` returns
     the source string — the UI is unchanged in English (zero-cost fallback).
  2. With a QTranslator installed (via :func:`install_pseudo_locale` or a real
     .qm file), every string is automatically substituted by the translator.
  3. Standard Qt tooling (``pyside6-lupdate`` / ``lupdate``) can extract a
     base catalog from the source by scanning for ``tr()`` calls.

How to extract the base catalog and add a locale
-------------------------------------------------
1. Extract::

       pyside6-lupdate ff_explorer/gui/main_window.py \\
                       ff_explorer/gui/widget_info.py  \\
                       ff_explorer/gui/settings_dialog.py \\
                       ff_explorer/gui/i18n.py \\
           -ts ff_explorer/gui/translations/ffexplorer_en.ts

   ``lupdate`` (from Qt / PySide6-tools) produces a .ts XML file with all
   ``tr()``-wrapped source strings as the base catalog.

2. Translate the .ts file for a target locale (e.g. ``es``), naming it
   ``ffexplorer_es.ts``, and translate the ``<translation>`` elements.

3. Compile to binary::

       pyside6-lrelease ff_explorer/gui/translations/ffexplorer_es.ts \\
           -qm ff_explorer/gui/translations/ffexplorer_es.qm

4. Install at app startup::

       from PySide6.QtCore import QTranslator, QLocale, QLibraryInfo
       from ff_explorer.gui.i18n import install_translator
       # (or write a small loader that calls QTranslator.load + app.installTranslator)
       translator = QTranslator()
       translator.load("ffexplorer_es", "ff_explorer/gui/translations")
       QApplication.instance().installTranslator(translator)

The ``translations/`` directory is created as a placeholder; no compiled .qm
file is shipped — only the mechanism and extraction recipe are provided here.

Usage
-----
::

    from ff_explorer.gui.i18n import tr

    label = QLabel(tr("Root path"))
    btn   = QPushButton(tr("&Run"))          # mnemonic '&' preserved as-is
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QTranslator

#: Default translation context — matches the class/module namespace used for
#: pyside6-lupdate extraction.  All tr() calls in the GUI package use this.
_DEFAULT_CONTEXT = "FFExplorer"

# Module-level list of installed pseudo-locale translators so we can remove
# them cleanly even if the caller loses the reference.
_installed: list[QTranslator] = []


def tr(text: str, context: str = _DEFAULT_CONTEXT) -> str:
    """Return the translated form of *text* for *context*.

    Delegates to ``QCoreApplication.translate(context, text)``.  When no
    QTranslator is installed the call is a no-op and returns *text* unchanged,
    so the English UI is completely unaffected at runtime.

    Parameters
    ----------
    text:
        The source (English) string to translate.  This is the catalog key.
    context:
        The translation context used by Qt — defaults to ``"FFExplorer"``
        so that pyside6-lupdate groups all strings under a single context in
        the .ts catalog.

    Returns
    -------
    str
        The translated string, or *text* unchanged when no translator is active.

    Examples
    --------
    >>> from ff_explorer.gui.i18n import tr
    >>> tr("Run")     # no translator installed → "Run"
    'Run'
    """
    return QCoreApplication.translate(context, text)


# ---------------------------------------------------------------------------
# Pseudo-locale translator (QA / dev tool — proof-of-path mechanism)
# ---------------------------------------------------------------------------

class PseudoLocaleTranslator(QTranslator):
    """A QTranslator that visibly marks every source string for QA / dev use.

    Installed via :func:`install_pseudo_locale`, this translator wraps every
    source text in ``⟦…⟧`` Unicode brackets so that:

    * Any untranslated (unwrapped) string in the UI is immediately visible
      as a plain string — a quick visual audit of i18n coverage.
    * The pseudo-translated strings can be asserted in offscreen smoke tests
      without a real .ts/.qm file.

    The transform is deterministic: ``tr("Run")`` with this translator active
    returns ``"⟦Run⟧"``.

    Parameters
    ----------
    parent:
        Optional Qt parent object (usually None for a module-level translator).
    """

    def translate(
        self,
        context: bytes | str,
        sourceText: bytes | str,
        disambiguation: bytes | str | None = None,
        n: int = -1,
    ) -> str:
        """Return the visibly marked pseudo-translation of *sourceText*."""
        # Qt may pass bytes or str depending on the build/version.
        text = sourceText.decode() if isinstance(sourceText, bytes) else sourceText
        if not text:
            return ""
        return f"⟦{text}⟧"  # ⟦…⟧


def install_pseudo_locale(app) -> PseudoLocaleTranslator:
    """Install a :class:`PseudoLocaleTranslator` on *app* and return it.

    Calling this causes every :func:`tr` invocation to return the source text
    wrapped in ``⟦…⟧``.  Uninstall with :func:`remove_pseudo_locale`.

    Parameters
    ----------
    app:
        The ``QApplication`` (or ``QCoreApplication``) instance.

    Returns
    -------
    PseudoLocaleTranslator
        The translator that was installed — pass it to :func:`remove_pseudo_locale`.
    """
    translator = PseudoLocaleTranslator(app)
    app.installTranslator(translator)
    _installed.append(translator)
    return translator


def remove_pseudo_locale(app, translator: QTranslator | None = None) -> None:
    """Remove the pseudo-locale translator from *app*.

    Parameters
    ----------
    app:
        The ``QApplication`` / ``QCoreApplication`` instance.
    translator:
        The specific translator returned by :func:`install_pseudo_locale`.
        When ``None``, removes all pseudo-locale translators installed via
        this module.
    """
    if translator is not None:
        app.removeTranslator(translator)
        if translator in _installed:
            _installed.remove(translator)
    else:
        for t in list(_installed):
            app.removeTranslator(t)
        _installed.clear()
