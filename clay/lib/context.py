"""Context filtering utilities for action handlers."""

# Kept as a public compatibility constant. Nothing is blocked: when
# includedData is absent, every accumulated value is passed to the action.
RESERVED_KEYS = frozenset()

# Engine-seeded globals. Ordinary actions must list these in includedData to
# receive them when filtering. The dispatcher independently reseeds them across
# workflow/loop boundaries so nested runs do not lose run configuration.
PASSTHROUGH_KEYS = frozenset({'__config__', '__schema__', '__workflow_template__'})


def _resolve_path(base: dict, path: str):
    """Walk a dot-separated path into nested dicts. Returns (value, found)."""
    val = base
    for part in path.split('.'):
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return None, False
    return val, True


def build_ctx(step_output: dict, action: dict) -> dict:
    """Build the context dict passed to an action handler.

    When includedData is absent: returns everything minus RESERVED_KEYS
    (backward-compatible, no change for existing actions).

    When includedData is present: returns only the listed keys.
    Engine-seeded globals (__config__, __schema__, __workflow_template__) are
    only delivered when explicitly listed — the engine does NOT auto-inject
    them.
    Supports dot-paths and optional alias prefix:
      "key"          → ctx["key"] = step_output["key"]
      "a.b"          → ctx["b"]   = step_output["a"]["b"]   (leaf as key name)
      "alias=a.b.c"  → ctx["alias"] = step_output["a"]["b"]["c"]
    """
    included = action.get('includedData')
    if included is None:
        # Return a shallow copy so handlers can add/remove input keys without
        # mutating the engine's accumulated context.
        return dict(step_output)

    ctx = {}
    for entry in included:
        if '=' in entry:
            alias, path = entry.split('=', 1)
        else:
            alias = entry.rsplit('.', 1)[-1]   # leaf segment as ctx key
            path = entry
        if '.' in path:
            val, found = _resolve_path(step_output, path)
            if found:
                ctx[alias] = val
        elif path in step_output:
            ctx[alias] = step_output[path]
    return ctx
