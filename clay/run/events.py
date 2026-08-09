"""The engine event vocabulary.

One definition shared by every emitter and every front-end. A consumer that
misspells an event name does not raise — its branch just never matches and the
output silently disappears — so the names must not be retyped per module.

Payloads carry data, never formatted text. Rendering, truncation and colour are
the front-end's business.

    run.start        label, auto, log_path
    run.complete     label, log_path
    run.cancelled    —
    run.error        message, + label/log_path for a failed root execution
    step.start       step
    action.start     id, action_type, + identifying fields (prompt, model, …)
    action.complete  id, action_type, data, duration_ms
    action.error     id, action_type, message
    action.output    id, action_type, kind, label, text
    action.skipped   id, action_type, key, value
    loop.iteration   iteration, max, file
    busy             active, action_type, preview
    log              level, message
    input.request    id, prompt      (io.SocketIO for clayd-managed UI runs)
    input.response   id, text        (sent by clayd send_input; read by io._handle_line)

`action.output` is what an action has to *show a person*: the resolved prompt
going to a model, the contents of a file just written, the output of a command.
It carries its own provenance — which action, which id, which kind of payload —
so a front-end can decide per action what it draws. A `log` event cannot: it is
a level and a string, and three handlers emitting through logger.info produced
events no consumer could tell apart.

`kind` is a stable token, not display text: 'prompt', 'file', 'command',
'read'. `label` is the one-line header ('greet.py written (3 lines)',
'$ python3 greet.py'); `text` is the body, and may be empty.

An action carrying `"visible": false` emits none of these to a front-end —
not action.start, not action.complete, not action.output. The log file still
records all of them (logger.emit's `show` parameter), and action.error is
never gated: an action you chose not to watch is still one you have to be
told about when it fails. See logger.visible().

`busy` is the other thing `"visible": false` does not gate, and it exists
because of it. A hidden action used to emit nothing at all between its start
and its finish, so every front-end sat silent for however long it took — and
Telegram and the Qt panel sat silent for *visible* model calls too, having no
indicator of any kind. It carries no id and nothing an action did: `active` is
a level a front-end holds an indicator on, `action_type` says what is being
waited for, and `preview` is up to logger.BUSY_PREVIEW_MAX_CHARS of the
resolved prompt on one line. It is the only event that never reaches the log
file — a spinner is not a thing that happened. See logger.busy().

An action carrying `"when": "some_key"` runs only if that key's value in the
run's accumulated output means yes (clay/lib/flags.py). When it does not, the
action emits `action.skipped` instead of its whole lifecycle — no start, no
complete, no output — and stores nothing. The event names the key and the
value that decided it, because an action that quietly does not happen is the
hardest kind of run to read. `"whenNot"` is the mirror, for the other half of
a branch. `"visible": false` silences the skip line like any other event.
"""

RUN_START      = 'run.start'
RUN_COMPLETE   = 'run.complete'
RUN_CANCELLED  = 'run.cancelled'
RUN_ERROR      = 'run.error'
STEP_START     = 'step.start'
ACTION_START   = 'action.start'
ACTION_DONE    = 'action.complete'
ACTION_ERROR   = 'action.error'
ACTION_OUTPUT  = 'action.output'
ACTION_SKIPPED = 'action.skipped'
LOOP_ITERATION = 'loop.iteration'
BUSY           = 'busy'
LOG            = 'log'
INPUT_REQUEST  = 'input.request'
INPUT_RESPONSE = 'input.response'

# A front-end changing a setting on a *running* workflow. It travels the same
# socket as input.response because it answers the same problem: the front-end
# and the workflow are separate processes, and clayd is already the one relay
# between them. It is not an answer to a question, which is why it is not an
# input.response with a magic body.
OPTION_SET     = 'option.set'

# There is deliberately no "events a chat front-end relays" subset here. A set
# like that decides what a user sees, which is a rendering decision, and having
# it in the vocabulary is what let the Telegram front-end quietly show less
# than the CLI. What each front-end draws now lives with the front-end:
# clay/run/renderers/terminal.py and clay/run/renderers/chat.py.
