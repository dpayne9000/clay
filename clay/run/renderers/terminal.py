"""Render engine events on a local terminal.

The engine emits events instead of printing. The CLI attaches this renderer
once at startup for the lifetime of the process.

clayd-managed runs send events to their front-end through the socket bridge and
do not attach this renderer.

This renderer does not draw input questions. TerminalIO.prompt() prints each
question immediately before reading its answer, so rendering it here would
duplicate it.

logger._notify calls listeners synchronously, and dispatch is sequential.
Spinner operations therefore require no additional synchronization.
"""

from .. import events, logger, termui
from .detail import (action_detail, busy_label, payload_lines, prompt_body,
                     skipped_reason)


class TerminalRenderer:
    """Subscribe to engine events and render them on stdout."""

    #: Maximum spinner label length. Longer labels may wrap and leave previous
    #: animation frames visible.
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
        # Actions inside a loop provide sufficient progress information, so
        # loop.iteration has no terminal representation.

    # Separate methods let subclasses suppress or replace individual formats
    # while handle() remains the single event dispatch table.

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
        """Render one line for an action closed by a gate.

        Detailed output identifies skipped actions and the values that closed
        their gates.
        """
        self._stop_spinner()
        print(f'  skipped {event.get("id", "")} ({skipped_reason(event)})')

    def _on_action_output(self, event: dict) -> None:
        self._stop_spinner()
        kind = event.get('kind', '')
        label = event.get('label', '')
        text = event.get('text', '')

        if kind == 'prompt':
            # logger.output emits busy state after this prompt event, so this
            # branch only draws the box. Apply the shared display limit here.
            termui.scramda_input(prompt_body(text), model=label)
            return

        # Render other payloads with an indented header and body.
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
            # Indent every line of a multiline informational message.
            for line in str(message).split('\n'):
                print(f'  {line}')

    # ── spinner ──────────────────────────────────────────────────────────

    def _on_busy(self, event: dict) -> None:
        """Start, relabel, or stop the spinner.

        Repeated active=True events replace the label without nesting spinners.
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
        """Stop the spinner safely before another operation writes output."""
        if self._spinner is not None:
            self._spinner.stop()
            self._spinner = None
