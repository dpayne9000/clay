"""
Action schema registry — single source of truth for all workflow action types.

    from clay.actions.registry import validate, schema, export_json

    errors = validate(action_dict)   # → list[str]  (empty = valid)
    s      = schema('shell')         # → JSON Schema dict for one type
    dump   = export_json()           # → combined JSON string (all types)

Run as a script to print JSON Schema:
    python -m clay.actions.registry            # all types
    python -m clay.actions.registry shell      # one type
"""
from __future__ import annotations

import json
import typing
from dataclasses import MISSING, dataclass, field, fields as dc_fields
from typing import Any, Union, get_args, get_origin


# ── Field descriptors ─────────────────────────────────────────────────────────

def req(desc: str, *, export: bool = True, skeleton: bool = True) -> Any:
    """Required field — must be present in the action JSON.

    export=False   omit from the JSON Schema export (still validated).
    skeleton=False omit from the generated workflow skeleton.
    """
    return field(metadata={"desc": desc, "export": export, "skeleton": skeleton})

def opt(desc: str, default: Any = None, *,
        export: bool = True, skeleton: bool = True) -> Any:
    """Optional field with a default value (None if not specified).

    export=False   omit from the JSON Schema export (still validated).
    skeleton=False omit from the generated workflow skeleton.
    """
    return field(default=default,
                 metadata={"desc": desc, "export": export, "skeleton": skeleton})


# ── Registry + decorators ─────────────────────────────────────────────────────

_REGISTRY: dict[str, type] = {}
_HANDLERS: dict[str, Any] = {}
_FLAGS: dict[str, dict[str, bool]] = {}

def action(type_name: str, *, export: bool = True, skeleton: bool = True):
    """Register a plain class as a dataclass action schema.

    export=False   dispatchable and validated, but hidden from the manifest.
    skeleton=False excluded from the generated workflow skeleton.
    """
    def decorator(cls):
        _REGISTRY[type_name] = dataclass(cls)
        _FLAGS[type_name] = {"export": export, "skeleton": skeleton}
        return _REGISTRY[type_name]
    return decorator

def handler_for(type_name: str):
    """Register a callable as the handler for an action type."""
    def decorator(func):
        _HANDLERS[type_name] = func
        return func
    return decorator

def handler_for_type(type_name: str):
    """Return the registered handler for an action type, or None."""
    return _HANDLERS.get(type_name)

def flags(type_name: str) -> dict[str, bool]:
    """Return the export/skeleton flags for an action type."""
    return _FLAGS.get(type_name, {"export": True, "skeleton": True})


# ── Discovery ─────────────────────────────────────────────────────────────────

_discovered = False

def _apply_module_order(modules: list[str]) -> None:
    """Reorder _REGISTRY so its types follow module-walk order.

    importlib.import_module() is a no-op for a module that is already in
    sys.modules, so the decorators fire in first-import order, not walk order.
    Anything that imports an action module directly before discover() runs
    (a unit test, for example) would otherwise pull that module's types to the
    front of the registry. Sorting afterwards makes discover()'s ordering
    guarantee hold regardless of import history.

    The sort is stable: types registered by the same module keep their
    definition order, and any type whose module is outside the walk keeps its
    relative position at the end.
    """
    rank = {name: position for position, name in enumerate(modules)}
    ordered = sorted(_REGISTRY.items(),
                     key=lambda item: rank.get(item[1].__module__, len(rank)))
    _REGISTRY.clear()
    _REGISTRY.update(ordered)


def discover(*, force: bool = False) -> None:
    """Import every module under clay.actions so the decorators register.

    Modules are imported in sorted name order, not filesystem order:
    registration order determines the oneOf sequence in export_json() and the
    emission order of the skeleton generator, and both must be reproducible
    across machines.
    """
    global _discovered

    if _discovered and not force:
        return

    import importlib
    import pkgutil

    package = importlib.import_module(__package__)

    modules = sorted(
        info.name
        for info in pkgutil.walk_packages(package.__path__, package.__name__ + ".")
    )

    for name in modules:
        importlib.import_module(name)

    _apply_module_order(modules)
    _discovered = True


# ── Validation ────────────────────────────────────────────────────────────────

