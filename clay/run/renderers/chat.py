"""Render engine events as text for a message thread.

ChatRenderer and TerminalRenderer consume the same event stream and follow the
same visibility policy. This prevents chat clients from silently omitting
events that the terminal displays.

Two deliberate differences from the terminal, both forced by the medium:

  * render() returns text instead of printing. The front-end controls transport,
    destination, and message grouping.

  * It does not render input.request. The front-end's prompt path retains the
    prompt ID for reply routing and displays the question itself.

The front-end owns the event subscription and calls render() for each event.
This class performs formatting without network or daemon dependencies.

CHANGING WHAT A CHAT SEES
-------------------------
This file contains both chat display policies. ChatRenderer is the detailed
formatter; ConciseChatRenderer subclasses it and removes the same diagnostic
categories as a CLI run without -v. The CLI renderers read the same events, so
none of these choices changes execution or the run log.

Return None from a method and that event draws nothing in a detailed chat:

    ── step name            _step()
    ▸ action → id           _action_start()
    a model's answer        _action_done()
    prompt: ...             _output(), kind 'prompt' — the resolved text sent
                            to the model; cut to display.promptMaxChars
    file contents           _output(), kind 'file'    (applyFileWrites,
                            writeMemory, writeSkill, removeSkill)
    command + output        _output(), kind 'command' (runReplyCommands)
    what a read loaded      _output(), kind 'read'    (serveFileReads,
                            readMemory, searchMemory, listMemory,
                            listSkills, searchSkills)
    WARN / ERROR lines      _log()
    error: ...              _error()

The action.output events carry `kind`, `id` and `action_type`, so _output()
is where a per-front-end visibility list goes. To show file writes and
commands but silence prompts and workspace scanning:

    if event.get('kind') in ('prompt', 'read'):
        return None

To show one specific action and nothing else — a curated turn report instead
of the raw stream — filter on the action id in _action_done():

    if event.get('id') != 'turn_report':
        return None

`turn_report` is the digest the coding2 workflow composes in its `settle`
step (workflows/system/coding2/iteration.json). Filtering like that also
silences `turn_summary` and `keep_going`, which are bookkeeping calls whose
answers ("YES") are written for the workflow, not for a person.

The other lever is `"visible": false` on the action in the workflow json,
which silences it for *every* front-end at the source (clay/run/logger.py).
Use that for an action nobody ever needs to watch; use the filters here when
the CLI should keep showing something the chat should not.
"""

from .. import events
from .detail import action_detail, payload_body, prompt_body, skipped_reason


class ChatRenderer:
    """Format engine events as chat lines.

    render() returns text to send or None for events with no chat representation.
    """

    def render(self, event: dict):
        kind = event.get('type', '')

        if kind == events.STEP_START:
            return self._step(event)
        if kind == events.ACTION_START:
            return self._action_start(event)
        if kind == events.ACTION_DONE:
            return self._action_done(event)
        if kind == events.ACTION_OUTPUT:
            return self._output(event)
        if kind == events.ACTION_SKIPPED:
            return self._skipped(event)
        if kind in (events.ACTION_ERROR, events.RUN_ERROR):
            return self._error(event)
        if kind == events.RUN_CANCELLED:
            return 'Run stopped by user'
        if kind == events.LOG:
            return self._log(event)

        # The front-end announces run start and completion. Actions inside loops
        # provide sufficient progress without loop.iteration messages.
        #
        # Front-ends represent busy events as transient transport indicators,
        # such as Telegram typing status, rather than persistent messages.
        return None

    # ── per-event formatting ─────────────────────────────────────────────

    def _step(self, event: dict):
        name = (event.get('step') or '').strip()
        return f'── {name}' if name else None

    def _action_start(self, event: dict):
        action_type = (event.get('action_type') or '').strip()
        action_id = (event.get('id') or '').strip()
        if not action_type and not action_id:
            return None

        line = f'▸ {action_type}' if action_type else '▸'
        if action_id:
            line += f' → {action_id}'

        detail = action_detail(event)
        if detail:
            line += f'\n{detail}'
        return line

    def _skipped(self, event: dict):
        """Render an action skipped by a gate and the deciding value.

        Detailed output distinguishes skipped actions from absent actions.
        """
        action_id = (event.get('id') or '').strip()
        if not action_id and not event.get('key'):
            return None
        return f'▸ skipped {action_id} ({skipped_reason(event)})'

    def _output(self, event: dict):
        """Render a user-facing action payload.

        Use `kind`, `id`, and `action_type` for per-action filtering.
        """
        label = str(event.get('label') or '').strip()
        text = str(event.get('text') or '')

        if event.get('kind') == 'prompt':
            prompt = self._preview(text)
            if not prompt:
                return None
            return f'prompt ({label}):\n{prompt}' if label else f'prompt:\n{prompt}'

        # Use the shared payload limit. Model answers arrive through
        # action.complete and remain complete.
        text = payload_body(event).strip()
        if not label:
            return text or None
        return f'{label}\n{text}' if text else label

    def _action_done(self, event: dict):
        # Only model completion data is conversational content. Other actions
        # use action.output or log events when they have content to display.
        if event.get('action_type') != 'scramda2':
            return None
        text = str(event.get('data') or '').strip()
        return text or None

    def _error(self, event: dict):
        message = str(event.get('message') or '').strip()
        return f'error: {message}' if message else None

    def _log(self, event: dict):
        message = str(event.get('message') or '').strip()
        if not message:
            return None
        level = (event.get('level') or '').upper()
        if level in ('WARN', 'ERROR'):
            return f'{level}: {message}'
        return message

    # ── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _preview(text: str) -> str:
        """The prompt as it will be shown, cut to display.promptMaxChars.

        Line breaks are kept: it is structured text and reads as such.

        Cut by the same shared helper the terminal uses, so a chat and a
        terminal watching one run see the same prompt. A model's *answer* is
        not routed through here — it arrives on action.complete and
        _action_done() returns all of it.
        """
        return prompt_body(str(text).strip())


class ConciseChatRenderer(ChatRenderer):
    """Chat rendering with the same content policy as a CLI run without -v.

    The engine has already removed events from actions carrying
    ``"visible": false`` before they reach this class.  These overrides only
    remove the diagnostic narration that ConciseRenderer removes from the
    terminal: step/action bookkeeping, skipped branches, outgoing model
    prompts and INFO logs.
    """

    OWN_KINDS = frozenset({'file', 'diff', 'read', 'command'})

    def _step(self, event: dict):
        return None

    def _action_start(self, event: dict):
        return None

    def _skipped(self, event: dict):
        return None

    def _log(self, event: dict):
        level = (event.get('level') or '').upper()
        if level not in ('WARN', 'ERROR'):
            return None
        return super()._log(event)

    def _output(self, event: dict):
        kind = event.get('kind', '')
        if kind == 'prompt':
            return None
        if kind not in self.OWN_KINDS:
            return super()._output(event)

        label = str(event.get('label') or '').strip()
        text = payload_body(event).strip()
        if kind in ('file', 'read'):
            return label or None
        if not label:
            return text or None
        return f'{label}\n{text}' if text else label
