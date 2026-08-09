"""Workflow engine — loads workflow JSON and runs its steps in order.

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
    """Log/emit that the run was cancelled so the UI and log record it."""
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
    return step_output


def load_file(filename: str) -> dict | None:
    """Load a workflow JSON file. Returns None (and reports) on any failure."""
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
    """Shared execution core. Runs pre-parsed workflow JSON — never reads from files.

    The workflow's own directory is not a parameter and is not in the context.
    `run` pushes it onto the paths stack for the duration of the call, and the
    handlers that need it read it from there.
    """
    log = logger.get()
    owns_log = log is None

    if owns_log:
        # Fresh run — discard any stale stop request from a previous run.
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
        # One root-only prerequisite pass. Nested workflows and loop bodies
        # re-enter with an active logger, so they do not repeat these checks.
        if owns_log:
            preflight.run_checks(data)
        result = process_steps(workflow_steps, actions, seed, auto=auto,
                               auto_context=auto_context, daemon=daemon)

        if owns_log:
            divider = '═' * 56
            log.log(divider)
            log.log(f'RUN COMPLETE  {label}')
            log.log(divider)
            # Emit before stop() — the event must land in the log file as well
            # as reach listeners. The finally below owns the actual teardown.
            logger.emit(events.RUN_COMPLETE, label=label, log_path=log.path)

        return result
    except Exception as exc:
        if owns_log:
            # One existing event reaches terminal, Qt, Telegram and daemon
            # clients. Known WorkflowFailure is handled cleanly at the CLI;
            # programming exceptions are still re-raised for their traceback.
            log.log(f'!! RUN FAILED  {label}: {exc}')
            logger.emit(events.RUN_ERROR, message=str(exc), label=label,
                        log_path=log.path)
        raise
    finally:
        if owns_log:
            logger.stop()


def run_from_data(data: dict, label: str = 'api-run', initial_data: dict | None = None,
                  *, auto: bool = False) -> dict:
    """Run a workflow from pre-parsed JSON. Used when JSON is sent directly
    (e.g. from the API) instead of loaded from a file. Never touches disk.

    Nothing is pushed onto the workflow stack: JSON that arrived over the wire
    has no directory. An action reaching for a file beside the workflow reports
    that there is none, rather than resolving against wherever clayd is running.
    """
    return _execute(data, label=label, initial_data=initial_data, auto=auto)


def run(filename: str, initial_data: dict | None = None, *,
        auto: bool = False, daemon: bool = False,
        inherited_auto_context=None) -> dict | None:
    """Run a resolved workflow file. Returns the final context, or None if the
    file could not be loaded.

    `filename` is already resolved — the CLI resolves what was typed, and the
    workflow and loop actions resolve a sub-workflow reference through
    `paths.workflow_asset`, which is where a directory becomes its main.json.
    Resolving again here would mean two layers deciding what a name means.

    The file's directory is pushed for the duration of the run, so the assets
    the workflow ships with resolve against it — including for a sub-workflow,
    which pushes its own directory when it re-enters here.
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
