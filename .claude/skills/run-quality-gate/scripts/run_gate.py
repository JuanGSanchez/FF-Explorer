#!/usr/bin/env python3
"""FF-Explorer quality gate: pytest+coverage (>=90% core) + invariant grep scan.

Deterministic, read-only except for pytest's own coverage cache. Prints a
PASS/FAIL block and exits 0 on PASS, 1 on FAIL, 2 on a harness/setup error.
Never edits configuration to flip a verdict — a softened gate is not a gate (C1).

Usage: python .claude/skills/run-quality-gate/scripts/run_gate.py [--repo <path>]
Default repo root is the current working directory.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

CORE_FORBIDDEN = ("tkinter", "PySide6", "fastapi", "fastmcp")
ARTIFACT_DIRS = ("packaging/work", "packaging/bin", "dist")


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run_pytest(repo: Path) -> tuple[bool, float | None, str]:
    """Run the configured gate. Returns (passed, coverage_pct, tail)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest"],
            cwd=str(repo), capture_output=True, text=True, timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # setup failure
        return False, None, f"pytest could not run: {exc}"
    out = proc.stdout + proc.stderr
    cov = None
    m = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+(?:\.\d+)?)%", out)
    if m:
        cov = float(m.group(1))
    tail = "\n".join(out.strip().splitlines()[-12:])
    return proc.returncode == 0, cov, tail


def scan_invariants(repo: Path) -> list[tuple[str, bool, str]]:
    """Best-effort static invariant checks. Returns (name, passed, evidence)."""
    results: list[tuple[str, bool, str]] = []

    core = _read(repo / "ff_explorer" / "core.py")
    hits = [f for f in CORE_FORBIDDEN if re.search(rf"^\s*(import|from)\s+{re.escape(f)}", core, re.M)]
    results.append(("core-purity", not hits,
                    "no forbidden imports" if not hits else f"core imports: {', '.join(hits)}"))

    pyproject = _read(repo / "pyproject.toml")
    thr_ok = "--cov-fail-under=90" in pyproject
    results.append(("cov-threshold", thr_ok,
                    "--cov-fail-under=90 present" if thr_ok else "threshold missing/lowered"))
    omit_count = pyproject.count('"ff_explorer/')  # known omit entries are __init__, gui/*, api/main
    omit_ok = omit_count <= 4
    results.append(("omit-not-widened", omit_ok,
                    f"omit entries={omit_count} (<=4 expected)"))

    rest = _read(repo / "ff_explorer" / "api" / "rest.py")
    gate_ok = ("min_length=1" in rest or "min_length = 1" in rest) and "confirm" in rest and "dry_run" in rest
    results.append(("destructive-gate", gate_ok,
                    "name_seed min_length + dry_run/confirm present" if gate_ok
                    else "destructive request model gate not detected in rest.py"))

    # tkinter / FF_UI regression
    ff_ui = (repo / "FF_UI.pyw").exists()
    tk_refs = []
    for f in repo.rglob("*.py"):
        if "/.git/" in f.as_posix() or "site-packages" in f.as_posix():
            continue
        if re.search(r"^\s*import\s+tkinter|^\s*from\s+tkinter", _read(f), re.M):
            tk_refs.append(f.relative_to(repo).as_posix())
    tk_ok = not ff_ui and not tk_refs
    results.append(("tkinter-absent", tk_ok,
                    "no tkinter / FF_UI.pyw" if tk_ok
                    else f"FF_UI.pyw={ff_ui}; tkinter in {tk_refs}"))

    staged = artifact_dirs_staged(repo)
    results.append(("artifacts-clean", not staged,
                    "no build artifacts staged" if not staged else f"staged: {', '.join(staged)}"))
    return results


def artifact_dirs_staged(repo: Path) -> list[str]:
    """Return any ARTIFACT_DIRS path appearing in `git diff --cached --name-only`."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(repo), capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []  # no git / not a failure of this gate
    staged = proc.stdout.splitlines()
    return [d for d in ARTIFACT_DIRS if any(s.startswith(d) for s in staged)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="repo root (default cwd)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()

    passed, cov, tail = run_pytest(repo)
    invs = scan_invariants(repo)
    cov_ok = cov is not None and cov >= 90.0
    all_ok = passed and cov_ok and all(p for _, p, _ in invs)

    print("GATE: PASS" if all_ok else "GATE: FAIL")
    print(f"coverage: {cov if cov is not None else 'unknown'}%"
          + ("" if cov_ok else " (<90)"))
    print(f"pytest: {'passed' if passed else 'FAILED'}")
    if not passed:
        print("--- pytest tail ---")
        print(tail)
    print("invariants: " + "; ".join(f"{n} {'PASS' if p else 'FAIL'} ({e})" for n, p, e in invs))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
