import json
import os
from ...run import logger
from ...lib import paths
from ..registry import action as _action_decorator, req, handler_for


@_action_decorator('loadContext', skeleton=False)
class LoadContext:
    id:   str = req("Context key for a plain-text file's contents. Ignored for JSON objects, whose keys merge directly")
    file: str = req("Path to a file beside the workflow. A JSON object merges its top-level keys into context; anything else loads as text under `id`")


@handler_for('loadContext')
def load_handler(action, ctx):
    """
    loadContext — reads a file that ships *with the workflow* and puts it into
    context. Paths resolve against the workflow's own directory, never the
    workspace: a workflow's assets are part of its sequencing data, not part of
    the directory the user is working in.

    A JSON object merges its top-level keys directly (merge=True tells
    process_steps to unpack rather than store under one name). Anything else —
    prose, a prompt template, training text — loads as a string under `id`.

    The fallback triggers on a JSON *parse* failure only. A file that parses
    cleanly into a list or a bare string is still an error: it was written as
    JSON and meant something structured, and quietly handing the workflow its
    source text instead would hide the mistake.
    """
    ref = action.get('file')
    if not ref:
        logger.error("loadContext: missing 'file'")
        return None

    path = paths.workflow_asset(ref)
    if path is None:
        if paths.current_workflow() is None:
            logger.error(
                f"loadContext: cannot resolve '{ref}' — this workflow was run "
                f"from data, not from a file, so it has no directory to read "
                f"assets from")
        else:
            logger.error(
                f"loadContext: '{ref}' not found beside the workflow "
                f"({paths.current_workflow()})")
        return None

    if not os.path.exists(path):
        logger.error(f"loadContext: file not found: {path}")
        return None

    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"loadContext: failed to read {path}: {e}")
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _as_text(action, path, text)

    if not isinstance(data, dict):
        logger.error(f"loadContext: expected a JSON object in {path}")
        return None

    logger.debug(f"loadContext: loaded {len(data)} keys from {path}")
    for key in data:
        logger.debug(f"  {key}: {str(data[key])[:80]}")

    # merge=True tells process_steps to unpack all keys into previous_data
    return {"id": action.get("id"), "data": data, "merge": True}


def _as_text(action, path, text):
    """Load `text` under the action's id. Requires one, unlike the JSON path.

    For a JSON object `id` is genuinely unused — the file names its own keys.
    Text has no such names, so `id` becomes the only handle the workflow has on
    what it just read, and a missing one would load the file into nothing.
    """
    key = action.get('id')
    if not key:
        logger.error(
            f"loadContext: {path} is not JSON, so 'id' is required — it names "
            f"the context key the text loads into")
        return None

    logger.debug(f"loadContext: loaded {len(text)} chars from {path} as '{key}'")
    return {"id": key, "data": text}
