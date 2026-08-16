"""Handle session commands without passing them to the workflow.

A terminal accepts session commands while waiting at a prompt. A leading slash
distinguishes `/manual on`, which changes a setting and repeats the prompt, from
`manual on`, which answers the workflow's question.

The terminal and Telegram use this shared grammar so commands have consistent
meaning across interfaces.
"""

from . import approval

_HANDLERS = []


def register(handler, *usages) -> None:
    """Register a command handler and its help entries.

    A handler returns None for unrelated input. Each usage is a (form, summary)
    pair, and one handler may advertise multiple forms.
    """
    _HANDLERS.append((handler, list(usages)))


def handle(text: str):
    """Apply a session command and return its display message.

    Return None when `text` is an ordinary workflow answer. Commands always
    return a message, including invalid commands that change no state.
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
    """List each registered command on a separate line."""
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
