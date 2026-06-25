# Instruction: Python Repo Conventions (FF-Explorer)

## Principles Applied
Inherited: P1 (sources), P2 (determinism), P3 (decision points), P4 (consistency), P5 (context budget — agents search before bulk-reading), P6 (self-contained), P7 (reference hygiene), P8 (principles block present), P9 Role Separation (governs Python-layer standards only; per-agent assets own their layer), P10 Exit-Status Determinism (output_format requires EXIT STATUS payload), P11 Programmatic Determinism (stdlib/pathlib/pytest first; cite repo-enhancer/orchestrator.md CONVENTIONS R18/P11), P12 Maximal-Effort Completeness (full convention coverage; no partial rules), P13 Token Economy (cite rule:line; terse findings). Engineering Disciplines (R17): cite repo-enhancer/orchestrator.md CONVENTIONS. Custom: none — this is the FF-Explorer Python best-practices instruction (PEP 8, pathlib, deterministic pytest, headless-core purity); encodes coding standards and architecture invariants for every dev agent.

Scope: applies to all code-producing FF-Explorer agents (core-dev, gui-dev, access-dev, test-author, packaging-builder) and to docs-writer/reviewer when they verify code against these standards. It governs Python style and the architecture invariants; the per-agent assets own their layer.

<instructions>
  <context>
    FF-Explorer is a Python >=3.11 package: a headless core (recursive search +
    save/remove/compress), a PySide6 GUI, a dual FastAPI+FastMCP access layer
    over one shared core, PyInstaller packaging, and a pytest suite with a 90%
    core coverage gate. These conventions keep new code stdlib-first,
    typed, deterministic, headless-pure, and secret-free, so the architecture
    and safety invariants survive every change. Reason: consistency and purity
    here are what let the access layer, GUI, and packaging all rest on one
    trustworthy core.
  </context>

  <rules>
    1. Standard library and pathlib first. Use the stdlib (`pathlib.Path`, `os`, `shutil`, `zipfile`, `re`, `fnmatch`, `hashlib`) before reaching for a dependency. Instead of adding a package for something stdlib covers, use stdlib; if a new dependency is genuinely needed, declare it in `pyproject.toml` (correct group/extra) with a pinned range and a one-line rationale — never inline or vendor it.
    2. Type everything public. Every public function/method has parameter and return type hints; prefer precise types (`list[Path]`, `int` kind `0|1`, explicit dataclasses/Pydantic models) over `Any`. Instead of leaving a signature untyped, annotate it.
    3. Keep the core headless and pure. `ff_explorer/core.py` must import no `tkinter`, `PySide6`/Qt, `fastapi`, or `fastmcp`, and must contain no UI or transport state. Instead of importing a surface into core, add the capability in core and surface it through `service.py`/`rest.py` so GUI and both transports inherit it.
    4. One shared core for both transports. REST and MCP delegate to the same core via `service.py` (MCP tools are generated from the FastAPI app). Instead of duplicating logic in a route or the MCP server, put it in core/service once.
    5. Preserve the destructive gate in code. Any remove/compress path requires `dry_run=false` AND `confirm=true` to mutate, rejects an empty/whitespace `name_seed` (`EmptySeedError`), and routes removes to the OS recycle bin via `send2trash` (compress permanently deletes originals by design). Never write a destructive code path that bypasses these.
    6. Deterministic, isolated tests. Tests use `tmp_path`/fixtures, never the real user filesystem or network; assertions are order-stable and reproducible; no test depends on wall-clock, machine paths, or another test's side effects. Instead of asserting on incidental ordering, sort or assert on sets where order is not guaranteed.
    7. Narrow exception handling. Catch the specific filesystem error types you expect (`OSError`, `shutil.Error`, `zipfile.BadZipFile`) where the failure mode is known and collect them into the report model; instead of a bare `except Exception` that swallows programming errors, let unexpected types propagate.
    8. No secrets, ever. Under no circumstances commit credentials, tokens, keys, or `.env` content. Instead of inlining a secret, read it from an environment variable and document the variable.
    9. No committed build artifacts. Under no circumstances add build output (`packaging/work/`, `packaging/bin/`, `dist/`, `*.egg-info`, `__pycache__`) to the repo. Instead of committing a prebuilt executable, keep the build reproducible from the spec and ensure the output dirs are git-ignored.
    10. PySide6 only for the GUI. The GUI is PySide6; never reintroduce Tkinter or revive `FF_UI.pyw`. Instead of a quick Tkinter widget, use the equivalent Qt widget.
  </rules>

  <conditional_rules>
    - If a change needs a new dependency, then add it to the correct `pyproject.toml` group/extra with a pinned range + rationale, and update packaging hidden-imports if it must be bundled.
    - If new core/service/api code is added, then it ships with deterministic tests keeping `--cov-fail-under=90` green — without lowering the threshold or widening the omit.
    - If a destructive failure mode is genuinely broad and unknown, then document why a wider catch is needed at that exact point rather than defaulting to bare `except Exception`.
    - If a value must vary by OS (e.g. send2trash backend, paths), then branch on `sys.platform` rather than hard-coding one platform.
  </conditional_rules>

  <output_format>
    Code follows these conventions; in review/report, cite the rule number and the file:line when a convention is applied or a deviation is flagged. End with the agent's EXIT STATUS payload.
  </output_format>

  <examples>
    <example>
      <input>Add a regex match mode to the query.</input>
      <output>Stdlib `re` (Rule 1); `match_mode: Literal["substring","glob","regex"]` typed param (Rule 2); compiled once in core and surfaced via service so REST+MCP inherit it (Rules 3,4); deterministic tmp_path tests incl. invalid-regex (Rule 6) keeping the gate at 90.</output>
    </example>
    <example>
      <input>Wrap the whole compress loop in except Exception to be safe.</input>
      <output>Refused as written (Rule 7). I'll catch OSError/shutil.Error/zipfile.BadZipFile and collect them into report.failed, letting a TypeError-class programming error propagate so bugs aren't masked as I/O failures.</output>
    </example>
  </examples>
</instructions>

<!--
  SOURCES:
  - User requirement: a python-repo-conventions instruction (stdlib/pathlib, typing, headless-core purity, deterministic tests, no secrets) for FF-Explorer dev agents.
  - Repo ground truth: ff_explorer/core.py (headless purity, send2trash recycle route, dry_run/confirm/EmptySeedError gate, narrow-except backlog FFX-B11), ff_explorer/api/* (one shared core dual transport), ff_explorer/gui/* (PySide6), pyproject.toml (>=3.11, deps/extras, --cov-fail-under=90, coverage omit), packaging/* (build artifacts).
  - references/claude.md §INSTRUCTION (XML tags, negative-instruction patterns); templates/claude_instruction.md.
-->
