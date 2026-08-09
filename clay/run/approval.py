"""Whether a destructive action asks a human first, and how it asks.

Three gates, switched independently, because they are three different risks:

    fileWrites   applyFileWrites, before anything reaches disk
    fileReads    serveFileReads, before anything is opened
    commands     runReplyCommands, before anything is executed

State is per process, and a process is a session: clayd spawns one subprocess
per workflow, plain `clay run` is its own process, and `clay ui` runs its
workflow on a worker thread of the app. So two sessions cannot share a setting
by accident, there is no session id to plumb anywhere, and nothing is left
behind when a run crashes.

config.json supplies only the settings a *new* session starts with and is never
written by a toggle. A switch typed mid-run that edited a hand-maintained file
would outlive the session that set it, and the next unrelated run would start
gated because of something someone typed yesterday.

Three surfaces move the switch, and all of them land here:

    clay run    a command typed at any terminal prompt   → handle_command()
    clay ui     a toggle per gate in the run panel       → set_gate()
    Telegram    /manual …, relayed by clayd as option.set → set_gate()

The gate itself is called from the *handlers*, never the dispatcher: the
dispatcher has the action dict, but only the handler knows which files and
which commands, and a prompt that cannot name them is not worth showing.
"""

import threading

from ..lib.config import get_approval_defaults
from . import logger

#: The gates, in the order a prompt or a status line should list them.
GATES = ('fileWrites', 'fileReads', 'commands')

#: What each gate is called when a human types it. The canonical name works
#: too; these are the short words a person actually reaches for.
_ALIASES = {
    'writes': 'fileWrites', 'write': 'fileWrites', 'filewrites': 'fileWrites',
    'reads': 'fileReads', 'read': 'fileReads', 'filereads': 'fileReads',
    'commands': 'commands', 'command': 'commands', 'cmd': 'commands',
    'bash': 'commands', 'shell': 'commands',
}

_LABELS = {'fileWrites': 'writes', 'fileReads': 'reads', 'commands': 'commands'}

#: Every approval prompt's id ends with this, so a front-end can recognise one
#: without parsing its text. A chat that cannot tell an approval apart from a
#: humanDecision cannot offer buttons for one and not the other.
PROMPT_SUFFIX = '.approve'

_ON = frozenset({'on', 'true', 'yes', 'y', '1', 'enable', 'enabled'})
_OFF = frozenset({'off', 'false', 'no', 'n', '0', 'disable', 'disabled'})

#: Answers to an approval prompt, where a bare number means an item to skip and
#: so cannot also mean yes or no. Kept apart from _ON/_OFF for that reason.
_APPROVE_ALL = frozenset({'y', 'yes', 'ok', 'approve', 'all'})
_REJECT_ALL = frozenset({'n', 'no', 'none', 'reject', 'cancel', 'abort'})

_lock = threading.Lock()
_state = None
_unattended = False


def _load() -> dict:
    """The session's settings, seeded from config on first use.

    Lazy rather than imported at module load so a test — or a UI that changes
    the config before starting a run — is not fighting a snapshot taken when
    the interpreter started.
    """
    global _state
    with _lock:
        if _state is None:
            _state = get_approval_defaults()
        return _state


def reset() -> None:
    """Drop the session's settings so the next read re-seeds from config."""
    global _state, _unattended
    with _lock:
        _state = None
        _unattended = False


def set_unattended(on: bool) -> None:
    """Record whether this run has a human who could answer a prompt.

    Set from dispatch() on every action rather than read from a launch flag,
    because a workflow can start a nested one and the answer is a property of
    the run in progress, not of how the process began.
    """
    global _unattended
    _unattended = bool(on)


# ── reading ──────────────────────────────────────────────────────────────

def enabled(gate: str) -> bool:
    """Whether `gate` should ask a human before acting.

    Two levels, deliberately: `/manual off` has to silence everything with one
    word, while the gates stay independently set underneath so turning it back
    on restores the arrangement someone chose rather than a blanket default.
    """
    state = _load()
    return bool(state.get('manual')) and bool(state.get(gate))


def manual() -> bool:
    """Whether the master switch is on."""
    return bool(_load().get('manual'))


def unattended() -> bool:
    """Whether this run has nobody who could answer a prompt.

    Read by workspaces.authorize(), which refuses rather than auto-approves —
    the opposite of confirm()'s choice, and deliberately so. See its docstring.
    """
    return _unattended


