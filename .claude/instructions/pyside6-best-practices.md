# Instruction: PySide6 Best Practices (FF-Explorer)

## Principles Applied
Inherited: P1 (source grounding — every directive references a source from research report RR-1; no API name or version number invented beyond RR-1's scope; citations carry traceable URLs), P2 (determinism — named signal/slot idioms and thread patterns; binary worker-vs-pool choice; no ambiguous "it depends" phrasing), P3 (systematicity — decision points enumerated in conditional_rules; each pattern has a named choice condition), P4 (consistency — same idioms across every gui-dev session; one best-practices instruction for this framework), P6 (self-contained — all directives, source citations, and migration gotchas stated here; RR-1 path and sources are explicit), P7 (reference hygiene — all [S*] cites resolve to RR-1 §Sources; hook names resolve to CLAUDE.md §Hooks; no filler), P8 (this block is the P8 expression for this asset), P9 Role Separation (this instruction governs the PySide6 GUI layer only; core.py/service.py are governed by python-repo-conventions.md; python-repo-conventions.md Rule 10 is the source of the PySide6-only mandate; this instruction does not duplicate it), P10 Exit-Status Determinism (n/a — this instruction does not mandate an exit-status output format; agents operating under it return EXIT STATUS per CLAUDE.md Operating contract), P11 Programmatic Determinism (directives direct gui-dev toward Qt's sanctioned worker patterns and signal/slot wiring rather than ad-hoc threading or direct widget mutation; headless_core_guard.py hook enforces the import boundary mechanically; R18/P11 canonical definition: `repo-enhancer/orchestrator.md` CONVENTIONS, do not restate), P12 Maximal-Effort Completeness (all five technical areas from RR-1 are covered: signals/slots, threading, UI-independent architecture, testing, migration gotchas), P13 Token Economy (cite [S*] IDs from RR-1 rather than restating source text; terse directives). Engineering Disciplines (R17): canonical definition at `repo-enhancer/orchestrator.md` CONVENTIONS; prompt layer = grouped numbered directives with positive/negative examples; context layer = load this instruction only when gui-dev touches ff_explorer/gui/ (just-in-time); harness layer = headless_core_guard.py hook enforces the import boundary; decision points in conditional_rules cover the worker-pattern choice.

Custom:
- C1 — Research Grounding: every directive in this instruction references at least one source from RR-1 (docs/research-pyside6-best-practices.md, compiled 2026-06-25); no PySide6 API, version number, or behavioral claim may be stated without a [S*] citation that resolves to RR-1 §Sources.

Scope: applies to gui-dev (and any agent touching ff_explorer/gui/) on PySide6 6.11.x, Python 3.11–3.13 [S1][S4]. Does not govern core.py or service.py — those are governed by .claude/instructions/python-repo-conventions.md. Does not add a SessionStart hook or duplicate any global harness.

