"""The two path bases clay resolves against, and the rule for each.

Workflows are sequencing data. The project directory is where work happens and
where workflows get used. Nothing resolves against both.

    workflow folders    where a workflow *name* resolves: $CLAY_HOME/workflows
                        first, then the copy shipped in clay/data. A workflow's
                        own assets — its goal, its training text, the
                        sub-workflow its loop calls — resolve against that
                        workflow's directory and nowhere else.

    project directory   where clay works: the directory it was started in, set
                        once and read directly. readFile/writeFile reach it
                        through run/workspaces.py, which gates it.

The process directory is not a workflow folder. A workflow name means the same
thing from every directory, or it means nothing; `clay run -f PATH` is how you
name an exact file with no searching.

Both the project directory and the running workflow's directory are module
state here rather than parameters threaded through every caller — the same
shape run/workspaces.py already uses for its session and gate state. Passing
them by hand is what let a value drift: DEFAULT_ROOT resolved against live cwd
at call time, so a daemon-launched workflow wrote into clay's own checkout
instead of the caller's directory.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Optional

#: The file a workflow directory reference resolves to.
ENTRY_FILE = 'main.json'

#: The subdirectory each workflow folder keeps workflows in.
WORKFLOWS_DIR = 'workflows'


# ── module state ─────────────────────────────────────────────────────────────

#: The project directory, resolved absolute. See project_dir().
_project_dir: Optional[str] = None

#: Directories of the workflows currently executing, innermost last. Pushed by
#: engine.run through in_workflow(); a nested runWorkflow or loop adds a frame.
_stack: list[str] = []


# ── the project directory ────────────────────────────────────────────────────

def set_project_dir(path: str) -> str:
    """Fix the directory clay works in. Called once, at startup.

    `clay run` sets it from the shell's cwd; the daemon sets it from the
    caller's, which arrives over the wire because clayd does not share it.
    Stored absolute, so a later chdir cannot move it.

    Symlinks are followed, because run/workspaces.py follows them before it
    decides whether a directory is approved. Storing the unfollowed name would
    mean clay printed one path and checked permission against another — on
    macOS every temp directory has both a /var and a /private/var name.
    """
    global _project_dir
    _project_dir = os.path.realpath(os.path.expanduser(str(path)))
    return _project_dir


def project_dir() -> str:
    """The directory clay works in.

    Freezes to the process's cwd on first read if nothing set it. That is for
    embedded and test use, where there is no startup to call set_project_dir —
    it fixes a value once rather than leaving every caller to read cwd again
    later and get a different answer.
    """
    if _project_dir is None:
        return set_project_dir(os.getcwd())
    return _project_dir


# ── the workflow folders ─────────────────────────────────────────────────────

def workflow_folder() -> str:
    """The writable workflow folder: $CLAY_HOME/workflows.

    Where a user's own workflows live and where seeding puts the templates.
    The packaged folder sits behind it as the fallback; `_folders` is what
    knows about both, because only name resolution needs to.
    """
    from . import config  # deferred: config imports the action registry
    return config.user_path(WORKFLOWS_DIR)


def _folders() -> list:
    """Where a named workflow is looked for, in order.

    The user's copy first, so an edit to a shipped workflow wins. The package
    second, because it is the one the user cannot change.
    """
    from . import config
    return [
        (config.user_path(), 'user'),
        (config.data_path(), 'package'),
    ]


# ── the running workflow ─────────────────────────────────────────────────────

@contextmanager
def in_workflow(directory: str) -> Iterator[str]:
    """Run a workflow with `directory` as the base its assets resolve against.

    Nests: runWorkflow and loop re-enter engine.run, which pushes a frame of
    its own, so a sub-workflow's `./goal.json` is its own and not its caller's.
    Popped in `finally` — a workflow that raises must not leave its directory
    behind for whatever runs next.
    """
    _stack.append(os.path.abspath(directory))
    try:
        yield _stack[-1]
    finally:
        _stack.pop()


def current_workflow() -> Optional[str]:
    """The directory of the workflow currently executing, or None.

    None when a workflow was handed to the engine as parsed JSON rather than
    loaded from a file (engine.run_from_data) — there is no directory, and
    saying so is better than naming one that has nothing to do with it.
    """
    return _stack[-1] if _stack else None


def workflow_asset(ref: str) -> Optional[str]:
    """Resolve a file the running workflow ships with. None when there is none.

    A workflow's assets travel with it, so they are found beside it or not at
    all. Nothing is searched: falling back to the process directory is what let
    a `goal.json` in whatever directory clay happened to be launched from
    shadow the one the workflow shipped with — silently, producing a run that
    could not be reproduced anywhere else.

    A directory resolves to its ENTRY_FILE, so a sub-workflow can be named by
    its folder: `./pipelines/draft` is `./pipelines/draft/main.json`. Without
    it the directory reaches open() and surfaces as "[Errno 21] Is a directory".

    An absolute ref is returned unchanged. It named one exact file and no
    resolution was asked for.
    """
    if os.path.isabs(ref):
        return ref
    base = current_workflow()
    if base is None:
        return None
    return workflow_file(os.path.normpath(os.path.join(base, ref)))


# ── naming a workflow on the command line ────────────────────────────────────
#
# Two ways to say which workflow to run, and they do not overlap:
#
#     clay run -f ./scratch/thing.json     exactly that path, no searching
#     clay run templates research          segments, searched across the folders
#
# `-f` exists because a search can always surprise you — when you mean *this
# file*, nothing should be looking anywhere else.

def workflow_file(candidate: str) -> Optional[str]:
    """The workflow file `candidate` names, or None. The one tolerance rule.

    Three spellings of the same workflow, decided in one place:

        …/quick-explainer.json    the file itself
        …/research                a directory, meaning its main.json
        …/quick-explainer         a bare name, meaning the .json beside it

    The bare-name case is what keeps `clay workflows` honest. That listing
    prints `templates/content/quick-explainer` with the extension stripped,
    because a reference someone types should not carry one — so the same text
    handed back to `clay run` has to find the file again.

    Public because `clay run -f PATH` asks exactly this question about an exact
    path: the difference between `-f` and the segment form is where they look,
    not what counts as a workflow once found.
    """
    if os.path.isfile(candidate):
        return os.path.abspath(candidate)
    entry = os.path.join(candidate, ENTRY_FILE)
    if os.path.isdir(candidate) and os.path.isfile(entry):
        return os.path.abspath(entry)
    if not candidate.endswith('.json') and os.path.isfile(candidate + '.json'):
        return os.path.abspath(candidate + '.json')
    return None


def _candidates(*segments) -> list:
    """Every place segments could name something, in search order.

    Each folder is tried with and without a `workflows/` prefix, which is what
    lets both of these mean the same thing without special-casing the word:

        clay run workflows templates research
        clay run templates research

    Empty when no segments were given — an empty reference would otherwise
    resolve to each folder itself, and every caller would silently act on the
    whole tree instead of saying nothing was named.
    """
    parts = [str(s) for s in segments if str(s or '').strip()]
    if not parts:
        return []
    ref = os.path.join(*parts)
    return [os.path.normpath(os.path.join(base, ref))
            for folder, _label in _folders()
            for base in (folder, os.path.join(folder, WORKFLOWS_DIR))]


def find_workflow(*segments) -> Optional[str]:
    """Find one runnable workflow named as path segments. None when nothing.

    First hit wins, in `_folders` order. Shadowing is not reported here — a
    warning on every run of a shadowed workflow becomes noise nobody reads.
    `clay workflows` names the duplicates instead, where someone is looking.
    """
    for candidate in _candidates(*segments):
        hit = workflow_file(candidate)
        if hit:
            return hit
    return None


def find_tree(*segments) -> Optional[str]:
    """Find what segments name, without collapsing a directory to its entry.

    The counterpart of `find_workflow`, for commands acting on a whole subtree —
    `clay lint templates` must reach every file under templates/, not just the
    one main.json `find_workflow` would pick out of it.
    """
    for candidate in _candidates(*segments):
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None


def list_workflows() -> list:
    """Every runnable workflow across the folders.

    Returns (label, ref, path) — `ref` being the segments a user would type, so
    a listing can be copied straight back onto the command line.

    A directory holding an ENTRY_FILE is one workflow, and its sibling JSON
    files are that workflow's parts rather than separate entries: listing
    coding2's context.json and iteration.json as things to run would be wrong.
    A directory *without* an ENTRY_FILE holds standalone workflows, and each of
    its JSON files is its own entry.
    """
    found = []
    for folder, label in _folders():
        base = os.path.join(folder, WORKFLOWS_DIR)
        if not os.path.isdir(base):
            continue
        found.extend(_walk_workflows(base, base, label))
    return found


def _walk_workflows(directory: str, base: str, label: str) -> list:
    found = []
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return found

    has_entry = os.path.isfile(os.path.join(directory, ENTRY_FILE))
    if has_entry and directory != base:
        ref = os.path.relpath(directory, base)
        found.append((label, ref.replace(os.sep, '/'),
                      os.path.join(directory, ENTRY_FILE)))

    for name in entries:
        full = os.path.join(directory, name)
        if os.path.isdir(full):
            found.extend(_walk_workflows(full, base, label))
        elif not has_entry and name.endswith('.json'):
            ref = os.path.relpath(full[:-len('.json')], base)
            found.append((label, ref.replace(os.sep, '/'), full))
    return found
