"""Validate actions and route them to registered handlers.

All handlers are resolved via clay.actions.registry.handler_for_type(), which
is populated by discover() importing every module under clay.actions. The few
types whose handlers take extra engine arguments (auto, auto_context, daemon)
are dispatched by explicit branches in dispatch() but still resolve their
callable through handler_for_type() rather than a direct module reference.

The running workflow's directory is not among those arguments. It lives on the
lib.paths stack, pushed by engine.run, and the handlers that resolve a file
beside their workflow read it from there.

Dispatch never prints. It emits action.start / action.complete / action.error
on the event bus (clay.run.logger) and each front-end renders what it wants.

An action carrying "visible": false emits to the log file but not to any
front-end — see logger.visible() and the note in dispatch().

An action carrying "when": "some_key" runs only when that key's accumulated
value means yes — see should_run() and the note in dispatch().
"""
from __future__ import annotations

import time

from . import approval
from . import events
from . import logger as logger
from .failure import WorkflowFailure
from ..actions.registry import discover as _discover, handler_for_type as _handler_for_type, validate as _validate
from ..lib.context import build_ctx, PASSTHROUGH_KEYS
from ..lib.flags import is_truthy

_discover()

# These action types present their own output and need no result preview.
_SILENT_RESULT_TYPES = frozenset({'humanDecision', 'humanShell', 'loop', 'workflow'})

# These action types do not raise a busy indicator. Keep this set separate from
# _SILENT_RESULT_TYPES because the two policies can change independently.
#
# The actions inside workflow and loop containers manage their own indicators.
# An inner active=False event would otherwise clear the container's indicator
# permanently. humanDecision and humanShell immediately wait for human input.
#
# io._floor_to_human() also clears indicators when an ordinary action pauses
# for manual approval.
_NO_BUSY_TYPES = frozenset({'workflow', 'loop', 'humanDecision', 'humanShell'})


def _action_fields(action: dict) -> dict:
    """Return action fields that a front-end may display.

    Structured data lets each renderer select fields without parsing prose.
    Renderers also control truncation and layout.
    """
    t = action.get('type', '')
    fields: dict = {}
    # Exclude prompt because this function runs before handlers resolve template
    # placeholders. Front-ends receive the resolved prompt through these events:
    #   scramda2       action.output, kind 'prompt' (from its handler)
    #   humanDecision  input.request (io.prompt), or, under --auto, the
    #                  action.output of the scramda2 it really dispatches
    # Including it here would duplicate the humanDecision question.
    if t == 'scramda2':
        fields['model'] = action.get('modelProfile') or action.get('model') or ''
    if t in ('workflow', 'loop'):
        fields['file'] = action.get('file', '')
    if t == 'loop':
        fields['iterations'] = action.get('iterations', 10)
    if t == 'shell':
        fields['command'] = action.get('command', '')
    if t == 'writeFile':
        fields['file'] = action.get('file', '')
        fields['content'] = action.get('content', '')
    if action.get('includedData'):
        fields['included'] = action.get('includedData')
    return fields


def _fields_line(fields: dict) -> str:
    """Format _action_fields as a one-line log entry."""
    parts = []
    for key, value in fields.items():
        if key == 'included':
            parts.append(f'included=[{", ".join(value)}]')
        elif key == 'iterations':
            parts.append(f'iterations={value}')
        else:
            s = str(value)
            parts.append(f'{key}="{s[:80]}"' + ('...' if len(s) > 80 else ''))
    return '  '.join(parts)


def _data_preview(value) -> str:
    s = str(value) if value is not None else 'None'
    preview = s[:120].replace('\n', ' ')
    suffix = '...' if len(s) > 120 else ''
    return f'"{preview}{suffix}"  ({len(s)} chars)'


def _resolve_action_fields(action: dict, previous_data: dict) -> dict:
    """Resolve whole-field overrides from previous action data.

    An exact {"override": "key"} value can resolve to any data type. Handlers
    continue to resolve placeholders within string fields through format_map.
    """
    resolved = dict(action)
    for field, value in action.items():
        if isinstance(value, dict) and list(value.keys()) == ['override']:
            ref_key = value['override']
            if ref_key in previous_data:
                resolved[field] = previous_data[ref_key]
            else:
                logger.warn(f'override key "{ref_key}" not found in context')
    return resolved


def _gate_value(action: dict, step_output: dict, field: str):
    """Return the context value named by a gate field.

    Gates read `step_output` because `includedData` filters action input, not
    control flow. Requiring a gate key in `includedData` could also expose that
    value to a prompt unnecessarily. `continueKey` follows the same rule.
    """
    key = action.get(field)
    if not key:
        return None, ''
    key = str(key)
    if key not in step_output:
        # A missing key usually indicates a typo or renamed action ID. Warn
        # before treating it as false so the resulting skip is visible.
        logger.warn(f'"{field}": "{key}" on action "{action.get("id", "")}" '
                    f'names a key no action has produced — reading it as no')
    return key, step_output.get(key)


