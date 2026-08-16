"""Context filtering utilities for action handlers."""

# Preserve this public compatibility constant. An absent includedData field
# passes every accumulated value to the action.
RESERVED_KEYS = frozenset()

# Engine-seeded globals. Ordinary actions must list these in includedData to
# receive them when filtering. The dispatcher independently reseeds them across
# workflow/loop boundaries so nested runs do not lose run configuration.
PASSTHROUGH_KEYS = frozenset({'__config__', '__schema__', '__workflow_template__'})


def _resolve_path(base: dict, path: str):
    """Resolve a dotted dictionary path and return (value, found)."""
    val = base
    for part in path.split('.'):
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return None, False
    return val, True


def build_ctx(step_output: dict, action: dict) -> dict:
    """Build the context dict passed to an action handler.

    Without includedData, return a shallow copy of all accumulated values.

    With includedData, return only listed keys. Engine globals require explicit
    inclusion. Entries support dotted paths and optional aliases:
      "key"          → ctx["key"] = step_output["key"]
      "a.b"          → ctx["b"]   = step_output["a"]["b"]   (leaf as key name)
      "alias=a.b.c"  → ctx["alias"] = step_output["a"]["b"]["c"]
    """
    included = action.get('includedData')
    if included is None:
        # Isolate handler key changes from the accumulated engine context.
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
