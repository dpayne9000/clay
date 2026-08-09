"""Concise renderer — the terminal with the plumbing taken out.

The default for `clay run`. TerminalRenderer, its parent, is what `-v` gives
you and is unchanged: the full stream, every action announced, every prompt
echoed. This subclass draws the same run for someone having a conversation
with a workflow rather than reading one.

WHAT THIS DOES NOT CHANGE
-------------------------
`"visible": false` means exactly what it meant before, and it is still decided
at the source (clay/run/logger.py). A hidden action is hidden in both modes; a
visible one is shown in both. This class never looks at that flag — it cannot,
because a hidden action's events never reach a renderer at all. What changes
here is how much scaffolding is drawn around the events that do arrive, and
how a payload is drawn once it has.

Manual approval is likewise untouched. An approval question is printed by
approval.confirm() through io.get().prompt() (clay/run/approval.py:336), the
same path a humanDecision takes, and no renderer draws either — which is why
a mode that draws almost nothing still asks every question it should.

WHAT IT DROPS
-------------
    step headers            _on_step_start
    ▸ action → id lines     _on_action_start
    skipped-action lines    _on_action_skipped
    outgoing model prompts  _on_action_output, kind 'prompt'
    INFO log lines          _on_log

Those five are the run explaining itself: which action is running, what was
sent to the model, which gate closed. Useful when something has gone wrong,
which is what `-v` is for, and noise when you are waiting for an answer. None
of it is lost — logger writes every event to the run log before any renderer
sees it, so the file under logs/ is identical in both modes.

WHAT IT KEEPS, AND DRAWS BETTER
-------------------------------
Model answers, warnings, errors and the spinner come through the parent
untouched. The four payload kinds a turn *did* something with are redrawn:

    file   ✎ greet.py written (3 lines)
    diff   ✎ utils/text.py updated (+4 −1), then the diff itself
    read   ▪ utils/text.py read
    command  the command, then its output indented

An unrecognised kind falls through to the parent's drawing rather than being
swallowed. A payload nobody has taught this class about is still something an
action wanted shown, and silently dropping it is the failure mode this file
would otherwise have every time a new action type is added.
"""

from .. import termui
from .terminal import TerminalRenderer


class ConciseRenderer(TerminalRenderer):
    """The default terminal renderer: content, not commentary."""

    #: Payload kinds this class draws itself. Anything else is the parent's.
    OWN_KINDS = frozenset({'file', 'diff', 'read', 'command'})

    # ── drawn by the parent, silenced here ───────────────────────────────

    def _on_step_start(self, event: dict) -> None:
        return

    def _on_action_start(self, event: dict) -> None:
        return

    def _on_action_skipped(self, event: dict) -> None:
        """Nothing. A closed gate is a fact about the workflow, not the answer.

        The parent draws it, and its reasoning holds there: a run where three
        actions are simply absent is unreadable. Reading a run is what `-v` is
        for. In a conversation the skipped half of a branch is the machinery
        working correctly, and saying so every turn is the noise this mode
        exists to remove.
        """
        return

    def _on_log(self, event: dict) -> None:
        """WARN and ERROR only.

        An INFO line is a workflow narrating itself — which files it read, how
        many entries a namespace holds. The parent prints all three levels.
        Warnings and errors are never silenced by any mode: something a person
        has to know about is not chatter, and a quiet failure is worse than a
        noisy run.
        """
        level = (event.get('level') or '').upper()
        if level not in ('WARN', 'ERROR'):
            return
        super()._on_log(event)

    # ── drawn differently ────────────────────────────────────────────────

    def _on_action_output(self, event: dict) -> None:
        kind = event.get('kind', '')

        if kind == 'prompt':
            # The single largest thing on the screen in verbose mode, and the
            # one least meant for a person: it is the assembled instructions,
            # not the answer. It stays in the run log in full.
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
            # Label only. A created file's body was in the answer printed
            # moments ago, and writeMemory and writeSkill quote back something
            # the turn already said.
            termui.file_write(label)
        elif kind == 'read':
            termui.file_read(label)
        else:
            termui.shell_run(label, text)