def state() -> dict:
    """A copy of the session's settings. A copy so callers cannot poke it."""
    return dict(_load())


def summary() -> str:
    """One line naming the master switch and every gate under it."""
    current = _load()
    if not current.get('manual'):
        return 'manual approval off — nothing asks before acting'
    gates = ', '.join(f'{_LABELS[g]} {"on" if current.get(g) else "off"}'
                      for g in GATES)
    return f'manual approval on — {gates}'


# ── writing ──────────────────────────────────────────────────────────────

def set_manual(on: bool) -> None:
    """Move the master switch. Leaves the individual gates as they were."""
    _load()
    with _lock:
        _state['manual'] = bool(on)


def set_gate(gate: str, on: bool) -> None:
    """Turn one gate on or off. Unknown gate names raise rather than no-op."""
    if gate not in GATES:
        raise ValueError(f'unknown approval gate {gate!r}')
    _load()
    with _lock:
        _state[gate] = bool(on)


def resolve_gate(word: str) -> str:
    """The canonical gate name for what a human typed, or '' if it is not one."""
    return _ALIASES.get((word or '').strip().lower(), '')


# ── the command grammar, shared by every surface ─────────────────────────

USAGE = ('Try /manual on|off, or /manual writes|reads|commands on|off')


class Command:
    """A parsed /manual line: what it changes, and what to say about it.

    Parsing is separated from applying because the two happen in different
    processes. A terminal types the command in the process that holds the
    setting; Telegram types it in the bot, and the setting lives in the
    workflow clayd spawned. One grammar, two ways to deliver the result — and
    `error` marks the lines that change nothing so a front-end does not relay a
    typo to a workflow as though it were a setting.
    """

    def __init__(self, changes=(), message: str = '', error: bool = False):
        self.changes = list(changes)   # [(key, bool), …]
        self.message = message
        self.error = error


def parse_command(text: str):
    """Read `text` as a manual-mode command. None means it was not one.

    One grammar for the terminal, Telegram and anything later, so `/manual reads
    off` cannot come to mean two different things on two screens.

        /manual                 show the current settings
        /manual on | off        the master switch
        /manual reads on        one gate
        /manual writes off
    """
    raw = (text or '').strip()
    if not raw.startswith('/'):
        return None

    parts = raw[1:].split()
    if not parts or parts[0].lower() != 'manual':
        return None

    args = [p.lower() for p in parts[1:]]
    if not args:
        return Command()

    if len(args) == 1:
        if args[0] in _ON:
            return Command([('manual', True)])
        if args[0] in _OFF:
            return Command([('manual', False)])
        gate = resolve_gate(args[0])
        if gate:
            return Command(message=f'say "/manual {args[0]} on" or "off" '
                                   f'to change {_LABELS[gate]} approval')
        return Command(message=f'"{args[0]}" is not a manual setting. {USAGE}',
                       error=True)

    gate = resolve_gate(args[0])
    if not gate:
        return Command(message=f'"{args[0]}" is not a manual setting. {USAGE}',
                       error=True)
    if args[1] in _ON:
        return Command([(gate, True)])
    if args[1] in _OFF:
        return Command([(gate, False)])
    return Command(message=f'"{args[1]}" is not on or off', error=True)


def handle_command(text: str):
    """Parse `text`, apply it to *this* process, and return what to show.

    None means it was not a command and belongs to whoever asked the question.
    A string is always shown, even when nothing changed: silence after a typo
    would leave someone believing a gate is on when it is off.
    """
    command = parse_command(text)
    if command is None:
        return None

    for key, value in command.changes:
        if key == 'manual':
            set_manual(value)
        else:
            set_gate(key, value)

    if command.message:
        return f'{command.message}\n{summary()}' if not command.error \
            else command.message

    changed_gate = next((k for k, _ in command.changes if k != 'manual'), '')
    if changed_gate and not manual():
        # Said out loud rather than quietly turning the master switch on for
        # them: someone arranging gates before enabling manual mode is doing
        # something reasonable, and someone who thinks they just enabled a gate
        # needs to know they did not.
        return (f'{summary()} — {_LABELS[changed_gate]} is set, and takes '
                f'effect when you say /manual on')
    return summary()


# ── asking ───────────────────────────────────────────────────────────────

