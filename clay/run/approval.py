"""Control whether and how destructive actions require human approval.

Three independent gates cover three distinct risks:

    fileWrites   applyFileWrites, before anything reaches disk
    fileReads    serveFileReads, before anything is opened
    commands     runReplyCommands, before anything is executed

Approval state is process-local. Each clayd workflow and plain `clay run` uses
its own process, while `clay ui` runs its workflow on an application worker
thread. Sessions therefore cannot accidentally share settings, no session ID
is required, and a crashed run leaves no approval state behind.

config.json defines the initial settings for a new session. Runtime toggles do
not modify it because a session-specific choice must not affect later runs.

Three interfaces update approval state through this module:

    clay run    a command typed at any terminal prompt   → handle_command()
    clay ui     a toggle per gate in the run panel       → set_gate()
    Telegram    /manual …, relayed by clayd as option.set → set_gate()

Handlers invoke approval gates instead of the dispatcher. The dispatcher has
the action dictionary, but only a handler knows the specific files or commands
that the approval prompt must identify.
"""

import threading

from ..lib.config import get_approval_defaults
from . import logger

#: Approval gates in display order.
GATES = ('fileWrites', 'fileReads', 'commands')

#: Short aliases accepted in addition to each gate's canonical name.
_ALIASES = {
    'writes': 'fileWrites', 'write': 'fileWrites', 'filewrites': 'fileWrites',
    'reads': 'fileReads', 'read': 'fileReads', 'filereads': 'fileReads',
    'commands': 'commands', 'command': 'commands', 'cmd': 'commands',
    'bash': 'commands', 'shell': 'commands',
}

_LABELS = {'fileWrites': 'writes', 'fileReads': 'reads', 'commands': 'commands'}

#: This suffix lets front-ends identify approval prompts without parsing text.
#: It also lets chat clients distinguish approvals from humanDecision prompts.
PROMPT_SUFFIX = '.approve'

_ON = frozenset({'on', 'true', 'yes', 'y', '1', 'enable', 'enabled'})
_OFF = frozenset({'off', 'false', 'no', 'n', '0', 'disable', 'disabled'})

#: Approval answers exclude numbers because a number identifies an item to skip.
#: These values must therefore remain separate from _ON and _OFF.
_APPROVE_ALL = frozenset({'y', 'yes', 'ok', 'approve', 'all'})
_REJECT_ALL = frozenset({'n', 'no', 'none', 'reject', 'cancel', 'abort'})

_lock = threading.Lock()
_state = None
_unattended = False


