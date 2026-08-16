"""Render workflow results with minimal diagnostic output.

This is the default renderer for `clay run`; `-v` selects TerminalRenderer.
Both receive the same events, but this class suppresses diagnostic narration.

WHAT THIS DOES NOT CHANGE
-------------------------
clay/run/logger.py applies `"visible": false` before events reach either
renderer. This class changes only how visible events are presented.

Approval and humanDecision questions use io.get().prompt() and bypass event
renderers, so concise mode does not suppress them.

WHAT IT DROPS
-------------
    step headers            _on_step_start
    ▸ action → id lines     _on_action_start
    skipped-action lines    _on_action_skipped
    outgoing model prompts  _on_action_output, kind 'prompt'
    INFO log lines          _on_log

These events remain available with `-v` and in the run log. Concise mode omits
them only from the current terminal display.

WHAT IT KEEPS, AND DRAWS BETTER
-------------------------------
The parent still renders model answers, warnings, errors, and busy state. This
class provides compact formats for four payload kinds:

    file   ✎ greet.py written (3 lines)
    diff   ✎ utils/text.py updated (+4 −1), then the diff itself
    read   ▪ utils/text.py read
    command  the command, then its output indented

Unknown payload kinds use the parent renderer so new event types remain visible.
"""

from .. import termui
from .terminal import TerminalRenderer


class ConciseRenderer(TerminalRenderer):
    """Render workflow results while suppressing diagnostic narration."""

    #: Payload kinds this class draws itself. Anything else is the parent's.
    OWN_KINDS = frozenset({'file', 'diff', 'read', 'command'})

    # ── drawn by the parent, silenced here ───────────────────────────────

    def _on_step_start(self, event: dict) -> None:
        return

    def _on_action_start(self, event: dict) -> None:
        return

    def _on_action_skipped(self, event: dict) -> None:
        """Suppress skipped-action diagnostics in concise mode.

        The detailed renderer and run log retain the skip reason.
        """
        return

    def _on_log(self, event: dict) -> None:
        """Render warnings and errors while suppressing informational logs.

        Warnings and errors remain visible in every display mode.
        """
        level = (event.get('level') or '').upper()
        if level not in ('WARN', 'ERROR'):
            return
        super()._on_log(event)

    # ── drawn differently ────────────────────────────────────────────────

    def _on_action_output(self, event: dict) -> None:
        kind = event.get('kind', '')

        if kind == 'prompt':
            # Outgoing prompts remain available in verbose mode and the run log.
            return

        if kind not in self.OWN_KINDS:
            super()._on_action_output(event)
            return

        self._stop_spinner()
        label = event.get('label', '')
        text = event.get('text', '')

        if kind == 'diff':
            termui.file_write(label, text)
        elif kind == 'file':
            # Show only the label because the preceding result already contains
            # the created content.
            termui.file_write(label)
        elif kind == 'read':
            termui.file_read(label)
        else:
            termui.shell_run(label, text)
