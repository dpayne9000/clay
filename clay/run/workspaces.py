"""Authorize the directories that Clay may access.

Every file action resolves paths under a `root` and refuses to escape it. That
guard constrains paths within a root, but the workflow can provide that root.
Without this outer boundary, `"root": "~"` would place the entire home
directory in scope while satisfying the inner path checks.

A root is usable when it is registered or contained by a registered directory.
Any other root requires human approval.

    ~/.clay/workspaces.json

Grants are by subtree: approving /Users/me/projects covers everything under it.
Containment uses resolve() followed by relative_to(), matching the file action
guards. resolve() removes `..` segments and follows symlinks before comparison.

Each grant defines the session's initial manual-approval gates for that
directory. The keys and polarity match approval.GATES: `fileWrites: true`
means that writes require approval.

Neither the launch directory nor the process working directory is approved
implicitly. This prevents a run launched from a home directory from gaining
access to the entire account without confirmation.
"""

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..lib.config import clay_dir, get_approval_defaults
from . import approval, logger

REGISTER_PATH = os.path.join(clay_dir, 'workspaces.json')

#: Actions without an explicit root use the fixed project directory. _base_for
#: resolves this value through lib.paths.project_dir(), not the live CWD.
DEFAULT_ROOT = '.'

#: Increment this version only for incompatible changes to the on-disk format.
VERSION = 1

_lock = threading.RLock()

#: Directories approved only for this process through "allow once".
_session: set = set()

#: Directories whose gates have been applied during this session. Applying each
#: directory once preserves later /manual changes.
_gates_applied: set = set()


class WorkspaceDenied(Exception):
    """Indicate that a root is outside every approved directory."""


class Grant:
    """Represent an approved directory and its descendant approval gates."""

    def __init__(self, path, gates=None, added: str = ''):
        self.path = Path(path).expanduser().resolve()
        self.gates = _clean_gates(gates)
        self.added = added or _now()

    def covers(self, candidate: Path) -> bool:
        """Return whether `candidate` is this directory or a descendant."""
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
    """Return known Boolean gates, using configured defaults when absent.

    Ignore invalid values so a hand-written grant cannot disable approval by
    supplying a malformed false value.
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
    """Load approved directories, treating an unreadable register as empty.

    An empty result requires approval for every directory. Report unreadable
    data so users can identify why previously approved directories prompt again.
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
    """Replace the workspace register atomically.

    Write a temporary file in the same directory and use os.replace() so a
    crash cannot leave a truncated register.
    """
    payload = {'version': VERSION,
               'approved': [grant.to_json() for grant in grants]}
    temp = f'{REGISTER_PATH}.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2)
        handle.write('\n')
    os.replace(temp, REGISTER_PATH)


def find(path) -> Grant | None:
    """Return the deepest grant covering `path`, or None.

    The deepest grant wins so a specific directory can override gates inherited
    from a broader approved directory.
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
    """Remove an exact directory grant and report whether it existed."""
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
    """Clear allow-once grants and applied-gate state between runs."""
    _session.clear()
    _gates_applied.clear()


# ── the gate ─────────────────────────────────────────────────────────────

#: Explicit workspace approvals. Keep these separate from approval answer words
#: because blank input must not grant access to a directory.
_YES = frozenset({'y', 'yes', 'approve', 'always'})
_ONCE = frozenset({'o', 'once'})

PROMPT_ID = 'workspace.approve'
DAEMON_CAPABILITIES = frozenset(approval.GATES)


@dataclass(frozen=True)
class DaemonAccess:
    """Required and missing permissions for an unattended workflow."""

    path: Path
    required: frozenset[str]
    missing: frozenset[str]
    grant: Grant | None

    @property
    def allowed(self) -> bool:
        return not self.missing


def daemon_access(root, required=None) -> DaemonAccess:
    """Read-only daemon permission check against the effective disk grant."""
    base = _base_for(root)
    needed = DAEMON_CAPABILITIES if required is None else frozenset(required)
    unknown = needed.difference(approval.GATES)
    if unknown:
        raise ValueError(f'unknown daemon capabilities: {", ".join(sorted(unknown))}')

    grant = find(base)
    missing = needed if grant is None else frozenset(
        gate for gate in needed if grant.gates.get(gate, True))
    return DaemonAccess(base, needed, missing, grant)


def grant_daemon_access(root, capabilities=None) -> Grant:
    """Allow selected daemon permissions on one exact directory."""
    base = _base_for(root)
    requested = (DAEMON_CAPABILITIES if capabilities is None
                 else frozenset(capabilities))
    unknown = requested.difference(approval.GATES)
    if unknown:
        raise ValueError(f'unknown daemon capabilities: {", ".join(sorted(unknown))}')

    covering = find(base)
    gates = dict(covering.gates) if covering is not None else _clean_gates(None)
    for gate in requested:
        gates[gate] = False
    return approve(base, gates=gates)


def _base_for(root) -> Path:
    """Resolve a workspace root against the fixed project directory."""
    from ..lib import paths

    path = Path(str(root or DEFAULT_ROOT)).expanduser()
    if not path.is_absolute():
        path = Path(paths.project_dir()) / path
    return path.resolve()


def authorize(root) -> Path:
    """Return an approved root, or raise WorkspaceDenied."""
    base = _base_for(root)

    if base in _session:
        return base

    grant = find(base)
    if grant is not None:
        _apply_gates(grant)
        return base

    if approval.unattended():
        # An unattended run has no human who can approve a new directory.
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

    # Reject blank or unrecognized input rather than treating a typo as consent.
    raise WorkspaceDenied(f'{base} was not approved')


def _apply_gates(grant: Grant) -> None:
    """Initialize session approval gates from a directory grant.

    Apply each directory once per session so later /manual changes persist.
    """
    with _lock:
        if grant.path in _gates_applied:
            return
        _gates_applied.add(grant.path)
    for gate, on in grant.gates.items():
        approval.set_gate(gate, on)
