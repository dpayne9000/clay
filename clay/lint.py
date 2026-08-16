"""
Workflow linter — validates all .json files under a directory.

Three checks are applied, in order:

  1. Parse        — valid JSON, top-level object
  2. Shape        — auto-detects file role from structure:
                      workflow  → has 'workflow' + 'actionSets'
                      data      → everything else (context, training, goals)
  3. Semantics    — per-role rules (see below)

Workflow semantics:
  - Every step in workflow.steps has a matching actionSet
  - Every actionSet key is referenced in workflow.steps
  - Every action passes required-field validation against the schema registry
  - Every action field is declared by that action type's schema. Undeclared
    fields are reported as warnings: the handler never reads them, so they are
    silently ignored at runtime. 'type', 'includedData', 'outputKey' and
    underscore-prefixed keys ('_comment') belong to no single type and are
    always allowed. This is a name-level check only — value types and ranges
    are not validated.
  - includedData scope: every key listed in includedData must be produced by
    a preceding action (in step execution order), present in defaults, an
    engine-seeded system key (lib.context.PASSTHROUGH_KEYS), or injected by a
    caller via their own
    includedData when this file is invoked as a sub-workflow or loop iteration.
    loadContext actions expand scope with all top-level keys from their file.

Data semantics:
  - Any JSON object is valid context data. Nested objects are intentionally
    supported because includedData can select values with dot paths.

Usage:
    python -m clay.lint [directory]          # default: your workflow folder
    python -m clay.lint path/to/file.json    # single file
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, fields as dc_fields
from typing import Optional

from .actions.registry import discover as _discover_actions, validate as _validate_action, _REGISTRY
from .lib.context import PASSTHROUGH_KEYS
from .lib import paths as _paths

# lint.py is imported standalone (e.g. by test_lint.py) without going through
# cli.py/dispatcher.py, so it must trigger discovery itself to populate
# _REGISTRY from the handler modules' @action declarations.
_discover_actions()


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class LintResult:
    path: str
    role: str = "unknown"          # 'workflow' | 'data' | 'invalid'
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# ── Role detection ────────────────────────────────────────────────────────────

def _detect_role(data: dict) -> str:
    if "workflow" in data and "actionSets" in data:
        return "workflow"
    return "data"


# ── includedData scope helpers ────────────────────────────────────────────────

# Keys always available regardless of workflow structure. Taken from
# lib.context so the linter cannot drift from what the engine actually seeds —
# a global added there used to have to be added here too, and a miss made lint
# reject a legitimate workflow.
_SYSTEM_KEYS: frozenset[str] = PASSTHROUGH_KEYS
# Keys injected by the loop engine for every iteration
_LOOP_INJECTED_KEYS: frozenset[str] = frozenset({'iteration'})

# Action fields that belong to no single type: 'type' is the discriminator,
# 'includedData' is consumed by build_ctx before the handler ever sees it,
# 'outputKey' is consumed by the engine when it stores the result, and
# 'visible' is read by clay.run.logger to decide whether this action's events
# reach a front-end. Underscore-prefixed keys ('_comment') are a documentation
# convention.
_UNIVERSAL_FIELDS: frozenset[str] = frozenset({'type', 'includedData', 'visible', 'when', 'whenNot', 'outputKey'})


def _declared_fields(action_type: str) -> set[str]:
    """Field names an action type declares in the schema registry."""
    cls = _REGISTRY.get(action_type)
    if cls is None:
        return set()
    return {f.name for f in dc_fields(cls)}


def _included_root(entry: str) -> str:
    """Return the root context key for an includedData entry.

    'alias=key.sub' → 'key'
    'key.sub'       → 'key'
    'key'           → 'key'
    """
    path = entry.split('=', 1)[1] if '=' in entry else entry
    return path.split('.')[0]


def _included_target(entry: str) -> str:
    """Return the top-level key delivered to an action by includedData.

    build_ctx preserves an explicit alias and otherwise names a selected dot
    path by its final component:

    'alias=key.sub' → 'alias'
    'key.sub'       → 'sub'
    'key'           → 'key'
    """
    if '=' in entry:
        return entry.split('=', 1)[0]
    return entry.rsplit('.', 1)[-1]


def _resolve_file_ref(ref: str, caller_dir: str) -> str | None:
    """Find the workflow file `ref` names from inside `caller_dir`, or None.

    The linter resolves statically, with no run in progress, so it pushes the
    calling workflow's directory as a frame and asks the same question the
    engine asks. Borrowing the frame rather than adding a resolve-against-this
    -directory variant is what keeps one rule for where a workflow's assets
    live — a linter that resolved references its own way could pass a file the
    engine would then fail to find.
    """
    with _paths.in_workflow(caller_dir):
        resolved = _paths.workflow_asset(ref)
    # An absolute ref is handed back unchanged, so it still needs checking.
    return resolved if resolved and os.path.isfile(resolved) else None


def _collect_external_keys(
    file_data: dict[str, dict],
) -> tuple[dict[str, set], set[str], set[str]]:
    """Scan all parsed workflow files and determine which context keys each
    sub-workflow / loop-iteration file can receive from its callers.

    Returns:
        external_keys_map  — {abs_path: set of root key strings}
        loop_files         — abs paths called as loop iterations
                             (their own action IDs are also available from
                             the previous iteration's outputs)
        unconstrained      — abs paths called with no includedData by at
                             least one caller (full parent ctx flows through;
                             scope cannot be statically verified)
    """
    external_keys_map: dict[str, set] = {}
    loop_files: set[str] = set()
    unconstrained: set[str] = set()

    for caller_path, data in file_data.items():
        if not isinstance(data, dict):
            continue
        caller_dir = os.path.dirname(caller_path)

        for actions in data.get('actionSets', {}).values():
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                action_type = action.get('type')
                if action_type not in ('workflow', 'loop'):
                    continue
                file_ref = action.get('file', '')
                if not file_ref:
                    continue
                target = _resolve_file_ref(file_ref, caller_dir)
                if not target:
                    continue

                if action_type == 'loop':
                    loop_files.add(target)

                included = action.get('includedData')
                if not isinstance(included, list):
                    # No includedData → full parent context passes through
                    unconstrained.add(target)
                    continue

                if target not in external_keys_map:
                    external_keys_map[target] = set()
                for entry in included:
                    if isinstance(entry, str):
                        external_keys_map[target].add(_included_target(entry))

    return external_keys_map, loop_files, unconstrained


def _all_action_ids(data: dict) -> set[str]:
    """Collect every action id defined anywhere in a workflow file."""
    ids: set[str] = set()
    for actions in data.get('actionSets', {}).values():
        if isinstance(actions, list):
            for action in actions:
                if isinstance(action, dict) and action.get('id'):
                    ids.add(action['id'])
    return ids


def _lint_included_data_scope(
    data: dict,
    result: LintResult,
    external_keys: set[str],
    file_path: str,
) -> None:
    """Verify every includedData key is in scope when the action runs.

    Scope at any action = defaults ∪ system_keys ∪ loop_injected ∪
                          external_keys (from caller's includedData) ∪
                          IDs of all preceding actions (in step order).

    loadContext actions immediately expand scope with the referenced file's
    top-level keys (since merge=True flattens them into step_output).
    """
    steps = data.get('workflow', {}).get('steps', [])
    action_sets = data.get('actionSets', {})
    defaults = set((data.get('defaults') or {}).keys())
    base_dir = os.path.dirname(os.path.abspath(file_path))

    available: set[str] = set()
    available |= defaults
    available |= _SYSTEM_KEYS
    available |= _LOOP_INJECTED_KEYS
    available |= external_keys

    for step in steps:
        actions = action_sets.get(step, [])
        if not isinstance(actions, list):
            continue
        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                continue
            loc = f"[{step}][{i}]"

            included = action.get('includedData')
            if isinstance(included, list):
                for entry in included:
                    if not isinstance(entry, str):
                        continue
                    root = _included_root(entry)
                    if root not in available:
                        display = f"'{entry}'" if entry != root else f"'{root}'"
                        result.errors.append(
                            f"{loc} includedData {display}: "
                            f"'{root}' is not produced by any preceding action"
                        )

            # Add this action's output to scope for subsequent actions
            action_id = action.get('id')
            if action_id:
                available.add(action_id)

            # loadContext merges a file's top-level keys directly into scope
            if action.get('type') == 'loadContext':
                ctx_ref = action.get('file', '')
                ctx_path = _resolve_file_ref(ctx_ref, base_dir)
                if ctx_path:
                    try:
                        with open(ctx_path) as f:
                            ctx_data = json.load(f)
                        if isinstance(ctx_data, dict):
                            available |= set(ctx_data.keys())
                    except Exception:
                        pass


# ── Per-role validators ───────────────────────────────────────────────────────

def _lint_workflow(data: dict, result: LintResult,
                   external_keys: set[str] | None = None,
                   skip_scope: bool = False) -> None:
    steps = data.get("workflow", {}).get("steps", [])
    action_sets = data.get("actionSets", {})

    if not steps:
        result.warnings.append("workflow.steps is empty")

    # step ↔ actionSet cross-reference
    for step in steps:
        if step not in action_sets:
            result.errors.append(f"step '{step}' has no matching actionSet")

    for key in action_sets:
        if key not in steps:
            result.warnings.append(f"actionSet '{key}' is not referenced in workflow.steps")

    # per-action checks
    known_types = set(_REGISTRY.keys())
    for step, actions in action_sets.items():
        if not isinstance(actions, list):
            result.errors.append(f"actionSet '{step}' must be an array")
            continue
        for i, action in enumerate(actions):
            loc = f"[{step}][{i}]"
            if not isinstance(action, dict):
                result.errors.append(f"{loc} action must be an object")
                continue

            action_type = action.get("type")
            if not action_type:
                result.errors.append(f"{loc} missing 'type'")
                continue

            if action_type not in known_types:
                result.warnings.append(f"{loc} unknown action type '{action_type}'")
                continue

            # required-field schema check
            for e in _validate_action(action):
                result.errors.append(f"{loc} {e}")

            # Undeclared fields: present in the JSON but never read by the
            # handler, so they are silently ignored at runtime. Warning only —
            # the emitted JSON Schema sets additionalProperties: true.
            declared = _declared_fields(action_type)
            for name in sorted(set(action) - declared - _UNIVERSAL_FIELDS):
                if name.startswith('_'):
                    continue
                result.warnings.append(
                    f"{loc} unknown field '{name}' on '{action_type}' — "
                    f"ignored at runtime (valid: {', '.join(sorted(declared))})"
                )

    # includedData scope check (skipped when caller passes unconstrained ctx)
    if not skip_scope:
        _lint_included_data_scope(data, result, external_keys or set(),
                                  result.path)


def _lint_data(data: dict, result: LintResult) -> None:
    """A top-level JSON object is valid context data at any nesting depth."""


# ── File-level entry point ────────────────────────────────────────────────────

def lint_file(path: str,
              external_keys: set[str] | None = None,
              skip_scope: bool = False) -> LintResult:
    result = LintResult(path=path)

    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        result.role = "invalid"
        result.errors.append(f"invalid JSON: {e}")
        return result
    except OSError as e:
        result.role = "invalid"
        result.errors.append(str(e))
        return result

    if not isinstance(data, dict):
        result.role = "invalid"
        result.errors.append("top-level value must be a JSON object")
        return result

    result.role = _detect_role(data)

    if result.role == "workflow":
        _lint_workflow(data, result,
                       external_keys=external_keys,
                       skip_scope=skip_scope)
    else:
        _lint_data(data, result)

    return result


# ── Directory walk ────────────────────────────────────────────────────────────

def lint_dir(root: str) -> list[LintResult]:
    # Phase 1: parse every JSON file so we can do cross-file analysis.
    file_data: dict[str, dict] = {}
    paths: list[str] = []
    for dirpath, _, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith(".json"):
                path = os.path.join(dirpath, name)
                paths.append(path)
                try:
                    with open(path) as f:
                        parsed = json.load(f)
                    if isinstance(parsed, dict):
                        file_data[os.path.abspath(path)] = parsed
                except Exception:
                    pass

    # Phase 2: determine external keys for each sub-workflow / loop file.
    ext_map, loop_files, unconstrained = _collect_external_keys(file_data)

    # Loop iteration files also receive all their own action IDs from the
    # previous iteration's step_output (the loop engine merges prev_result_data).
    for abs_path in loop_files:
        data = file_data.get(abs_path)
        if data:
            ext_map.setdefault(abs_path, set()).update(_all_action_ids(data))

    # Phase 3: lint each file with the resolved scope information.
    results = []
    for path in paths:
        abs_path = os.path.abspath(path)
        ext_keys = ext_map.get(abs_path, set())
        skip = abs_path in unconstrained
        results.append(lint_file(path, external_keys=ext_keys, skip_scope=skip))
    return results


def lint(path: str) -> list[LintResult]:
    """Lint a single file or every .json under a directory."""
    if os.path.isfile(path):
        return [lint_file(path)]
    return lint_dir(path)


# ── Reporter ──────────────────────────────────────────────────────────────────

_ROLE_LABEL = {"workflow": "workflow", "data": "data    ", "invalid": "INVALID "}
_ICONS = {"workflow": "⬡", "data": "◦", "invalid": "✗"}


def report(results: list[LintResult]) -> int:
    """
    Print a lint report, one line per file checked (clean or not), followed
    by a summary. Returns exit code (0 = all clean, 1 = errors found).
    """
    errors_total = 0
    cwd = os.getcwd()

    for r in results:
        rel = os.path.relpath(r.path, cwd)
        icon = "✗" if r.errors else ("△" if r.warnings else "✓")
        role = _ROLE_LABEL.get(r.role, r.role)
        print(f"\n{icon}  {rel}  [{role}]")

        for e in r.errors:
            print(f"   ✗ {e}")
            errors_total += 1
        for w in r.warnings:
            print(f"   △ {w}")

    total = len(results)
    clean = sum(1 for r in results if r.ok)
    errored = total - clean
    roles = {}
    for r in results:
        roles[r.role] = roles.get(r.role, 0) + 1

    role_summary = "  ".join(f"{v} {k}" for k, v in sorted(roles.items()))
    print(f"\n{'─' * 52}")
    print(f"  {total} files  ·  {clean} clean  ·  {errored} with errors")
    print(f"  {role_summary}")

    _print_findings(results, cwd)

    return 0 if errors_total == 0 else 1


def _print_findings(results: list[LintResult], cwd: str) -> None:
    """Print a compact one-line-per-issue list after the summary.

    The per-file output above is grouped and indented; this repeats every
    finding in a flat, greppable form so nothing scrolls out of reach.
    """
    errors = [(os.path.relpath(r.path, cwd), e)
              for r in results for e in r.errors]
    warnings = [(os.path.relpath(r.path, cwd), w)
                for r in results for w in r.warnings]

    for label, icon, items in (("Errors", "✗", errors),
                               ("Warnings", "△", warnings)):
        if not items:
            continue
        print(f"\n  {label} ({len(items)}):")
        for rel, msg in items:
            print(f"    {icon} {rel}  {msg}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    from .lib import paths as _paths
    path = args[0] if args else _paths.workflow_folder()

    if not os.path.exists(path):
        print(f"lint: path not found: {path}", file=sys.stderr)
        return 1

    results = lint(path)
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