def should_run(action: dict, step_output: dict) -> tuple[bool, str, str]:
    """Return whether gate fields allow the action to run and why.

    `"when": "files_written"` runs the action only if the run has produced a
    `files_written` whose value is truthy according to clay/lib/flags.py.
    `"whenNot"` provides the inverse condition for the other branch. When both
    fields are present, both conditions must hold. An action without either
    field runs normally.

    The key and value let the caller explain why an action was skipped.
    """
    key, value = _gate_value(action, step_output, 'when')
    if key and not is_truthy(value):
        return False, key, '' if value is None else str(value)

    not_key, not_value = _gate_value(action, step_output, 'whenNot')
    if not_key and is_truthy(not_value):
        return False, f'not {not_key}', '' if not_value is None else str(not_value)

    return True, '', ''


def dispatch(action: dict, step_output: dict, *, auto: bool = False,
             auto_context=None, daemon: bool = False):
    """Validate one action, route it to its handler, and emit its lifecycle.

    Returns the handler's result dict ({"id", "data", ...}) or None when the
    action intentionally stores nothing. Invalid schemas and unknown action
    types raise WorkflowFailure; successful output keeps its existing shape.
    """
    # Store unattended state centrally because several handlers use it. This
    # avoids adding the same argument to each handler signature.
    approval.set_unattended(daemon)

    log = logger.get()
    action = _resolve_action_fields(action, step_output)
    action_type = action.get('type')
    action_id = action.get('id', '')

    errors = _validate(action)
    if errors:
        for e in errors:
            logger.emit(events.ACTION_ERROR, id=action_id,
                        action_type=action_type, message=e)
        if log:
            log.log('!! SCHEMA  ' + '; '.join(errors))
        raise WorkflowFailure(
            f'Action "{action_id}" ({action_type}) is invalid: '
            + '; '.join(errors)
        )

    # "visible": false hides lifecycle events and payloads from front-ends.
    # Errors remain visible, and the log file records every event.
    #
    # humanDecision questions remain visible because io.py emits input.request
    # independently. Hiding a question would prevent the user from answering.
    show = logger.visible(action)

    # Evaluate gates after validation but before lifecycle events. Validation
    # must expose invalid gated actions even when their gate is closed. A skipped
    # action must not start a renderer indicator or retain a previous result.
    run, when_key, when_value = should_run(action, step_output)
    if not run:
        # Remove results from earlier loop iterations. Later gates must not read
        # a stale value for an action that did not run in the current iteration.
        step_output.pop(action_id, None)
        logger.emit(events.ACTION_SKIPPED, id=action_id,
                    action_type=action_type, key=when_key,
                    value=when_value[:120], show=show)
        if log:
            log.log(f'SKIP    {action_type}  "{action_id}"  '
                    f'when "{when_key}" = {_data_preview(when_value)}')
        return None

    fields = _action_fields(action)
    logger.emit(events.ACTION_START, id=action_id, action_type=action_type,
                show=show, **fields)

    if log:
        log.log(f'ACTION  {action_type}  "{action_id}"  {_fields_line(fields)}')

    ctx = build_ctx(step_output, action)
    # Child workflows inherit engine infrastructure even when includedData
    # filters user variables. Their actions still select ordinary input normally.
    engine_globals = {
        key: step_output[key]
        for key in PASSTHROUGH_KEYS
        if key in step_output
    }

    started = time.monotonic()
    # Busy state applies to visible and hidden actions. The finally block clears
    # it even when a handler raises.
    busy = action_type not in _NO_BUSY_TYPES
    if busy:
        logger.busy(True, action_type)
    try:
        if action_type == 'humanDecision':
            result = _handler_for_type('humanDecision')(action, ctx, auto=auto, auto_context=auto_context)
        elif action_type == 'workflow':
            result = _handler_for_type('workflow')(
                action, ctx, auto=auto, auto_context=auto_context,
                engine_globals=engine_globals)
        elif action_type == 'loop':
            result = _handler_for_type('loop')(
                action, ctx, auto=auto, auto_context=auto_context,
                engine_globals=engine_globals)
        elif action_type == 'humanShell':
            result = _handler_for_type('humanShell')(action, ctx, auto=auto, daemon=daemon)
        else:
            handler = _handler_for_type(action_type)
            if handler is None:
                if log:
                    log.log(f'  !! UNKNOWN ACTION TYPE: {action_type}')
                raise WorkflowFailure(f'Unknown action type: {action_type}')
            result = handler(action, ctx)
    except Exception as exc:
        # Emit an error so renderers can clear indicators after a handler fails.
        logger.emit(events.ACTION_ERROR, id=action_id,
                    action_type=action_type, message=str(exc))
        raise
    finally:
        # This also covers the unknown action type raised inside the try block.
        if busy:
            logger.busy(False)

    logger.emit(events.ACTION_DONE,
                id=(result or {}).get('id', action_id),
                action_type=action_type,
                data=(result or {}).get('data'),
                duration_ms=int((time.monotonic() - started) * 1000),
                show=show)

    # Record a result preview in the log file only.
    if log and result and action_type not in _SILENT_RESULT_TYPES:
        data = result.get('data')
        if data is not None:
            s = str(data).strip()
            if s:
                log.log(f'  → stored "{result.get("id")}"  {_data_preview(data)}')

    return result
