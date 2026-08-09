"""Action dispatch — validates one action and routes it to its handler.

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

# Types that handle their own output (human prompts, loops) — don't log result preview
_SILENT_RESULT_TYPES = frozenset({'humanDecision', 'humanShell', 'loop', 'workflow'})

# Types that raise no busy indicator. The same four names as above, and
# deliberately a second set rather than a reuse — the reason is different and
# either list can change without the other.
#
# 'workflow' and 'loop' are containers: the work is the actions inside, each of
# which brackets itself, and the first inner active=False would drop an outer
# indicator that nothing then brings back. 'humanDecision' and 'humanShell'
# hand the floor to a person straight away.
#
# The last two are belt and braces. The real guard is io._floor_to_human(),
# because under manual approval an ordinary action blocks on a question too.
_NO_BUSY_TYPES = frozenset({'workflow', 'loop', 'humanDecision', 'humanShell'})


def _action_fields(action: dict) -> dict:
    """Identifying fields a front-end may want to show for this action.

    Data, not a formatted string — a Qt panel wanting the model name should
    read a key, not parse prose. Truncation and layout are the renderer's.
    """
    t = action.get('type', '')
    fields: dict = {}
    # No prompt field, for any action type. This runs before the handler, so
    # action['prompt'] is always the raw template with its {placeholders}
    # unsubstituted — it was never the text anyone was actually shown or sent.
    # The resolved text reaches front-ends on its own event instead:
    #   scramda2       action.output, kind 'prompt' (from its handler)
    #   humanDecision  input.request (io.prompt), or, under --auto, the
    #                  action.output of the scramda2 it really dispatches
    # Both humanDecision paths already carry it, so a third copy here would
    # have put the same question on screen twice.
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
    """One-line summary of _action_fields for the log file — not a front-end."""
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
    """
    Resolve action fields whose entire value is {"override": "key"} to the
    corresponding previous_data value of any type.
    String fields with {placeholder} interpolation are left for each handler
    to resolve via format_map as before.
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
    """The value a gate field names, or None if the field is absent.

    Read from `step_output`, not from the built ctx: ctx is filtered by
    `includedData`, and a gate is not data the action consumes — requiring the
    key in `includedData` would mean pouring a value into a prompt purely to
    be allowed to test it. `continueKey` reads the raw accumulated output for
    the same reason.
    """
    key = action.get(field)
    if not key:
        return None, ''
    key = str(key)
    if key not in step_output:
        # Not the same as a key that exists and says no. Nothing has ever
        # stored under this name, which in a hand-written workflow is a typo
        # or an action id that was renamed — and the consequence is an action
        # that silently never runs, or always runs. Saying so is what stops it
        # being silent.
        logger.warn(f'"{field}": "{key}" on action "{action.get("id", "")}" '
                    f'names a key no action has produced — reading it as no')
    return key, step_output.get(key)


def should_run(action: dict, step_output: dict) -> tuple[bool, str, str]:
    """Whether the gate fields let this action run, and what decided.

    `"when": "files_written"` runs the action only if the run has produced a
    `files_written` whose value means yes (clay/lib/flags.py — the same
    vocabulary `loop`'s continueKey has always used, so a model answering NO
    reads as no here too). `"whenNot"` is its mirror, and exists because the
    two halves of a branch are both real work: one action handles the case the
    gate opens on, another handles the case it does not, and without the
    negation the second half has nothing to hang on. Both together mean both
    must hold. Neither field means run, which is every action written before
    this existed.

    Returns (run, key, value) so the caller can say *why* an action did not
    happen rather than leaving a hole in the run.
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
    # Recorded rather than threaded: applyFileWrites, serveFileReads and
    # runReplyCommands all need to know whether a human is reachable, and three
    # more handler signatures carrying the same flag is how the special-case
    # ladder below grows. The same fact humanShell reads from its `daemon`
    # argument, kept where the approval gate can reach it.
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

    # "visible": false — the action draws nothing at all: no start line, no
    # done line, no payload (logger.output reads the same flag). Errors are
    # never gated: an action you chose not to watch is still one you have to
    # be told about when it fails. The log file keeps every event either way.
    #
    # A humanDecision's question is unaffected too — it travels as
    # input.request through clay/run/io.py, not through this emit — because a
    # hidden question is one nobody can answer.
    show = logger.visible(action)

    # "when": "key" — the gate goes here, after validation and before any
    # lifecycle event: a skipped action must not emit a start line a renderer
    # would hold a spinner open on, and must not store a result, or a later
    # `when` reading its id would see the leftovers of the turn before.
    # Validating first is deliberate — a typo in a gated action is still a
    # typo, and finding it only on the turn the gate happens to open is how a
    # workflow breaks in front of a user weeks later.
    run, when_key, when_value = should_run(action, step_output)
    if not run:
        # Drop whatever this id held. Inside a loop the same actions run again
        # each iteration, so an action skipped on pass 2 would otherwise leave
        # pass 1's answer standing — and a later `when` reading that id would
        # gate on a result from a turn that no longer exists. An action that
        # did not run has no result, and that is what the store should say.
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
    # Engine-seeded globals are run infrastructure, not ordinary action input.
    # A workflow/loop must inherit them even when its includedData deliberately
    # filters user variables; actions inside the child still opt in normally.
    engine_globals = {
        key: step_output[key]
        for key in PASSTHROUGH_KEYS
        if key in step_output
    }

    started = time.monotonic()
    # Raised for every action, hidden or not. A "visible": false action emits
    # nothing else a front-end can see, and Telegram and the Qt panel had no
    # indicator even for visible model calls. Dropped in finally, so a handler
    # that raises does not leave three front-ends claiming to be working.
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
        # The renderer holds a spinner open between action.start and
        # action.complete. Without this the terminal is left spinning on a
        # handler crash.
        logger.emit(events.ACTION_ERROR, id=action_id,
                    action_type=action_type, message=str(exc))
        raise
    finally:
        # Also covers the unknown-type branch above, which returns from inside
        # the try.
        if busy:
            logger.busy(False)

    logger.emit(events.ACTION_DONE,
                id=(result or {}).get('id', action_id),
                action_type=action_type,
                data=(result or {}).get('data'),
                duration_ms=int((time.monotonic() - started) * 1000),
                show=show)

    # Log result preview (log file only)
    if log and result and action_type not in _SILENT_RESULT_TYPES:
        data = result.get('data')
        if data is not None:
            s = str(data).strip()
            if s:
                log.log(f'  → stored "{result.get("id")}"  {_data_preview(data)}')

    return result
