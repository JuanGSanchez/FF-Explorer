"""
ff_explorer.rename
==================
Batch rename rule engine with dry-run preview and undo file.

Public API
----------
rename_entries(path, kind, name_seed, *, case_sensitive=True,
               match_mode="substring", rules, dry_run=True, confirm=False)
               -> RenameReport

replay_undo(undo_file) -> list[tuple[str, str]]
    Reverse the rename recorded in *undo_file*.  Returns the list of
    (original_name, restored_name) pairs that were successfully reversed.

Rule dataclass
--------------
RenameRule(kind, params)
    kind: "find_replace" | "regex_replace" | "prefix" | "suffix"
          | "case" | "counter"
    params: dict with rule-specific keys (see apply_rule docstring).

Safety guards (identical to remove_entries / compress_entries):
1. name_seed must be non-empty / non-whitespace — EmptySeedError otherwise.
2. dry_run=True (default) — returns the planned mapping without mutating.
3. confirm=True is required alongside dry_run=False to actually rename.

Headless purity: this module imports NO tkinter / PySide6 / fastapi / fastmcp.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from ff_explorer.core import (
    EntryKind,
    EmptySeedError,
    list_entries as _core_list_entries,
)

__all__ = [
    "RenameRule",
    "RenameReport",
    "rename_entries",
    "replay_undo",
    "apply_rules",
]


# ---------------------------------------------------------------------------
# Internal helpers (inlined from core to avoid importing private symbols)
# ---------------------------------------------------------------------------

def _normalise_path(path: str | Path) -> Path:
    """Return an absolute, resolved Path; raise ValueError for missing dirs."""
    p = Path(path).resolve()
    if not p.is_dir():
        raise ValueError(f"path must be an existing directory, got: {path!r}")
    return p


def _guard_seed(name_seed: str) -> None:
    """Raise EmptySeedError if name_seed is blank — rename_entries guard."""
    if not name_seed or not name_seed.strip():
        raise EmptySeedError("rename_entries")

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RenameRule:
    """A single composable rename rule.

    Attributes
    ----------
    kind:
        One of: ``"find_replace"``, ``"regex_replace"``, ``"prefix"``,
        ``"suffix"``, ``"case"``, ``"counter"``.
    params:
        Dict of rule-specific parameters; see :func:`apply_rules` for the
        expected keys per kind.
    """
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class RenameReport:
    """Returned by rename_entries regardless of dry_run state.

    Attributes
    ----------
    dry_run:
        Mirrors the *dry_run* parameter.
    matched:
        All file names (not full paths) that matched the filter.
    mapping:
        Planned (old_name, new_name) pairs for every matched entry.
    renamed:
        (old_path_str, new_path_str) pairs for entries successfully renamed
        (empty on dry-run).
    collisions:
        Descriptions of collision conflicts preventing the rename.
        If non-empty the batch is refused entirely.
    failed:
        (path_str, error_message) pairs for per-file OSError failures
        collected during live apply.
    undo_file:
        Absolute path to the undo JSON file written on a successful live
        apply, or ``None`` when dry-run or no renames occurred.
    """
    dry_run: bool = True
    matched: list[str] = field(default_factory=list)
    mapping: list[tuple[str, str]] = field(default_factory=list)
    renamed: list[tuple[str, str]] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    undo_file: str | None = None

    @property
    def would_affect(self) -> list[str]:
        """Names that would be / were targeted (preview list)."""
        return self.matched


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

# Counter state is maintained per-batch (mutable, passed by reference)
_CounterState = list  # [int] — single-element list so it's mutable across calls


def _apply_single_rule(
    name: str,
    stem: str,
    suffix: str,
    rule: RenameRule,
    counter_state: _CounterState,
) -> str:
    """Apply one rule to (stem, suffix) and return the new full filename.

    Parameters
    ----------
    name:
        Current full filename (used for find_replace / regex_replace on the
        whole name).
    stem:
        Current filename stem (without extension).
    suffix:
        Current filename suffix (including the leading dot, e.g. ``".txt"``).
    rule:
        The :class:`RenameRule` to apply.
    counter_state:
        Single-element list [current_value] for the ``"counter"`` rule so
        state is shared across calls within one batch.

    Returns
    -------
    str
        The new full filename after applying the rule.
    """
    p = rule.params
    kind = rule.kind

    if kind == "find_replace":
        find = str(p.get("find", ""))
        replace = str(p.get("replace", ""))
        new_name = name.replace(find, replace)
        # Re-split stem/suffix from updated name for downstream rules
        new_stem = Path(new_name).stem
        new_suffix = Path(new_name).suffix
        return new_name

    if kind == "regex_replace":
        pattern = str(p.get("pattern", ""))
        replacement = str(p.get("replacement", ""))
        flags = re.IGNORECASE if p.get("ignore_case", False) else 0
        compiled = re.compile(pattern, flags)
        new_name = compiled.sub(replacement, name)
        return new_name

    if kind == "prefix":
        text = str(p.get("text", ""))
        # Prepend to stem, keep suffix
        return text + stem + suffix

    if kind == "suffix":
        # "suffix" here means: append text BEFORE the extension
        text = str(p.get("text", ""))
        return stem + text + suffix

    if kind == "case":
        mode = str(p.get("mode", "lower"))
        if mode == "upper":
            new_stem = stem.upper()
        elif mode == "lower":
            new_stem = stem.lower()
        elif mode == "title":
            new_stem = stem.title()
        else:
            new_stem = stem
        return new_stem + suffix

    if kind == "counter":
        start = int(p.get("start", 1))
        step = int(p.get("step", 1))
        padding = int(p.get("padding", 1))
        template = str(p.get("template", "{stem}{n}{suffix}"))
        # counter_state[0] holds the current counter value
        n = counter_state[0]
        formatted_n = str(n).zfill(padding)
        counter_state[0] = n + step
        new_name = template.format(
            stem=stem,
            suffix=suffix,
            n=formatted_n,
            name=name,
        )
        return new_name

    raise ValueError(f"Unknown rename rule kind: {kind!r}")


def apply_rules(name: str, rules: list[RenameRule], counter_state: _CounterState | None = None) -> str:
    """Apply an ordered list of rules to a filename and return the new name.

    Rules are applied in order; each rule receives the output of the previous.
    The stem/suffix split is re-computed after each step so rules that operate
    on stem+suffix always see the current state.

    Parameters
    ----------
    name:
        Original filename (basename only, no directory).
    rules:
        Ordered list of :class:`RenameRule` objects.
    counter_state:
        Shared mutable list ``[current_value]`` for counter rules.  Pass the
        same object across all filenames in a batch.  If ``None`` a fresh
        state ``[1]`` is created (useful for unit tests of a single name).

    Returns
    -------
    str
        The transformed filename.
    """
    if counter_state is None:
        counter_state = [1]
    current = name
    for rule in rules:
        p = Path(current)
        stem = p.stem
        suffix = p.suffix
        current = _apply_single_rule(current, stem, suffix, rule, counter_state)
    return current


# ---------------------------------------------------------------------------
# Core rename operation
# ---------------------------------------------------------------------------

def rename_entries(
    path: str | Path,
    kind: EntryKind | int,
    name_seed: str,
    *,
    rules: list[RenameRule],
    case_sensitive: bool = True,
    match_mode: str = "substring",
    dry_run: bool = True,
    confirm: bool = False,
) -> RenameReport:
    """Walk *path*, filter by *name_seed*, and rename matched entries.

    Safety guards (identical to remove_entries / compress_entries):

    1. *name_seed* must be non-empty and non-whitespace —
       :class:`~ff_explorer.core.EmptySeedError` otherwise.
    2. *dry_run=True* (the default) — returns the planned old→new mapping
       without touching the filesystem.
    3. *confirm=True* is required alongside *dry_run=False* to actually rename.
       Raises ``ValueError`` if *dry_run=False* but *confirm=False*.

    Collision detection is performed before any mutation:
    - If two source files map to the same target name, collision is reported.
    - If a target name already exists on disk (and the existing file is not
      itself being renamed away), collision is reported.
    When any collision is detected the entire batch is refused —
    :attr:`RenameReport.collisions` is populated and no rename is performed.

    On a confirmed apply with no collisions:
    - Each matched file is renamed via :meth:`pathlib.Path.rename`.
    - An undo JSON file is written to
      ``<path>/.ffe-rename-undo/<YYYYMMDD-HHMMSS>.json`` recording the
      reverse mapping (new_path → original_path) for :func:`replay_undo`.
    - Per-file :exc:`OSError` failures are collected into
      :attr:`RenameReport.failed` rather than aborting mid-batch.

    Parameters
    ----------
    path:
        Root directory to walk.
    kind:
        :class:`~ff_explorer.core.EntryKind` value (or int: 0=FOLDERS, 1=FILES).
    name_seed:
        Non-empty filter pattern.  Blank raises ``EmptySeedError``.
    rules:
        Ordered list of :class:`RenameRule` objects applied to each matched
        filename.  Applied in order; each rule receives the output of the
        previous.
    case_sensitive:
        Case-sensitive name matching (default ``True``).
    match_mode:
        ``"substring"`` (default), ``"glob"``, or ``"regex"``.
    dry_run:
        When ``True`` (default), return the preview mapping without renaming.
    confirm:
        Must be ``True`` when *dry_run=False*.  Explicit opt-in token.

    Returns
    -------
    RenameReport
        See :class:`RenameReport` for field descriptions.

    Raises
    ------
    EmptySeedError
        If *name_seed* is blank or whitespace-only.
    ValueError
        If *dry_run=False* but *confirm=False*, or *path* is not a directory.
    """
    _guard_seed(name_seed)
    root_path = _normalise_path(path)
    kind = EntryKind(int(kind))

    if not dry_run and not confirm:
        raise ValueError(
            "rename_entries() requires confirm=True when dry_run=False.  "
            "Set both dry_run=False and confirm=True to actually rename entries."
        )

    # Reuse core matcher — identical semantics to remove_entries.
    # search_archives=False: renames must never target archive-internal entries.
    matches = _core_list_entries(
        root_path, kind, name_seed,
        case_sensitive=case_sensitive,
        match_mode=match_mode,
        search_archives=False,
    )
    matched_names = [str(e.path.name) for e in matches]
    report = RenameReport(dry_run=dry_run, matched=matched_names)

    if not matches:
        return report

    # Compute old→new mapping — one shared counter_state for the entire batch
    counter_state: list[int] = [int(rules[0].params.get("start", 1))
                                 if rules and rules[0].kind == "counter"
                                 else 1]
    # Re-initialise with correct start for first counter rule found
    for rule in rules:
        if rule.kind == "counter":
            counter_state[0] = int(rule.params.get("start", 1))
            break

    mapping_raw: list[tuple[Path, Path]] = []
    shared_counter: list[int] = [counter_state[0]]

    for entry in matches:
        old_path = entry.path
        new_name = apply_rules(old_path.name, rules, shared_counter)
        new_path = old_path.parent / new_name
        mapping_raw.append((old_path, new_path))

    report.mapping = [(str(old.name), str(new.name)) for old, new in mapping_raw]

    # --- Collision detection ---
    old_paths_set = {old for old, _ in mapping_raw}
    new_paths = [new for _, new in mapping_raw]
    new_names_list = [new.name for new in new_paths]

    # Check 1: two sources map to the same target name within the batch
    seen_new: dict[str, str] = {}
    for (old, new) in mapping_raw:
        key = str(new)
        if key in seen_new:
            report.collisions.append(
                f"Collision: both '{seen_new[key]}' and '{old.name}' would be "
                f"renamed to '{new.name}'"
            )
        else:
            seen_new[key] = old.name

    # Check 2: target already exists on disk and isn't being renamed away
    for (old, new) in mapping_raw:
        if new == old:
            continue  # no-op rename — not a collision
        if new.exists() and new not in old_paths_set:
            report.collisions.append(
                f"Collision: target '{new.name}' already exists on disk "
                f"(not being renamed away)"
            )

    if report.collisions:
        # Refuse to apply — return the preview with collisions populated
        return report

    if dry_run:
        return report

    # --- Live apply ---
    undo_map: dict[str, str] = {}  # new_path_str -> old_path_str
    for (old_path, new_path) in mapping_raw:
        try:
            old_path.rename(new_path)
            report.renamed.append((str(old_path), str(new_path)))
            undo_map[str(new_path)] = str(old_path)
        except OSError as exc:
            logger.warning("rename: failed for %s -> %s: %s",
                           old_path, new_path, exc)
            report.failed.append((str(old_path), str(exc)))

    # Write undo file only if at least one rename succeeded
    if undo_map:
        undo_dir = root_path / ".ffe-rename-undo"
        undo_dir.mkdir(exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
        undo_path = undo_dir / f"{ts}.json"
        with open(undo_path, "w", encoding="utf-8") as fp:
            json.dump(undo_map, fp, indent=2)
        report.undo_file = str(undo_path)

    return report


# ---------------------------------------------------------------------------
# Undo helper
# ---------------------------------------------------------------------------

def replay_undo(undo_file: str | Path) -> list[tuple[str, str]]:
    """Reverse a rename batch recorded in *undo_file*.

    Reads the JSON mapping written by :func:`rename_entries` (which maps
    new_path → original_path) and renames each file back.

    Parameters
    ----------
    undo_file:
        Absolute path to the ``.json`` undo file written by
        :func:`rename_entries`.

    Returns
    -------
    list[tuple[str, str]]
        ``[(attempted_new_path, original_path), ...]`` for entries where the
        reverse rename was attempted.  The list includes both successes and
        failures.  On :exc:`OSError` the item is still included so callers
        can inspect the full attempted set.

    Raises
    ------
    FileNotFoundError
        If *undo_file* does not exist.
    ValueError
        If the file is not valid JSON.
    """
    undo_path = Path(undo_file)
    if not undo_path.exists():
        raise FileNotFoundError(f"Undo file not found: {undo_file!r}")

    with open(undo_path, encoding="utf-8") as fp:
        try:
            undo_map: dict[str, str] = json.load(fp)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid undo file JSON: {exc}") from exc

    results: list[tuple[str, str]] = []
    for new_path_str, old_path_str in undo_map.items():
        new_path = Path(new_path_str)
        old_path = Path(old_path_str)
        try:
            new_path.rename(old_path)
        except OSError as exc:
            # best-effort; caller receives the full pair list
            logger.warning("rename: undo failed for %s -> %s: %s",
                           new_path_str, old_path_str, exc)
        results.append((new_path_str, old_path_str))

    return results