def validate(action: dict) -> list[str]:
    """
    Validate an action dict against its registered schema.
    Returns a list of error strings; empty list means valid.
    Unknown action types return an empty list (dispatcher handles them).
    """
    action_type = action.get('type')
    if not action_type:
        return ["missing 'type' field"]

    cls = _REGISTRY.get(action_type)
    if cls is None:
        return []  # unknown type — let the dispatcher report it

    return [
        f"'{action_type}' missing required field '{f.name}'"
        for f in dc_fields(cls)
        if f.default is MISSING and f.default_factory is MISSING
        and f.name not in action
    ]


# ── JSON Schema export ────────────────────────────────────────────────────────

_PY_TO_JSON: dict[type, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}

def _json_type(annotation) -> str | None:
    # Unwrap Optional[X] (i.e. Union[X, None]) → X
    if get_origin(annotation) is Union:
        annotation = next((a for a in get_args(annotation) if a is not type(None)), annotation)
    return _PY_TO_JSON.get(annotation)

def schema(type_name: str) -> dict:
    """Return a JSON Schema object for one action type."""
    cls = _REGISTRY[type_name]
    hints = typing.get_type_hints(cls)
    props: dict = {"type": {"type": "string", "const": type_name}}
    required = ["type"]

    for f in dc_fields(cls):
        if not f.metadata.get("export", True):
            continue
        is_required = f.default is MISSING and f.default_factory is MISSING
        prop: dict = {"description": f.metadata.get("desc", "")}
        json_type = _json_type(hints.get(f.name))
        if json_type:
            prop["type"] = json_type
        if not is_required and f.default is not None:
            prop["default"] = f.default
        props[f.name] = prop
        if is_required:
            required.append(f.name)

    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": True,
    }

# Fields every action accepts, declared by no action class. Defined once here
# rather than injected into all 39 per-type schemas: this document is pulled
# verbatim into model prompts (see the NOTE below), so a field repeated per
# type is a field paid for 39 times. Every entry sets additionalProperties:
# true, so these validate wherever they appear.
_UNIVERSAL_PROPERTIES: dict = {
    "visible": {
        "description": (
            "Set false to hide this action from every front-end — no start "
            "line, no result, no file/command/prompt output. The log file "
            "still records all of it, and errors are always shown."
        ),
        "type": "boolean",
        "default": True,
    },
    "when": {
        "description": (
            "Run this action only if the named earlier output means yes. "
            "'false', 'done', '0', 'no', 'stop' and empty mean no; anything "
            "else means yes, so a model answering YES or NO gates directly. "
            "The key is read from the run's accumulated output and does not "
            "need to be in includedData. A skipped action stores nothing."
        ),
        "type": "string",
    },
    "whenNot": {
        "description": (
            "The mirror of 'when': run this action only if the named earlier "
            "output means no. Use it for the other half of a branch — the "
            "action that handles the case 'when' skips. Both fields together "
            "mean both must hold."
        ),
        "type": "string",
    },
}


def all_schemas() -> dict:
    """Return a combined JSON Schema with oneOf discriminated by the 'type' field."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12",
        "title": "ClayAction",
        "$defs": {"universalFields": {"properties": dict(_UNIVERSAL_PROPERTIES)}},
        "oneOf": [schema(name) for name in _REGISTRY if flags(name)["export"]],
    }

# NOTE: export_json() is imported directly by clay/cli.py and clay/lib/config.py
# to seed the '__schema__' context key. Those imports are intentional and stay
# as they are for now, but the payload needs proper formatting work later: it is
# raw JSON Schema (~27k chars) and is pulled into model prompts by
# workflows/system/editor/iteration.json, system/coding/iteration.json and
# dev/system/editor/iteration.json. Every field added here grows those prompts.
# A prompt-shaped rendering (compact per-type field lists rather than full JSON
# Schema envelopes) should replace the direct export_json() dump.
def export_json(indent: int = 2) -> str:
    """Serialise all_schemas() to a JSON string."""
    return json.dumps(all_schemas(), indent=indent)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    discover()
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name not in _REGISTRY:
            print(f"Unknown action type '{name}'. Known types: {', '.join(_REGISTRY)}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(schema(name), indent=2))
    else:
        print(export_json())
