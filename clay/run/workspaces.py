"""Which directories clay may touch at all, and what it asks about in each.

Every file action resolves paths under a `root` and refuses to escape it. That
guard is sound, but it only ever bounded paths *within* a root — the root
itself came straight out of a workflow file, `{placeholder}`-interpolated from
context, so `"root": "~"` was honoured and every check below it was then
satisfied while the whole home directory was in scope.

This is the outer boundary. A root is usable when it is a registered directory
or beneath one; anything else asks a human once and is remembered.

    ~/.clay/workspaces.json

Grants are by subtree: approving /Users/me/projects covers everything under it.
Containment is decided by resolve() then relative_to(), the same primitive the
path guards already use, so there is one escape story rather than two — and
resolve() collapses `..` and follows symlinks before the comparison is made.

Each grant also carries the manual-approval gates a session starts with while
working there, so "this directory is mine, don't ask about writes in it" and
"this one is shared, ask every time" are the same mechanism rather than two.
The keys and their polarity are exactly approval.GATES': ``fileWrites: true``
means *ask before writing*, here as everywhere else. One word, one meaning.

Nothing is approved implicitly — not the launch directory, not the process CWD.
A CLI grants the directory it was started in the moment someone answers for it,
which is a decision worth seeing once, and `clay run` from a home directory
would otherwise put an entire account in scope without ever drawing a prompt.
"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..lib.config import clay_dir, get_approval_defaults
from . import approval, logger

REGISTER_PATH = os.path.join(clay_dir, 'workspaces.json')

#: Where an action with no explicit `root` works: the project directory, the
#: one clay was started in. Previously "output", which resolved to $CWD/output —
#: so the same workflow wrote to a different place depending on where it was
#: launched, and a coding workflow read its sources from one directory and
#: wrote to another. One string here rather than a copy per module, which is how
#: the four resolvers came to disagree in the first place.
#:
#: Resolved by _base_for against lib.paths.project_dir(), not against live cwd.
DEFAULT_ROOT = '.'

#: Bumped only if the on-disk shape changes incompatibly. A register written by
#: a newer clay is left alone rather than silently rewritten to this shape.
VERSION = 1

_lock = threading.RLock()

#: Directories approved for this process only ("allow once"). Not written to
#: the register, and gone when the run ends — the same session model approval
#: uses, for the same reason: a one-off answer must not outlive its run.
_session: set = set()

#: Directories whose gates have already been applied this session. Applied on
#: first use rather than on every action, so a `/manual` toggle typed mid-run
#: is not overwritten by the next file action in the same directory.
_gates_applied: set = set()


class WorkspaceDenied(Exception):
    """A root outside every approved directory. Never a silent no-op."""


class Grant:
    """One approved directory and the gates that apply beneath it."""

    def __init__(self, path, gates=None, added: str = ''):
        self.path = Path(path).expanduser().resolve()
        self.gates = _clean_gates(gates)
        self.added = added or _now()

    def covers(self, candidate: Path) -> bool:
        """Whether `candidate` is this directory or lives under it."""
        try:
            candidate.relative_to(self.path)
        except ValueError:
            return False
        return True

    def depth(self) -> int:
        return len(self.path.parts)

    def to_json(self) -> dict:
        return {'path': str(self.path), 'added': self.added,
                'gates': dict(self.gates)}

    @classmethod
    def from_json(cls, raw):
        if not isinstance(raw, dict) or not str(raw.get('path') or '').strip():
            return None
        return cls(raw['path'], raw.get('gates'), str(raw.get('added') or ''))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clean_gates(gates) -> dict:
    """Only the known gates, only booleans, defaults for anything missing.

    A directory written by hand is as likely to carry a typo as a config file,
    and a gate that silently reads as false is one that stops asking.
    """
    settled = {key: bool(value) for key, value in get_approval_defaults().items()
               if key in approval.GATES}
    if isinstance(gates, dict):
        for key in approval.GATES:
            if isinstance(gates.get(key), bool):
                settled[key] = gates[key]
    return settled


# ── the register ─────────────────────────────────────────────────────────

def load() -> list:
    """Every approved directory. Never raises; an unreadable register is empty.

    Empty means everything asks, which is the safe direction to fail in: a
    corrupt file must not be read as a grant. It says so rather than failing
    silently, because "why is it suddenly asking about my project" needs an
    answer.
    """
    try:
        with open(REGISTER_PATH, encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as error:
        print(f'workspaces: {REGISTER_PATH} could not be read ({error}) '
              f'— treating every directory as unapproved')
        return []

    entries = data.get('approved') if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [grant for grant in (Grant.from_json(raw) for raw in entries)
            if grant is not None]


def save(grants) -> None:
    """Write the register, replacing it atomically.

    Via a temp file in the same directory and os.replace: a register truncated
    by a crash mid-write would read as empty, and empty means every directory a
    person already approved starts asking again.
    """
    payload = {'version': VERSION,
               'approved': [grant.to_json() for grant in grants]}
    temp = f'{REGISTER_PATH}.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
        handle.write('\n')
    os.replace(temp, REGISTER_PATH)


def find(path) -> Grant | None:
    """The approved directory covering `path`, deepest first, or None.

    Deepest wins so a specific directory's gates beat the broad grant it sits
    inside — approving all of ~/projects and then saying "ask about writes in
    ~/projects/client" has to mean the narrower thing.
    """
    candidate = Path(path).expanduser().resolve()
    covering = [grant for grant in load() if grant.covers(candidate)]
    if not covering:
        return None
    return max(covering, key=Grant.depth)


def approve(path, gates=None) -> Grant:
    """Record `path` as approved, replacing any grant for that exact directory.

    Directories already covered by a *broader* grant are left in place: they
    may carry narrower gates, and find() prefers the deepest match.
    """
    grant = Grant(path, gates)
    with _lock:
        grants = [existing for existing in load() if existing.path != grant.path]
        grants.append(grant)
        save(sorted(grants, key=lambda entry: str(entry.path)))
    logger.info(f'workspaces: approved {grant.path} (and everything under it)')
    return grant


def forget(path) -> bool:
    """Remove one exact directory. True when something was removed."""
    target = Path(path).expanduser().resolve()
    with _lock:
        grants = load()
        kept = [grant for grant in grants if grant.path != target]
        if len(kept) == len(grants):
            return False
        save(kept)
    _session.discard(target)
    _gates_applied.discard(target)
    return True


def reset_session() -> None:
    """Drop allow-once grants and let gates re-apply. For tests and for reuse
    of a process across runs."""
    _session.clear()
    _gates_applied.clear()


# ── the gate ─────────────────────────────────────────────────────────────

#: Answers, kept apart from approval's word lists on purpose. A blank line
#: approves everything at an approval prompt — the sensible default when the
#: question is "these three files, yes?". Here the question is "may clay have
#: this directory", and a stray newline must not answer it.
_YES = frozenset({'y', 'yes', 'approve', 'always'})
_ONCE = frozenset({'o', 'once'})

PROMPT_ID = 'workspace.approve'


def _base_for(root) -> Path:
    """The absolute directory `root` names, relative ones against the project.

    A relative root — including DEFAULT_ROOT, which is what an action with no
    `root` at all gets — belongs to the directory clay was started in, not to
    whatever cwd happens to be when the action runs. Those are the same thing
    for `clay run` in a terminal and are not the same thing under clayd, which
    sets its children's cwd to clay's own checkout: a workflow with no `root`
    was writing into the program instead of into the caller's project.
    """
    from ..lib import paths

    path = Path(str(root or DEFAULT_ROOT)).expanduser()
    if not path.is_absolute():
        path = Path(paths.project_dir()) / path
    return path.resolve()


def authorize(root) -> Path:
    """Return `root` resolved, once it is known to be an approved directory.

    Raises WorkspaceDenied otherwise. Every file action calls this before it
    resolves anything, so a new file action cannot quietly skip the boundary by
    forgetting a check — there is one check.
    """
    base = _base_for(root)

    if base in _session:
        return base

    grant = find(base)
    if grant is not None:
        _apply_gates(grant)
        return base

    if approval.unattended():
        # Deliberately not approval.confirm()'s choice. That decides whether an
        # action proceeds inside a boundary a human already drew; this decides
        # where the boundary is, and a scheduled run must not be able to widen
        # its own reach because nobody was watching.
        raise WorkspaceDenied(
            f'{base} is not an approved working directory, and this run has no '
            f'human to ask. Approve it with:  clay dirs add {base}')

    return _ask(base)


def _ask(base: Path) -> Path:
    from . import io  # deferred: io's terminal prompt calls back into approval

    text = (f'clay wants to use a directory it has not been given access to:\n'
            f'\n    {base}\n\n'
            f'Approving covers this directory and everything under it.\n\n'
            f'[y] approve and remember   [o] allow once   [n] refuse')

    try:
        answer = io.get().prompt(PROMPT_ID, text)
    except io.ChannelClosed:
        raise WorkspaceDenied(
            f'{base} is not an approved working directory, and the input '
            f'channel closed before it could be answered') from None

    reply = str(answer or '').strip().lower()
    if reply in _YES:
        _apply_gates(approve(base))
        return base
    if reply in _ONCE:
        _session.add(base)
        logger.info(f'workspaces: allowing {base} for this run only')
        return base

    # Anything else refuses, blank included. A typo must not hand over a
    # directory, and there is no cost to being asked twice.
    raise WorkspaceDenied(f'{base} was not approved')


def _apply_gates(grant: Grant) -> None:
    """Seed the session's approval gates from the directory being entered.

    Once per directory per session: applying on every action would overwrite a
    `/manual` toggle typed mid-run with the file on disk, every time the next
    file action came round.
    """
    with _lock:
        if grant.path in _gates_applied:
            return
        _gates_applied.add(grant.path)
    for gate, on in grant.gates.items():
        approval.set_gate(gate, on)
