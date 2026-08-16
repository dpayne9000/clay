"""Define the shared engine event vocabulary.

Emitters and front-ends share these constants. A misspelled event name would
silently fail to match, so modules must not redefine the strings.

Payloads carry structured data. Front-ends control formatting, truncation, and
color.

    run.start        label, auto, log_path
    run.complete     label, log_path
    run.cancelled    —
    run.error        message, + label/log_path for a failed root execution
    step.start       step
    action.start     id, action_type, + identifying fields (model, file, …)
    action.complete  id, action_type, data, duration_ms
    action.error     id, action_type, message
    action.output    id, action_type, kind, label, text
    action.skipped   id, action_type, key, value
    loop.iteration   iteration, max, file
    busy             active, action_type, preview
    log              level, message
    input.request    id, prompt      (io.SocketIO for clayd-managed UI runs)
    input.response   id, text        (sent by clayd send_input; read by io._handle_line)

`action.output` contains user-facing action data such as resolved prompts, file
content, and command output. Its action type, ID, and payload kind let a
front-end filter structured fields. A `log` event contains only a level and
message.

`kind` is a stable token, not display text: 'prompt', 'file', 'command',
'read'. `label` is the one-line header ('greet.py written (3 lines)',
'$ python3 greet.py'); `text` is the body, and may be empty.

`"visible": false` suppresses action lifecycle and output events from
front-ends but not from the log. Errors always remain visible. See
logger.visible().

Visibility does not suppress `busy` events because hidden actions still need a
working indicator. `active` holds the indicator state, `action_type` identifies
the operation, and `preview` contains a bounded one-line prompt. Busy events
are transient UI state and do not enter the log. See logger.busy().

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

# option.set carries cross-process setting changes over the existing clayd
# socket. It remains distinct from input.response because it does not answer a
# prompt.
OPTION_SET     = 'option.set'

# Rendering modules decide which events to display. Keep visibility policies
# out of this vocabulary so terminal and chat behavior cannot diverge silently.