<instructions>
  <context>
    FF-Explorer's GUI layer (ff_explorer/gui/) runs on PySide6 6.11.x
    (LGPLv3) against Python 3.11–3.13. [S1][S4] PySide6 6.11.x fully
    supports Python 3.13; pin a current 6.11.x wheel when targeting 3.13
    (early 3.13.0 + older PySide6 combinations failed to install, resolved
    in current wheels). [S1][S8]

    The GUI is a thin client over the headless core: it renders state and
    forwards user intent; all domain logic lives in ff_explorer/core.py.
    (CLAUDE.md Invariant 1; .claude/instructions/python-repo-conventions.md
    Rule 3.) These directives keep the GUI idiomatic, thread-safe, testable
    without a display, and migration-safe across PySide6 6.x releases.

    Source for all technical claims: docs/research-pyside6-best-practices.md
    (RR-1, compiled 2026-06-25). [S*] citations below resolve to RR-1
    §Sources.
  </context>

  <rules>
    <!-- Signals and slots -->

    1. Use new-style signal connections only: obj.signalName.connect(
       self.handler). String-based SIGNAL()/SLOT() macros are Qt4 legacy;
       do not use them in any new or modified code. [S2][S5]

    2. Declare custom signals as class-level attributes on the QObject
       subclass: valueChanged = Signal(int). Never declare a signal inside
       __init__ — Qt's meta-object machinery requires class-level
       declaration to register the signal; a signal created in __init__ is
       not picked up correctly. [S2][S5]

    3. Mark every slot handler with @Slot(type). The decorator is required
       for slots invoked across threads (queued connections, QRunnable
       workers) to guarantee correct cross-thread dispatch; it also
       registers a typed C++ slot, reducing per-slot memory overhead.
       Stack decorators for overloads: place @Slot(int) and @Slot(str) as
       separate decorators on the same method. [S2][S3]

    4. Prefer named slots over lambda or functools.partial captures. A
       lambda that captures a loop variable binds late: all closures see
       the final loop value, not the per-iteration value. If a lambda is
       unavoidable, capture explicitly (lambda v=v: ...). Use a named slot
       whenever you need to call disconnect() on the connection or when
       capturing per-iteration state. [S2][S5]

    <!-- Threading / event-loop discipline -->

    5. Never block the GUI thread. The GUI thread runs QApplication.exec();
       any blocking call — synchronous I/O, time.sleep(), a long computation,
       a busy loop — freezes the UI and the event loop. All long or blocking
       work must run off the GUI thread via one of the two patterns in
       Rules 6–7. [S11][S15]

    6. Stateful or long-lived workers: use the worker-object + moveToThread
       pattern. Create a plain QObject subclass (the worker) with signals;
       instantiate a QThread; call worker.moveToThread(thread); wire
       thread.started to worker.run and worker.finished to thread.quit;
       then call thread.start(). [S13][S14]

    7. Pooled or fire-and-forget tasks: use QThreadPool + QRunnable.
       Subclass QRunnable and implement run(). Attach a separate QObject
       subclass as a signals holder (QRunnable itself has no signals);
       emit progress/result/finished from run() on the signals holder.
       Submit via QThreadPool.globalInstance().start(worker). [S10][S12][S16]

    8. Under no circumstances subclass QThread and put slots or domain work
       inside the subclass. The QThread object lives in the creating
       (GUI) thread, so its slots execute on the GUI thread, not in the
       worker thread — this is a common and subtle bug. Instead: create a
       plain QObject worker and call moveToThread (Rule 6). [S15]

    9. Under no circumstances touch a widget or any GUI object from a
       worker thread. Qt GUI classes are not thread-safe. Instead: send
       results back to the GUI thread via signals using queued connections
       and let a GUI-thread slot decorated with @Slot update the widget.
       [S10][S15]

    <!-- Architecture: UI-independent core -->

    10. The GUI layer is a thin client. ff_explorer/core.py and all sibling
        headless modules must have zero PySide6/Qt imports. (CLAUDE.md
        Invariant 1; .claude/instructions/python-repo-conventions.md
        Rule 3.) The headless_core_guard.py hook (PreToolUse) enforces
        this boundary mechanically. Widgets render state and forward user
        intent; all domain logic stays in the core. Do not add business
        logic to a widget class. [S17][S20]

    11. Bridge core data to PySide6 views through a Qt ModelView adapter
        (QAbstractItemModel / QAbstractListModel / QAbstractTableModel)
        or a controller layer (MVC / MVVM / MVP). Do not hand-sync widget
        state with application data. The model is the single source of
        truth for view state; views read from it, not from application
        variables directly. [S17][S18][S19][S20]

    <!-- Testing -->

    12. Use pytest-qt (qtbot fixture) for GUI layer tests. pytest-qt
        explicitly supports PySide6, manages the QApplication lifecycle,
        and simulates key presses / mouse clicks without rendering to a
        screen. [S21][S22][S24]

    13. Set QT_QPA_PLATFORM=offscreen for all GUI test runs. This is the
        documented headless platform; Qt needs no display server and no
        X/Wayland session. (Already documented in CLAUDE.md §Gate & build
        commands.) [S21]

    14. Await async signals with qtbot.waitSignal(signal, timeout=<ms>)
        for a single signal; qtbot.waitSignals([...]) for multiple
        signals; qtbot.waitUntil(predicate) for condition-based waits.
        Under no circumstances use time.sleep() to wait for a signal or
        thread completion in a test. [S22][S24]

    15. Test UI-independent core logic (core.py, service.py,
        content_search.py, etc.) with plain pytest and no qtbot. Reserve
        pytest-qt for the thin GUI layer only. Most coverage comes from
        core tests; the GUI test suite covers view/controller wiring.
        [S17][S21]

    <!-- Migration gotchas: PySide2 / Qt5 → PySide6 / Qt6 -->

    16. Use fully-qualified scoped enum names: Qt.ItemDataRole.BackgroundRole,
        Qt.AlignmentFlag.AlignLeft. The unscoped aliases exist in PySide6
        for back-compat but are not forward-safe; use the scoped form in
        all new and modified code. (Note: PyQt6 removed the unscoped
        aliases entirely; PySide6 keeps them only temporarily.) [S25][S30]

    17. Use app.exec() and dialog.exec(). exec_() is a PySide2-compat alias
        slated for removal; do not use it in new code. Where exec_() appears
        in existing code, replace it. [S26][S30]

    18. Import QAction and QShortcut from PySide6.QtGui, not
        PySide6.QtWidgets. They moved from QtWidgets to QtGui in Qt6.
        [S30]

    19. Do not call Qt.AA_EnableHighDpiScaling, Qt.AA_DisableHighDpiScaling,
        or Qt.AA_UseHighDpiPixmaps. These application attributes are
        deprecated in PySide6; high-DPI scaling is enabled by default.
        Remove these calls from any migrated code. [S30]
  </rules>

  <conditional_rules>
    - If choosing between the two threading patterns: stateful worker with
      rich signal/slot communication or a long lifecycle → moveToThread
      (Rule 6); short, independent, pooled tasks with fire-and-forget
      semantics → QThreadPool/QRunnable (Rule 7). [S10][S13]
    - If a worker needs to send progress or results back to the GUI:
      use signals from a QObject signals holder; never pass a widget
      reference into the worker and never return a value from
      QRunnable.run(). [S10][S12]
    - If a dialog is modal: call dialog.exec() (not exec_()); ensure
      the dialog is instantiated and shown on the GUI thread. [S26]
    - If a new Qt enum value is needed: look up the fully-qualified
      scoped name in the Qt for Python docs
      (https://doc.qt.io/qtforpython-6/) before using it; do not guess
      the unscoped form. [S25]
  </conditional_rules>

  <examples>
    <example>
      <input>Run a core.list_entries() search in the background and show
      progress in the GUI without freezing.</input>
      <output>
        CORRECT — moveToThread worker pattern (Rules 5–6, 3, 9):

          class SearchSignals(QObject):
              progress = Signal(int)
              finished = Signal(list)

          class SearchWorker(QObject):
              def __init__(self, query):
                  super().__init__()
                  self.query = query
                  self.signals = SearchSignals()

              def run(self):
                  results = core.list_entries(self.query)   # headless core
                  self.signals.progress.emit(100)
                  self.signals.finished.emit(results)       # signal, not widget touch

          # In the GUI-thread widget:
          self.thread = QThread()
          self.worker = SearchWorker(query)
          self.worker.moveToThread(self.thread)
          self.thread.started.connect(self.worker.run)
          self.worker.signals.finished.connect(self.on_results)  # new-style
          self.thread.start()

          @Slot(list)                             # @Slot required (Rule 3)
          def on_results(self, results):
              self.model.setResults(results)      # GUI thread only

        INCORRECT:
          def search_clicked(self):
              results = core.list_entries(query)  # blocks event loop (Rule 5)
              self.model.setResults(results)

          class SearchWorker(QThread):            # subclassing QThread (Rule 8)
              def run(self):
                  self.label.setText("done")      # widget touch off-thread (Rule 9)
      </output>
    </example>
    <example>
      <input>Declare and connect a custom signal for a result count.</input>
      <output>
        CORRECT:
          class ResultsWidget(QWidget):
              resultsChanged = Signal(int)         # class-level (Rule 2)

              @Slot(int)                           # @Slot decorator (Rule 3)
              def on_results_changed(self, count):
                  self.label.setText(f"{count} results")

          widget.resultsChanged.connect(widget.on_results_changed)   # new-style (Rule 1)

        INCORRECT:
          def __init__(self):
              self.resultsChanged = Signal(int)    # in __init__: not registered
          self.connect(w, SIGNAL("resultsChanged(int)"), ...)  # old-style macro
          app.exec_()                              # use app.exec() (Rule 17)
          from PySide6.QtWidgets import QAction   # import from QtGui (Rule 18)
      </output>
    </example>
  </examples>
</instructions>

<!--
  SOURCES:
  - User requirement: a PySide6-best-practices instruction for FF-Explorer's
    gui-dev agent, grounded in research report RR-1 (Group E, item 16).
  - docs/research-pyside6-best-practices.md (RR-1, 2026-06-25): all
    technical claims and [S*] citations ([S1]–[S30]).
  - CLAUDE.md §Architecture (GUI subsystem), §Invariants 1, §Gate & build
    commands (QT_QPA_PLATFORM=offscreen), §Hooks (headless_core_guard.py).
  - .claude/instructions/python-repo-conventions.md Rule 3 (headless core),
    Rule 10 (PySide6 only for the GUI).
  - references/software-development.md §3: best-practices instruction
    grouped structure and grounding requirement.
  - templates/claude_instruction.md v2026-05-10: structural template.
  - repo-enhancer/orchestrator.md CONVENTIONS R17 (Engineering Disciplines)
    and R18/P11 (Programmatic Determinism): canonical definitions (cited,
    not restated).
-->
