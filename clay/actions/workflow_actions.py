import os
from ..run import engine
from ..run import logger
from ..lib import paths
from .registry import action as _action_decorator, req, opt, handler_for

_running = set()


@_action_decorator('workflow')
class Workflow:
    id:        str = req("Output key for the sub-workflow result")
    file:      str = req("Path to the workflow JSON file to run")
    outputKey: str = opt("Compatibility field; currently ignored because the complete sub-workflow context is stored under id", "final")


@handler_for('workflow')
def handler(action, ctx, auto=False, auto_context=None, engine_globals=None):
    log = logger.get()
    ref = action.get('file')
    if not ref:
        logger.error("workflow action missing 'file' field")
        return None

    filename = paths.workflow_asset(ref)
    if filename is None:
        logger.error(
            f"workflow: '{ref}' not found beside the calling workflow "
            f"({paths.current_workflow()})")
        return None

    if filename in _running:
        logger.warn(f"'{filename}' is already in the call stack — possible cycle")

    _running.add(filename)
    if log:
        log.log(f'WORKFLOW →  {filename}')
        log.depth += 1

    try:
        child_seed = {**(engine_globals or {}), **ctx}
        run_kwargs = {"initial_data": child_seed, "auto": auto}
        if auto_context is not None:
            run_kwargs["inherited_auto_context"] = auto_context
        result_data = engine.run(filename, **run_kwargs)
        action_id = action.get('id')
        return {"id": action_id, "data": result_data} if action_id else None
    finally:
        _running.discard(filename)
        if log:
            log.depth -= 1
            log.log(f'WORKFLOW ←  {os.path.basename(filename)}')