class Decision:
    """Which of a set of items a human allowed through.

    A class rather than a list of indices because every caller needs both
    halves — what to do and what to say about the rest — and rebuilding the
    rejected set from the approved one at three call sites is how they come to
    disagree about what was skipped.
    """

    def __init__(self, items, approved):
        self.items = list(items)
        self.approved = sorted(set(approved))

    @property
    def rejected(self) -> list:
        return [i for i in range(len(self.items)) if i not in set(self.approved)]

    @property
    def all_approved(self) -> bool:
        return len(self.approved) == len(self.items)

    def approved_labels(self) -> list:
        return [self.items[i][0] for i in self.approved]

    def rejected_labels(self) -> list:
        return [self.items[i][0] for i in self.rejected]

    def __bool__(self) -> bool:
        return bool(self.approved)


def confirm(gate: str, heading: str, items, prompt_id: str = '', *,
            required: bool = False) -> Decision:
    """Ask a human which of `items` may go ahead.

    `items` is a sequence of (label, detail) pairs — one file, one command. The
    text is built here and handed to io.get().prompt(), which is why this works
    unchanged on the terminal, in `clay ui` and in Telegram: those are three
    implementations of one channel, not three approval systems.

    When ``required`` is true, configuration cannot bypass the question and an
    unattended run approves nothing. Generated code, commands and file changes
    use this mode because absence of a human is not authorization.
    """
    items = [(str(label), str(detail or '')) for label, detail in items]
    everything = Decision(items, range(len(items)))

    if not items:
        return everything

    if not required and not enabled(gate):
        return everything

    if _unattended:
        logger.warn(f'approval: {heading} — refused, no human on this run')
        return Decision(items, [])

    from . import io  # deferred: io's terminal prompt calls handle_command()

    listing = '\n'.join(f'  {n}. {label}' + (f'\n{_indent(detail)}' if detail else '')
                        for n, (label, detail) in enumerate(items, 1))
    text = (f'{heading}\n\n{listing}\n\n'
            f'[y] approve all   [n] reject all   '
            f'or list the numbers to skip, e.g. "2 4"')

    key = prompt_id or gate
    if not key.endswith(PROMPT_SUFFIX):
        key += PROMPT_SUFFIX

    try:
        answer = io.get().prompt(key, text)
    except io.ChannelClosed:
        # A closed channel is not consent. The run has lost the human it was
        # about to ask, and proceeding would do the exact thing manual mode
        # exists to prevent.
        logger.warn(f'approval: {heading} — input channel closed, '
                    f'nothing approved')
        return Decision(items, [])

    # The prompt dropped every front-end's busy indicator (io._floor_to_human)
    # to keep a spinner from eating the question. The question is answered
    # now, and the handler is about to do the actual work — execute the
    # source, write the files, run the command — so the indicator has to come
    # back up here. logger.busy(True) is a relabel, not a second "started"
    # event: this is the same level output() would raise the moment the next
    # action.output payload comes in, just not stalled until then.
    logger.busy(True, gate)

    return _parse_answer(answer, items)


def _indent(text: str) -> str:
    return '\n'.join(f'     {line}' for line in str(text).splitlines())


def _parse_answer(answer, items) -> Decision:
    """Read a human's reply as a set of approvals.

    Numbers are the items to *skip*, not the ones to keep: rejecting one bad
    command out of five should not mean typing the other four, and that is the
    direction a person reaches for when they say "not that one".

    A blank line approves everything, matching every other [Y/n] prompt in
    clay. Anything unrecognised approves nothing — a typo must not be read as
    consent to write files.
    """
    # Deliberately not _ON/_OFF: those contain "1" and "0", and here a bare
    # number is an item to skip. Reading "1" as "approve everything" would turn
    # "don't write the first file" into "write all of them".
    raw = str(answer or '').strip()
    if not raw or raw.lower() in _APPROVE_ALL:
        return Decision(items, range(len(items)))
    if raw.lower() in _REJECT_ALL:
        return Decision(items, [])

    tokens = [t for t in raw.replace(',', ' ').split() if t]
    skip = set()
    for token in tokens:
        if not token.isdigit():
            logger.warn(f'approval: could not read {raw!r} as an answer '
                        f'— nothing approved')
            return Decision(items, [])
        index = int(token) - 1
        if not 0 <= index < len(items):
            logger.warn(f'approval: there is no item {token} '
                        f'— nothing approved')
            return Decision(items, [])
        skip.add(index)

    return Decision(items, [i for i in range(len(items)) if i not in skip])
