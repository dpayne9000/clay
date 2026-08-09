"""Session commands — lines a human types that the workflow never sees.

A prompt is the only moment a terminal user has the floor, so it is also the
only place a session setting can be changed mid-run. That makes prompts do two
jobs, and the two must not be confusable: `/manual on` changes a setting and
re-asks the question, while `manual on` is an answer to whatever was asked.
The leading slash is the whole distinction, and it is why a command is drawn
differently from an answer rather than echoed back as one.

The grammar lives here, once, so the same words work at a terminal prompt and
as a Telegram bot command. A setting that meant two things on two screens would
be worse than no setting.
"""

from . import approval

_HANDLERS = []


def register(handler, *usages) -> None:
    """Add a command. `handler(text) -> str | None`, None meaning "not mine".

    `usages` are (form, summary) pairs for the help listing — several because
    one handler can have more than one useful shape, and a help line per shape
    is the point of having help at all.
    """
    _HANDLERS.append((handler, list(usages)))


def handle(text: str):
    """Apply `text` as a session command; return what to show, or None.

    None means it was an ordinary answer and belongs to the workflow. A string
    is always shown, including for a command that changed nothing — silence
    after a typo would leave someone believing a gate is on when it is off.
    """
    raw = (text or '').strip()
    if not raw.startswith('/'):
        return None

    for handler, _ in _HANDLERS:
        outcome = handler(raw)
        if outcome is not None:
            return outcome

    word = raw.split()[0]
    return f'{word} is not a command here.\n{help_text()}'


def help_text() -> str:
    """Every registered command, one per line."""
    return '\n'.join(f'  {form:<36} {summary}'
                     for _, usages in _HANDLERS for form, summary in usages)


def _help(text: str):
    if text.strip().split()[0].lower() not in ('/help', '/?'):
        return None
    return f'Commands:\n{help_text()}'


register(approval.handle_command,
         ('/manual [on|off]',
          'ask before writing, reading or running (no argument shows the state)'),
         ('/manual writes|reads|commands on|off',
          'set one gate; takes effect when /manual is on'))
register(_help, ('/help', 'this list'))
