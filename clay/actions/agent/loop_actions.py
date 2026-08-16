import os
from ...run import engine
from ...run import logger
from ...lib.flags import is_truthy
from ...lib import paths
from ..registry import action as _action_decorator, req, opt, handler_for


@_action_decorator('loop')
class Loop:
    id:          str = req("Output key for the complete final iteration context")
    file:        str = req("Path to the sub-workflow JSON file to run each iteration")
    iterations:  int = opt("Max iterations. 0 or absent = infinite (requires continueKey)", 0)
    continueKey: str = opt("Sub-workflow output key checked for stop signal (false/done/0/no/stop/empty)", None)
    outputKey:   str = opt("Secondary storage key for the complete final iteration context", "final")
    merge:      bool = opt("Publish the last iteration's action ids into the calling workflow instead of one nested dict", False)


@handler_for('loop')
def handler(action, ctx, auto=False, auto_context=None, engine_globals=None):
    """
    Loop action — runs a sub-workflow file repeatedly.

    Context passed to each iteration:
      - parent_seed: the ctx received by the loop action (workflow context at
        the point the loop is invoked), held constant for all iterations
      - prev_result_data: full step_output from the previous iteration, merged
        on top of parent_seed so action IDs from the last run are available and
        overwrite stale values from earlier iterations (one iteration of memory)
      - iteration: current iteration number as a string
    """
    log = logger.get()
    ref = action.get('file')
    if not ref:
        logger.error("loop: missing 'file' field")
        return None

    filename = paths.workflow_asset(ref)
    if filename is None:
        logger.error(
            f"loop: '{ref}' not found beside the calling workflow "
            f"({paths.current_workflow()})")
        return None

    raw_iterations = action.get('iterations', 0)
    try:
        max_iterations = int(raw_iterations) if raw_iterations else 0
    except (ValueError, TypeError):
        logger.warn(f"loop: invalid iterations value '{raw_iterations}', defaulting to 0 (infinite)")
        max_iterations = 0
    infinite = max_iterations == 0
    if not infinite:
        max_iterations = min(max_iterations, 10000)

    continue_key = action.get('continueKey')
    if infinite and not continue_key:
        logger.warn("loop: infinite mode requires 'continueKey' — defaulting to 1000 iterations")
        max_iterations = 1000
        infinite = False

    # Holds the original calling context — never modified between iterations.
    parent_seed = {**(engine_globals or {}), **ctx}

    # Carries the previous iteration's full step_output forward so action
    # outputs are available in the next iteration (overwriting same-named keys).
    # Empty on the first iteration so parent_seed values are used as-is.
    prev_result_data = {}

    result_data = {}
    i = 0

    while True:
        i += 1
        if not infinite and i > max_iterations:
            break
        label = '∞' if infinite else str(max_iterations)
        if log:
            log.log(f'LOOP  iter={i}/{label}  {os.path.basename(filename)}')
        logger.emit('loop.iteration', iteration=i, max=max_iterations if not infinite else None,
                    file=os.path.basename(filename))

        iteration_seed = {
            **parent_seed,
            **prev_result_data,   # previous iteration's outputs overwrite stale parent values
            'iteration': str(i),  # always reflects the current iteration number
        }

        run_kwargs = {"initial_data": iteration_seed, "auto": auto}
        if auto_context is not None:
            run_kwargs["inherited_auto_context"] = auto_context
        result_data = engine.run(filename, **run_kwargs)

        if result_data is None:
            logger.info(f"loop: iteration {i} returned no data, stopping")
            break

        # Keep one iteration of memory — next iteration sees this run's outputs.
        prev_result_data = result_data

        if continue_key:
            continue_val = result_data.get(continue_key, '')
            # Same reading of "yes" the `when` gate uses — one vocabulary, so a
            # model answering NO stops a loop and closes a gate identically.
            if not is_truthy(continue_val):
                if log:
                    log.log(f'LOOP  early stop at iter={i}  {continue_key}="{continue_val}"')
                logger.info(f"loop: stopping at iteration {i} ({continue_key}={continue_val!r})")
                break

    # Without merge the loop stores one dict — the whole final step_output —
    # under its own id, which a caller cannot put in a prompt or gate a `when`
    # on without rendering the entire nested run. merge publishes the last
    # iteration's action ids into the calling workflow instead, so a nested
    # pass composes with the workflow around it the way a plain action does.
    # Off by default: it writes into the caller's namespace, and an existing
    # workflow must not start doing that because it was upgraded.
    if action.get("merge"):
        return {"id": action.get("id"), "data": result_data, "merge": True}
    return {"id": action.get("id"), "data": result_data}
