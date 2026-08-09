"""Terminal renderer — draws engine events on a local terminal.

The engine does not print. It emits, and each front-end draws what it
receives; this is the front-end for the CLI. Attach it once at startup and it
renders for the whole process.

It is deliberately not attached for a clayd-managed run: nobody is watching
that process's terminal, and the same events already reach the real front-end
over the socket bridge.

One rule, and the rest follows from it: this renderer never draws prompt text.
TerminalIO.prompt() (clay/run/io.py:40) prints the question itself, because it
must print and then immediately read the answer on the same call. Drawing it
here too would show every question twice.

Thread safety: none, and none needed. logger._notify calls listeners
synchronously on the emitting thread and dispatch is sequential, so the
spinner is only ever touched by one thread at a time.
"""

from .. import events, logger, termui
from .detail import (action_detail, busy_label, payload_lines, prompt_body,
                     skipped_reason)


class TerminalRenderer:
    """Subscribes to the engine event bus and draws to stdout."""

    #: Spinner labels are cut to this. termui.Spinner redraws its line with
    #: '\r', which only returns to the start of the *physical* line, so a label
    #: long enough to wrap the terminal leaves every previous frame on screen.
    BUSY_LABEL_MAX = 56

    def __init__(self) -> None:
        self._spinner = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def attach(self) -> None:
        logger.add_listener(self.handle)

    def detach(self) -> None:
        logger.remove_listener(self.handle)
        self._stop_spinner()

    # ── rendering ────────────────────────────────────────────────────────

    def handle(self, event: dict) -> None:
        kind = event.get('type', '')

        if kind == events.RUN_START:
            self._on_run_start(event)
        elif kind == events.RUN_COMPLETE:
            self._on_run_complete(event)
        elif kind == events.RUN_CANCELLED:
            self._stop_spinner()
            termui.error('Run stopped by user')
        elif kind == events.RUN_ERROR:
            self._stop_spinner()
            termui.error(event.get('message', ''))
        elif kind == events.STEP_START:
            self._on_step_start(event)
        elif kind == events.ACTION_START:
            self._on_action_start(event)
        elif kind == events.ACTION_DONE:
            self._on_action_done(event)
        elif kind == events.ACTION_ERROR:
            self._stop_spinner()
            termui.error(event.get('message', ''))
        elif kind == events.ACTION_OUTPUT:
            self._on_action_output(event)
        elif kind == events.ACTION_SKIPPED:
            self._on_action_skipped(event)
        elif kind == events.BUSY:
            self._on_busy(event)
        elif kind == events.LOG:
            self._on_log(event)
        # loop.iteration draws nothing — the actions inside it announce
        # themselves, and a counter line per iteration is noise.

    # Each event gets a method of its own, including the one-liners, so a
    # renderer that wants a quieter terminal can subclass this and return from
    # the ones it does not draw. handle() is then the single description of the
    # vocabulary, and a new event type is added to it once rather than to every
    # subclass — the reason detail.py exists, applied to dispatch instead of to
    # formatting. See concise.py.

    def _on_run_start(self, event: dict) -> None:
        termui.startup_banner(event.get('label', ''), event.get('auto', False),
                              event.get('log_path', ''))

    def _on_run_complete(self, event: dict) -> None:
        termui.completion_banner(event.get('log_path', ''))

    def _on_step_start(self, event: dict) -> None:
        termui.step_header(event.get('step', ''))

    def _on_action_start(self, event: dict) -> None:
        termui.action_line(event.get('action_type', ''), event.get('id', ''),
                           action_detail(event))

    def _on_action_skipped(self, event: dict) -> None:
        """One line for an action a `when` gate closed.

        Drawn, not swallowed. A gated workflow's whole point is that some turns
        do less than others, and a run where three actions simply are not there
        is unreadable unless it says which ones and what decided.
        """
        self._stop_spinner()
        print(f'  skipped {event.get("id", "")} ({skipped_reason(event)})')

    def _on_action_output(self, event: dict) -> None:
        self._stop_spinner()
        kind = event.get('kind', '')
        label = event.get('label', '')
        text = event.get('text', '')

        if kind == 'prompt':
            # Draws the box only. The spinner is not started here any more:
            # logger.output emits a busy carrying this same resolved text
            # immediately after this event, and one spinner with two sources is
            # how the two drift. It still spans exactly the model call — that
            # busy is emitted right before gopher.fire — and it now also spans
            # the call when the action is "visible": false and this branch
            # never runs at all.
            # Cut here, not in termui: engine.py formats what it is handed and
            # holds no opinion on length, and cutting in the renderer is what
            # lets the terminal and the chat share one number from config.json.
            termui.scramda_input(prompt_body(text), model=label)
            return

        # Everything else keeps the shape a logger.info message had here — the
        # header and every line of the body in the indented column.
        print(payload_lines(event))

    def _on_action_done(self, event: dict) -> None:
        self._stop_spinner()
        if event.get('action_type') == 'scramda2':
            termui.scramda_output(event.get('data') or '')

    def _on_log(self, event: dict) -> None:
        self._stop_spinner()
        level = (event.get('level') or '').upper()
        message = event.get('message', '')
        if level == 'ERROR':
            termui.error(message)
        elif level == 'WARN':
            termui.warn(message)
        else:
            # Indent every line, not just the first: a file echo and a
            # command's output arrive as one multi-line message, and only the
            # head of it would otherwise sit in the indented column.
            for line in str(message).split('\n'):
                print(f'  {line}')

    # ── spinner ──────────────────────────────────────────────────────────

    def _on_busy(self, event: dict) -> None:
        """Raise, relabel or drop the spinner.

        `active` is a level, so a second active=True is a relabel — which is
        exactly what arrives when a prompt resolves and the generic action type
        can be replaced by the text being waited for.
        """
        if event.get('active'):
            self._start_spinner(busy_label(event, self.BUSY_LABEL_MAX))
        else:
            self._stop_spinner()

    def _start_spinner(self, label: str = 'processing') -> None:
        self._stop_spinner()
        self._spinner = termui.Spinner()
        self._spinner.start(label)

    def _stop_spinner(self) -> None:
        """Idempotent. Anything that prints must call this first — a live
        spinner rewrites the current line and would eat the output."""
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None
