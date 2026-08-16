"""Load workflow JSON and execute its steps in order.

Public API: run() for a workflow file, run_from_data() for pre-parsed JSON,
dry_run() to print a file without executing, process_steps() to run steps
against an existing context. Per-action routing lives in dispatcher.dispatch;
cooperative stop flags live in cancellation.
"""
from __future__ import annotations

import json
import os

from . import cancellation
from . import dispatcher
from . import events
from . import logger as logger
from . import preflight
from ..lib import paths


def _note_cancelled(log):
    """Record cancellation in the event stream and run log."""
    logger.emit(events.RUN_CANCELLED)
    if log:
        log.log('!! CANCELLED  stopped by user')


def _effective_auto_context(inherited, local):
    """Layer workflow instructions parent-first, omitting empty values."""
    parts = [str(value).strip() for value in (inherited, local)
             if value is not None and str(value).strip()]
    return '\n\n'.join(parts) or None


def process_steps(steps: list, actions: dict, initial_data: dict | None = None, *,
                  auto: bool = False, auto_context=None, daemon: bool = False) -> dict:
    """Run each step's actions in order, accumulating results into one dict."""
    log = logger.get()
    step_output = dict(initial_data or {})
    for step in steps:
        if cancellation.is_cancelled():
            _note_cancelled(log)
            break
        logger.emit(events.STEP_START, step=step)
        if log:
            log.log(f'STEP  {step}')
        step_actions = actions.get(step, [])
        for action in step_actions:
            if cancellation.is_cancelled():
                _note_cancelled(log)
                break
            result = dispatcher.dispatch(action, step_output, auto=auto,
                                         auto_context=auto_context, daemon=daemon)
            if result:
                if result.get("merge") and isinstance(result.get("data"), dict):
                    step_output.update(result["data"])
                elif result.get("id"):
                    step_output[result["id"]] = result["data"]
                    output_key = action.get("outputKey")
                    if output_key:
                        step_output[output_key] = result["data"]
                    error_key = f'{result["id"]}_error'
                    if result.get("error"):
                        step_output[error_key] = result["error"]
                    else:
                        step_output.pop(error_key, None)
    return step_output


def load_file(filename: str) -> dict | None:
    """Load workflow JSON, reporting failures and returning None."""
    log = logger.get()
    try:
        with open(filename, 'r') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        msg = f"File not found: {filename}"
        logger.emit(events.RUN_ERROR, message=msg)
        if log:
            log.log(f'!! ERROR  {msg}')
    except json.JSONDecodeError:
        msg = f"Failed to decode JSON: {filename}"
        logger.emit(events.RUN_ERROR, message=msg)
        if log:
            log.log(f'!! ERROR  {msg}')
    except Exception as e:
        msg = f"An error occurred: {e}"
        logger.emit(events.RUN_ERROR, message=msg)
        if log:
            log.log(f'!! ERROR  {msg}')


def _execute(data: dict, label: str, initial_data: dict | None = None, *,
             auto: bool = False, daemon: bool = False,
             inherited_auto_context=None) -> dict:
    """Run pre-parsed workflow data without reading a workflow file.

    The workflow's own directory is not a parameter and is not in the context.
    `run` pushes it onto the paths stack for the duration of the call, and the
    handlers that need it read it from there.
    """
    log = logger.get()
    owns_log = log is None

    if owns_log:
        # A root run must not inherit a cancellation request from an earlier run.
        cancellation.clear_cancel()
        log = logger.start(label)
        divider = '═' * 56
        log.log(divider)
        log.log(f'RUN  {label}' + ('  [AUTO]' if auto else ''))
        log.log(f'LOG  {log.path}')
        log.log(divider)
        logger.emit(events.RUN_START, label=label, auto=auto, log_path=log.path)

    workflow_steps = data.get('workflow', {}).get('steps', [])
    actions = data.get('actionSets', {})
    defaults = data.get('defaults', {})
    auto_context = _effective_auto_context(
        inherited_auto_context, data.get('autoContext'))
    seed = {**defaults, **(initial_data or {})}

    try:
        # Run prerequisites once. Nested workflows reuse the active logger and
        # therefore skip this root-only check.
        if owns_log:
            preflight.run_checks(data)
        result = process_steps(workflow_steps, actions, seed, auto=auto,
                               auto_context=auto_context, daemon=daemon)

        if owns_log:
            divider = '═' * 56
            log.log(divider)
            log.log(f'RUN COMPLETE  {label}')
            log.log(divider)
            # Emit completion before finally closes the log.
            logger.emit(events.RUN_COMPLETE, label=label, log_path=log.path)

        return result
    except Exception as exc:
        if owns_log:
            # One event reports failures to every client. The CLI handles known
            # WorkflowFailure exceptions; programming errors retain tracebacks.
            log.log(f'!! RUN FAILED  {label}: {exc}')
            logger.emit(events.RUN_ERROR, message=str(exc), label=label,
                        log_path=log.path)
        raise
    finally:
        if owns_log:
            logger.stop()


def run_from_data(data: dict, label: str = 'api-run', initial_data: dict | None = None,
                  *, auto: bool = False) -> dict:
    """Run workflow data received directly instead of loading a workflow file.

    In-memory data has no workflow directory, so this function does not modify
    the workflow path stack. Relative workflow assets therefore fail instead of
    resolving against clayd's working directory.
    """
    return _execute(data, label=label, initial_data=initial_data, auto=auto)


def run(filename: str, initial_data: dict | None = None, *,
        auto: bool = False, daemon: bool = False,
        inherited_auto_context=None) -> dict | None:
    """Run a resolved workflow file and return its final context.

    The caller resolves `filename`. Workflow and loop actions resolve child
    references through paths.workflow_asset(), including directory-to-main.json
    conversion, so this function must not resolve the name again.

    The workflow's directory remains on the path stack during execution so its
    relative assets resolve correctly. Each child workflow pushes its own path.
    """
    data = load_file(filename)
    if data is None:
        return None
    with paths.in_workflow(os.path.dirname(os.path.abspath(filename))):
        return _execute(data, label=filename, initial_data=initial_data,
                        auto=auto, daemon=daemon,
                        inherited_auto_context=inherited_auto_context)


def dry_run(filename: str):
    """Print the parsed workflow JSON without executing anything."""
    data = load_file(filename)
    if data:
        print(json.dumps(data, indent=2))
