# RESEARCH REPORT — PySide6 Best Practices (RR-1, FF-Explorer Phase-B)

- Request ID: RR-1
- Status: COMPLETE
- Researcher: The Researcher
- Compiled: 2026-06-25
- Purpose: Ground a new `pyside6-best-practices.md` instruction for FF-Explorer (PySide6 GUI over a UI-independent core; Python 3.11 baseline, 3.13 ceiling).
- Citation policy (C1): every finding carries a source. Accessed dates = 2026-06-25 unless noted.

---

## 1. Current stable release line + Python compatibility + licensing

- **Latest stable: PySide6 6.11.1**, released 2026-05-13 (PyPI). The 6.11.x line is the current production-stable Qt for Python series; it wraps the **Qt 6.11** framework. [S1][S4]
- **Python support: 3.10–3.14.** Package metadata declares `Requires-Python >=3.10, <3.15` with classifiers for 3.10, 3.11, 3.12, 3.13, 3.14. **Python 3.13 is fully supported** by the current line. (Historical note: very early 3.13.0 + older PySide6 combos failed to install; resolved in current wheels — pin a current PySide6 if targeting 3.13.) [S1][S8]
- **FF-Explorer fit:** 3.11 baseline and 3.13 ceiling both fall inside the supported window. Recommend pinning a current 6.11.x (or the project's chosen ≥6.8 LTS-aligned minor) rather than an unbounded range.
- **Licensing:** Distributed under **LGPLv3 OR GPLv2 OR GPLv3**, with a separate commercial license available. Under LGPLv3, dynamic linking against an unmodified PySide6/Qt keeps an application's own code under its own terms, provided LGPL relinking/replacement obligations are honored (ship the Qt libs replaceably, provide license texts/attribution). [S1]

## 2. Signal/slot best-practice idioms

- **Use new-style connections:** `obj.signalName.connect(self.handler)` — bind the signal object's `.connect()` to a callable. This is the supported, type-checkable idiom; old string-based `SIGNAL()/SLOT()` macros are legacy. [S2][S5]
- **Declare typed custom signals as class-level attributes** on a `QObject` subclass: `valueChanged = Signal(int)`. Declaring at class level (not in `__init__`) is required for Qt's meta-object machinery; the type argument gives the typed signature. [S2][S5]
- **`@Slot` decorator rationale:** mark handlers with `@Slot(int)` / `@Slot(str)`. The decorator (a) is **required for slots invoked across threads** (e.g. queued connections, `QRunnable.run`-side wiring) to guarantee correct cross-thread dispatch, and (b) reduces per-slot memory and slightly speeds invocation by registering a typed C++ slot. For in-thread, low-volume slots the speed/memory effect is negligible, but using it consistently documents intent and is the recommended default. **Stack multiple decorators for overloads:** `@Slot(int)` + `@Slot(str)` on one method. [S2][S3]
- **Avoid lambda-capture pitfalls:** a `connect(lambda: ...)` that captures loop variables binds late (all closures see the final value) — capture explicitly (`lambda v=v: ...`) or use `functools.partial`. Lambdas/`partial` also create references that can keep objects alive and are awkward to `disconnect`; prefer named slots when you need to disconnect or when capturing per-iteration state. [S2][S5]

## 3. Keeping long-running work off the GUI thread

- **Core rule:** the event loop runs in the GUI thread (started by `QApplication.exec()`); **blocking it freezes the UI**. All long/blocking work must run off this thread. [S11][S15]
- **Two sanctioned patterns:**
  - **Worker-object + `moveToThread` (QThread):** create a plain `QObject` worker that exposes signals, instantiate a `QThread`, call `worker.moveToThread(thread)`, wire `thread.started → worker.run` and `worker.finished → thread.quit`, then `thread.start()`. This is the recommended general pattern for a long-lived/stateful worker that needs rich signal/slot communication. [S13][S14]
  - **`QThreadPool` + `QRunnable`:** for fire-and-forget / pooled tasks, subclass `QRunnable`, implement `run()`, and submit via `QThreadPool.globalInstance().start(worker)`. The pool reuses threads and handles queuing, reducing thread-creation overhead. `QRunnable` itself has no signals — attach a separate `QObject` "signals" holder (inherit `QObject` for the signals, emit progress/result/finished from `run()`) to communicate back. [S10][S12][S16]
- **Choosing:** pooled, short, independent jobs → `QThreadPool`/`QRunnable`; one persistent worker with state + frequent signals → `moveToThread`. [S10][S13]
- **Anti-patterns (forbidden):**
  - **Subclassing `QThread` and putting slots/work in the subclass** — the `QThread` object lives in the *creating* thread, so its slots execute there, not in the new thread. Use the worker-object approach instead. [S15]
  - **Touching widgets / any GUI object from a worker thread** — Qt GUI classes are not thread-safe; mutate the UI only on the GUI thread. Send results back via signals (queued connections), let a GUI-thread slot update widgets. [S10][S15]
  - **Blocking calls (sleep, sync I/O, busy loops) on the GUI thread**, or processing huge work inside a single slot without yielding. [S11][S15]

## 4. "No business logic in widgets" — UI-independent, testable core

- **Boundary principle:** keep all domain/business logic in a **UI-independent core** that has zero PySide6 imports; widgets are thin and only render state + forward user intent. The model/core must be "completely unaware of the UI's existence," so UI changes never touch business rules. This makes the core unit-testable without a display. [S17][S20]
- **Recommended structure for PySide6:**
  - **Qt ModelView (`QAbstractItemModel`/`QAbstractListModel`/`QAbstractTableModel`)** to bridge core data to views — avoids hand-syncing widget state with data and removes boilerplate. Wrap the pure-Python core in a thin model adapter; views bind to the model. [S17]
  - **MVC / MVP / MVVM controller layer:** a controller (or presenter/view-model) owns signal–slot wiring between view and model, so widgets contain no decision logic. MVVM/MVP both give a "clean separation between GUI and business logic" yielding a modular, testable codebase. [S18][S19][S20]
- **FF-Explorer fit:** core stays import-clean (testable with plain `pytest`); a model/controller layer adapts it to PySide6 views. The existing "UI-independent core" goal maps directly onto this.

## 5. Headless / CI GUI testing

- **`pytest-qt`** is the standard pytest plugin for Qt app testing and explicitly supports **PySide6** (and PyQt5/6, PySide2). Its `qtbot` fixture creates/manages the `QApplication`, runs an event loop, and simulates key presses / mouse clicks; the GUI is never rendered, so it runs in CI. [S21][S22][S24]
- **Headless platform:** set **`QT_QPA_PLATFORM=offscreen`** in the CI environment so Qt needs no display server (no X/Wayland). [S21]
- **Testing signals:** use **`qtbot.waitSignal(signal, timeout=...)`** as a context manager to block until a signal fires (e.g. `QThread.finished`, a worker's `result` signal); **`qtbot.waitSignals([...])`** waits for several. Use `qtbot.waitUntil(predicate)` to await a condition. [S22][S24]
- **Offscreen gotcha:** some focus/tooltip/geometry assertions that pass with a real platform can fail under `offscreen`; guard with `qtbot.waitUntil(lambda: w.hasFocus())` before such assertions, or avoid asserting on platform-dependent visuals. [S21]
- **Layering benefit:** because the core (Topic 4) is UI-independent, most logic tests need no `qtbot` at all — reserve `pytest-qt` for the thin view/controller layer.

## 6. Deprecations / migration gotchas vs PySide2 / Qt5

- **Scoped enums:** Qt6 enums are true scoped Python enums — use fully-qualified names: `Qt.ItemDataRole.BackgroundRole`, `Qt.AlignmentFlag.AlignLeft`. PySide6 *retains* the old unscoped aliases for back-compat (unlike PyQt6, which removed them), but **prefer fully-qualified names** for forward-safety. [S25][S30]
- **`exec_()` → `exec()`:** use `app.exec()` / `dialog.exec()`. `exec_()` exists only as a temporary PySide2-compat alias and is slated for removal — do not use in new code. [S26][S30]
- **`QAction` (and `QShortcut`) moved `QtWidgets` → `QtGui`** in Qt6 — update imports. [S30]
- **High-DPI:** `Qt.AA_EnableHighDpiScaling` / `AA_DisableHighDpiScaling` / `AA_UseHighDpiPixmaps` are deprecated; high-DPI scaling is on by default in PySide6 — drop these attribute calls. [S30]
- **Migration heuristic:** code using fully-qualified enum names + `exec()` + corrected imports ports cleanly from PySide2/PyQt5 to PySide6 with minimal change. [S30]

---

## Synthesis (for the instruction author)

Pin a current PySide6 6.11.x (LGPLv3) — covers Python 3.11–3.13. Mandate: new-style typed signals declared at class level; `@Slot`-decorated handlers (required for cross-thread); named slots over capturing lambdas. Long work off the GUI thread via worker-object+`moveToThread` (stateful) or `QThreadPool`/`QRunnable` (pooled), never by subclassing-QThread-with-slots and never touching widgets off-thread. Enforce the UI-independent core: domain logic has no PySide6 imports, adapted to views through a Qt model + controller (MVC/MVVM). Test the core with plain pytest and the thin UI with `pytest-qt` under `QT_QPA_PLATFORM=offscreen`, using `qtbot.waitSignal` for async. Code style: fully-qualified scoped enums, `exec()` not `exec_()`, `QAction` from `QtGui`, no deprecated high-DPI attrs.

## Limitations

- The PySide6→Qt version mapping (6.11.1 wraps Qt 6.11) is inferred from PyPI/release-notes; exact Qt patch level not separately confirmed per build. [S1][S4]
- Threading and architecture guidance draws partly on high-quality community tutorials (pythonguis, Real Python) alongside official Qt docs; these corroborate the official `QThread`/`QThreadPool` docs. [S10][S13][S15]
- LGPL relinking obligations summarized at a high level — not legal advice; consult the Qt licensing page for distribution specifics.

## Sources (URL + accessed 2026-06-25)

- [S1] PySide6 — PyPI. https://pypi.org/project/PySide6/
- [S2] Signals and Slots — Qt for Python (official docs). https://doc.qt.io/qtforpython-6/tutorials/basictutorial/signals_and_slots.html
- [S3] "PySide6 @Slot() Decorator Explained" — pythonguis.com. https://www.pythonguis.com/faq/what-does-slot-do/
- [S4] Qt for Python release notes (PySide6). https://doc.qt.io/qtforpython-6/release_notes/pyside6_release_notes.html
- [S5] "PySide6 Signals, Slots and Events" — pythonguis.com. https://www.pythonguis.com/tutorials/pyside6-signals-slots-events/
- [S8] PySide6 install / Python 3.13 — Qt Forum. https://forum.qt.io/topic/159278/cannot-install-pyside6-on-python-3-13-0
- [S10] "Multithreading PySide6 applications with QThreadPool" — pythonguis.com. https://www.pythonguis.com/tutorials/multithreading-pyside6-applications-qthreadpool/
- [S11] "Use PyQt's QThread to Prevent Freezing GUIs" — Real Python. https://realpython.com/python-pyqt-qthread/
- [S12] PySide6.QtCore.QThreadPool — Qt for Python (official docs). https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThreadPool.html
- [S13] "QThread vs QRunnable" — Qt Forum. https://forum.qt.io/topic/133574/qthread-vs-qrunnable
- [S14] "Threads in PySide6, packaging and executables" — abd-01.github.io. https://abd-01.github.io/posts/2024-01-15-PySide6-Notes/
- [S15] PySide6.QtCore.QThread — Qt for Python (official docs). https://doc.qt.io/qtforpython-6/PySide6/QtCore/QThread.html
- [S16] "Simple Threading Using QThreadPool.start()" — pythonguis.com. https://www.pythonguis.com/faq/pyqt-qthreadpool-simple-threading/
- [S17] "Using the PySide6 ModelView Architecture" — pythonguis.com. https://www.pythonguis.com/tutorials/pyside6-modelview-architecture/
- [S18] "A Clean Architecture for a PyQt GUI Using the MVVM Pattern" — M. Huber, Medium. https://medium.com/@mark_huber/a-clean-architecture-for-a-pyqt-gui-using-the-mvvm-pattern-b8e5d9ae833d
- [S19] "A Clean Architecture for a PyQt GUI Using the MVP Pattern" — M. Huber, Medium. https://medium.com/@mark_huber/a-clean-architecture-for-a-pyqt-gui-using-the-mvp-pattern-78ecbc8321c0
- [S20] qt-python-mvc (example MVC, PySide2/6) — GitHub, tom-a-horrocks. https://github.com/tom-a-horrocks/qt-python-mvc
- [S21] "Headless Testing of PySide/PyQt GUI Applications with pytest-qt" — ilManzo's blog. https://ilmanzo.github.io/post/testing_pyside_gui_applications/
- [S22] pytest-qt — PyPI. https://pypi.org/project/pytest-qt/
- [S24] pytest-qt documentation (intro / qtbot). https://pytest-qt.readthedocs.io/en/latest/intro.html
- [S25] "Deprecation Warning for Enum Access" — qtpy issue #352, GitHub. https://github.com/spyder-ide/qtpy/issues/352
- [S26] "PyQt6 vs PySide6" — pythonguis.com. https://www.pythonguis.com/faq/pyqt6-vs-pyside6/
- [S30] "PySide2 vs PySide6: Migration Guide" — pythonguis.com. https://www.pythonguis.com/faq/pyside2-vs-pyside6/

---
END OF REPORT
