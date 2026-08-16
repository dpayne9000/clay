"""Resolve project paths and workflow paths against distinct bases.

The project directory contains work products. Workflow directories contain
workflow definitions and their packaged assets. No path resolves against both.

    workflow folders    where a workflow *name* resolves: $CLAY_HOME/workflows
                        first, then the copy shipped in clay/data. A workflow's
                        own assets — its goal, its training text, the
                        sub-workflow its loop calls — resolve against that
                        workflow's directory and nowhere else.

    project directory   where clay works: the directory it was started in, set
                        once and read directly. readFile/writeFile reach it
                        through run/workspaces.py, which gates it.

The process directory is not a workflow search folder. Use `clay run -f PATH`
to select an exact file without searching.

Module state holds both bases so every caller uses the same values. In
particular, daemon workflows must retain the caller's project directory instead
of resolving against clayd's current working directory.
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

#: Active workflow directories ordered from outermost to innermost.
_stack: list[str] = []


# ── the project directory ────────────────────────────────────────────────────

def set_project_dir(path: str) -> str:
    """Set and return Clay's fixed project directory.

    `clay run` uses the shell's working directory, while clayd receives the
    caller's directory over its connection. Store an absolute path so later
    directory changes cannot affect it.

    Resolve symlinks to match workspace authorization and ensure displayed and
    authorized paths identify the same directory.
    """
    global _project_dir
    _project_dir = os.path.realpath(os.path.expanduser(str(path)))
    return _project_dir


def project_dir() -> str:
    """Return Clay's fixed project directory.

    Embedded and test callers default to the process directory on first access.
    Subsequent calls retain that value.
    """
    if _project_dir is None:
        return set_project_dir(os.getcwd())
    return _project_dir


# ── the workflow folders ─────────────────────────────────────────────────────

def workflow_folder() -> str:
    """Return the writable workflow folder under CLAY_HOME.

    User workflows and seeded templates live here. Name resolution also searches
    the packaged fallback through _folders().
    """
    from . import config  # deferred: config imports the action registry
    return config.user_path(WORKFLOWS_DIR)


def _folders() -> list:
    """Return workflow search folders in precedence order.

    User files take precedence over read-only packaged files.
    """
    from . import config
    return [
        (config.user_path(), 'user'),
        (config.data_path(), 'package'),
    ]


# ── the running workflow ─────────────────────────────────────────────────────

@contextmanager
def in_workflow(directory: str) -> Iterator[str]:
    """Use `directory` as the asset base during workflow execution.

    Nested workflows push their own base, so relative assets belong to the
    current workflow. The finally block restores the previous base after errors.
    """
    _stack.append(os.path.abspath(directory))
    try:
        yield _stack[-1]
    finally:
        _stack.pop()


def current_workflow() -> Optional[str]:
    """Return the current workflow directory, or None for in-memory data.

    engine.run_from_data() provides no directory for relative assets.
    """
    return _stack[-1] if _stack else None


def workflow_asset(ref: str) -> Optional[str]:
    """Resolve an asset relative to the active workflow directory.

    Do not search other directories because process-local files could otherwise
    shadow packaged assets and make runs depend on their launch location.

    A directory resolves to ENTRY_FILE, allowing a sub-workflow reference to
    name its folder.

    Return absolute references unchanged.
    """
    if os.path.isabs(ref):
        return ref
    base = current_workflow()
    if base is None:
        return None
    return workflow_file(os.path.normpath(os.path.join(base, ref)))


# ── naming a workflow on the command line ────────────────────────────────────
#
# Workflow selection supports exact files and searched names:
#
#     clay run -f ./scratch/thing.json     exactly that path, no searching
#     clay run templates research          segments, searched across the folders
#
# Use `-f` when search behavior would be inappropriate.

def workflow_file(candidate: str) -> Optional[str]:
    """Resolve `candidate` to a workflow file, or return None.

    Three spellings of the same workflow, decided in one place:

        …/quick-explainer.json    the file itself
        …/research                a directory, meaning its main.json
        …/quick-explainer         a bare name, meaning the .json beside it

    Bare names without `.json` support references copied from `clay workflows`.

    Both exact and searched references use these rules after locating a candidate.
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
    """Return every location that path segments could name, in search order.

    Search each folder with and without a `workflows/` prefix:

        clay run workflows templates research
        clay run templates research

    Return no candidates for empty input to prevent callers from acting on an
    entire workflow tree.
    """
    parts = [str(s) for s in segments if str(s or '').strip()]
    if not parts:
        return []
    ref = os.path.join(*parts)
    return [os.path.normpath(os.path.join(base, ref))
            for folder, _label in _folders()
            for base in (folder, os.path.join(folder, WORKFLOWS_DIR))]


def find_workflow(*segments) -> Optional[str]:
    """Return the first runnable workflow named by path segments.

    Search in _folders() order. `clay workflows` reports shadowed names instead
    of warning on every execution.
    """
    for candidate in _candidates(*segments):
        hit = workflow_file(candidate)
        if hit:
            return hit
    return None


def find_tree(*segments) -> Optional[str]:
    """Resolve path segments without converting a directory to its entry file.

    Commands such as `clay lint templates` use this function to retain the
    complete subtree.
    """
    for candidate in _candidates(*segments):
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None


def list_workflows() -> list:
    """Return every runnable workflow across search folders.

    Each result is (label, ref, path), where ref can be reused on the command line.

    A directory containing ENTRY_FILE represents one workflow; sibling JSON
    files are its assets. Without ENTRY_FILE, each JSON file is standalone.
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