def _load() -> dict:
    """Load the session settings from config on first use.

    Lazy loading lets tests and the UI change configuration before a run starts
    without retaining a snapshot created when the module was imported.
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
    """Return whether `gate` should ask a human before acting.

    The master switch can disable all prompts without changing individual gate
    settings. Re-enabling it therefore restores the previous gate arrangement.
    """
    state = _load()
    return bool(state.get('manual')) and bool(state.get(gate))


def manual() -> bool:
    """Return whether the master approval switch is on."""
    return bool(_load().get('manual'))


def unattended() -> bool:
    """Return whether this run has no human available to answer a prompt.

    workspaces.authorize() uses this value to refuse rather than automatically
    approve access. See its docstring for the corresponding security policy.
    """
    return _unattended


def state() -> dict:
    """Return a copy of the session settings to prevent external mutation."""
    return dict(_load())


def summary() -> str:
    """Summarize the master switch and each approval gate on one line."""
    current = _load()
    if not current.get('manual'):
        return 'manual approval off — nothing asks before acting'
    gates = ', '.join(f'{_LABELS[g]} {"on" if current.get(g) else "off"}'
                      for g in GATES)
    return f'manual approval on — {gates}'


# ── writing ──────────────────────────────────────────────────────────────

def set_manual(on: bool) -> None:
    """Set the master switch without changing individual gates."""
    _load()
    with _lock:
        _state['manual'] = bool(on)


def set_gate(gate: str, on: bool) -> None:
    """Set one gate, raising ValueError for an unknown gate name."""
    if gate not in GATES:
        raise ValueError(f'unknown approval gate {gate!r}')
    _load()
    with _lock:
        _state[gate] = bool(on)


def resolve_gate(word: str) -> str:
    """Return the canonical gate name for user input, or '' if none matches."""
    return _ALIASES.get((word or '').strip().lower(), '')


# ── the command grammar, shared by every surface ─────────────────────────

USAGE = ('Try /manual on|off, or /manual writes|reads|commands on|off')


class Command:
    """Represent the changes and response produced by a parsed /manual command.

    Parsing and application are separate because they may occur in different
    processes. Terminal commands run where the setting is stored, while a
    Telegram command is parsed by the bot and applied by the clayd workflow
    process. The `error` flag prevents a front-end from relaying invalid input
    as a setting change.
    """

    def __init__(self, changes=(), message: str = '', error: bool = False):
        self.changes = list(changes)   # [(key, bool), …]
        self.message = message
        self.error = error


def parse_command(text: str):
    """Parse `text` as a manual-mode command, or return None if it is unrelated.

    All interfaces share this grammar so a command has the same meaning on the
    terminal, Telegram, and future clients.

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
    """Parse `text`, apply it to this process, and return a response to display.

    None indicates that the text is not a command and should remain a response
    to the original prompt. Commands always return a message so invalid input
    cannot leave the user uncertain about the current approval state.
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
        # Do not enable the master switch implicitly. A user may configure gates
        # before enabling manual mode and must be told that the gate is inactive.
        return (f'{summary()} — {_LABELS[changed_gate]} is set, and takes '
                f'effect when you say /manual on')
    return summary()


# ── asking ───────────────────────────────────────────────────────────────

class Decision:
    """Record which items a human approved.

    Callers need both approved and rejected items. Keeping that calculation in
    one class prevents call sites from reporting a different rejected set than
    the one they acted upon.
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

    `items` is a sequence of (label, detail) pairs representing files, commands,
    or other operations. This function builds the prompt and passes it to
    io.get().prompt(), whose channel implementations support the terminal,
    `clay ui`, and Telegram through the same approval path.

    When the gate is off, all items are approved without a prompt. For an
    unattended daemon, this represents the advance authorization recorded in
    its workspace grant; otherwise no persisted setting could authorize it.

    When the gate is on during an unattended run, no items are approved because
    no human can answer. `required` identifies security-sensitive call sites;
    it does not override advance authorization or an unanswered enabled gate.
    """
    items = [(str(label), str(detail or '')) for label, detail in items]
    everything = Decision(items, range(len(items)))

    if not items:
        return everything

    if not enabled(gate):
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
        # A closed channel cannot provide consent, so reject every item.
        logger.warn(f'approval: {heading} — input channel closed, '
                    f'nothing approved')
        return Decision(items, [])

    # io._floor_to_human() clears busy indicators before displaying a prompt.
    # Restore the indicator now because the handler is resuming work.
    # logger.busy(True) relabels the existing operation; it does not start a
    # second one or wait for the next action.output event.
    logger.busy(True, gate)

    return _parse_answer(answer, items)


def _indent(text: str) -> str:
    return '\n'.join(f'     {line}' for line in str(text).splitlines())


def _parse_answer(answer, items) -> Decision:
    """Read a human's reply as a set of approvals.

    Numbers identify items to skip rather than items to keep. A user can reject
    one item without listing every item that should proceed.

    A blank line approves everything, matching every other [Y/n] prompt in
    clay. Anything unrecognised approves nothing — a typo must not be read as
    consent to write files.
    """
    # Do not use _ON or _OFF here because they contain "1" and "0". In this
    # prompt, a bare number identifies an item to skip.
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
