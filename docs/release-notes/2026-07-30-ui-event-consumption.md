# 2026-07-30 — the graph UI reads the real event vocabulary, and can be answered

Companion to `2026-07-30-chat-renderer-parity.md`. That release gave every
front-end `action.output`; checking that the Qt window actually drew it turned
up a panel that had been reading a vocabulary the engine stopped emitting.

## Fixed — `LogPanel` was matching event names that do not exist

`clay/ui/panels.py` matched on string literals rather than `clay.run.events`,
and the literals had drifted:

| branch | was | consequence |
|---|---|---|
| `action.start` | printed `event['type']` | every line read `▸ action.start → myid` — never the action's type |
| `action.error` | read `event['error']` | events carry `message`; the error line was always blank |
| `workflow.start` / `workflow.complete` | not in the vocabulary | the events are `run.start` / `run.complete`; neither branch had ever fired |
| `log` | absent | no `logger.info`, `warn` or `error` had ever reached this panel |
| `run.cancelled`, `run.error` | absent | a run that failed or was stopped said nothing |

Every branch now names its event through `events.*`. This is exactly the
failure mode the module docstring in `clay/run/events.py` warns about — a
misspelled event does not raise, its branch just never matches and the output
silently disappears — so the fix is not "correct the strings", it is "stop
retyping them".

`clay/ui/window.py` had the same defect: it animated graph nodes on
`step.complete`, which the engine does not emit, so a step went `active` and
stayed that way for the rest of the run. A step is now finished when the next
one starts, or when the run ends — `done`, `error` or back to `idle` according
to how it ended. The `action.start` / `action.complete` branches, previously
`pass`, now colour the action node via `scene.action_node_by_id`.

## Fixed — a workflow run from `clay ui` could not be answered

`WorkflowRunner` runs the engine on a worker thread and attached no input
channel, so `io.get()` returned `TerminalIO` and a `humanDecision` called
`builtins.input()`. That reads the terminal the app was launched from, or
raises `EOFError` when there is no tty. Either way it is not the window the
person is looking at, and a workflow containing a human step could not be run
from the editor at all.

The daemon path never had this problem — `clayd` turns `input.request` into a
`prompt` event and `ProcessDashboard` and `WorkflowManager` both already have
the widget and the `send_input` round-trip. It was only the in-process run that
had nowhere to type.

### Added — `io.QueueIO`, the third input channel

```
plain `clay run` in a terminal        → TerminalIO  (builtins.input)
clayd-managed run (--events-socket)   → SocketIO    (JSON lines)
in-process run inside `clay ui`       → QueueIO     (thread to thread)
```

Same contract as `SocketIO`: `prompt()` blocks and raises `ChannelClosed` if
the channel closes underneath it, `deliver()` hands over the answer, `close()`
releases the waiter. There is no socket because there is no second process.

The question goes out on the **event bus**, as `input.request`, rather than
down a private signal to the widget. It therefore reaches every listener the
run already has — the log file included — and `LogPanel` handles it in the same
switch as every other event.

It lives in `clay/run/io.py`, not in the UI package: it holds no Qt, it is a
channel rather than a widget, and putting it beside the other two channels is
what makes it testable without PySide6.

`io.attach(channel)` is the general form of `attach_socket`, which is now one
line on top of it.

### Added — the prompt row on `LogPanel`

Hidden until an `input.request` arrives, then the question is printed, the row
appears and takes focus, and Return or **Send** answers it. Submitting emits
`input_submitted(prompt_id, text)`, which `WorkflowWindow` forwards to
`WorkflowRunner.send_input`.

An empty answer is sent, not swallowed — `humanDecision` reads a blank line as
"take the default", so the guard is on a prompt being outstanding, not on the
text being non-empty.

The row is withdrawn when the run ends, is cancelled, or errors. A question on
screen with no run behind it can only be answered into nothing.

### Stop now works during a human step

`WorkflowRunner.cancel()` closes the channel as well as requesting
cancellation. Cooperative cancellation unwinds at the next action boundary, and
a run parked in `humanDecision` has no next action — Stop did nothing until
somebody answered the question they were trying to abandon.

## Tests

`clay/tests/run/test_io_roundtrip.py` gained `QueueRoundTripTest`: the question
goes out on the bus, an empty answer is an answer, an answer with no question
is refused, `close()` releases a waiting prompt (what Stop depends on), and a
second question while one is outstanding raises.

## Verification

Not yet run:

```
.venv/bin/python -m clay.tests
```
