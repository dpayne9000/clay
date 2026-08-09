# 2026-07-31 — Install paths and workflow naming

Groundwork for a relocatable install. Everything here is about clay stopping
assuming it is running out of a git checkout.

Tracked in [docs/tasks/install-packaging.md](../tasks/install-packaging.md).

## Shipped data moved into the package

`configs/`, `skills/` and the `system`, `templates` and `registry` workflow
trees now live under `clay/data/`. They were previously found by walking three
directories up from `__file__`, which only resolves inside a checkout.

The split is program versus content:

- `clay/data/workflows/system` is program. Read from the package, never copied.
- `templates/`, `registry/`, `skills/`, `memory/` are content. Seeded into the
  user directory, and yours to edit afterwards.

## `$CLAY_HOME`

The user directory is `$CLAY_HOME` when set, `~/.clay` otherwise, resolved once
at import as a module constant in `clay/lib/config.py`.

New in that module: `data_path()` (shipped, read-only), `user_path()`
(writable), `resource()` (user copy first, shipped second), `ensure_user_dir()`
and `seed_user_dir()`.

Importing `config` no longer creates directories. Seeding happens once in
`cli()` after `parse_args`, so `clay --help` and mistyped commands write
nothing, and it prints how many files it copied instead of doing it silently.

Collision introduced: `web/install.sh:7` already uses `CLAY_HOME` to mean the
clone destination. Unresolved.

## Naming a workflow

A workflow can no longer be named by a path relative to a checkout, so
`clay/lib/paths.py` gained segment resolution:

```
clay run templates content quick-explainer
clay run workflows templates content quick-explainer
clay run workflows/templates/content/quick-explainer.json
clay run -f ./scratch/thing.json
```

Segments are searched under three roots — working directory, then
`$CLAY_HOME`/`~/.clay`, then the package — each tried with and without a
`workflows/` prefix. A checkout always beats an installed copy. `-f` names an
exact file and searches nowhere.

Both forms end at `workflow_at`, so a directory means its `main.json` and a
bare name finds its `.json` either way. Supplying both `-f` and segments is
rejected rather than resolved by precedence, because the two mean different
things and ignoring half of what was typed would be silent.

Applies to `run`, `dryrun`, `daemon run`. `daemon run` resolves before the
request crosses the wire — clayd does not share the caller's working directory.
`clay ui` resolves each argument separately, since each opens its own tab.
`lint` uses `resolve_tree`, which does not collapse a directory to its
`main.json`: linting a directory has to reach every file under it.

## `clay workflows`

New command listing what the segment form can find, grouped by root, printing
the reference to type rather than an absolute path. `--paths` adds the file,
and a positional term filters by substring.

Shadowing is reported here and nowhere else. A warning on every run of a
shadowed workflow is noise; someone reading this listing is looking for it.

## Exit codes now propagate

`cli()` is the console-script entry point, so its return value is the process
exit code — but `args.func(args)` discarded what subcommands returned, and
`clay.py:main()` discarded `cli()`'s. **Every failing command exited 0.**

Both now propagate. This is what lets an unresolved workflow name be reported
as a plain message rather than a traceback while still failing a script.

Worth watching on the next full test run: failure paths that were previously
swallowed now surface as non-zero exits.

## Install docs split out — `docs/INSTALL.md`

Install instructions live in one file now. `README.md` and `QUICKSTART.md` link
to it and carry none of their own.

**Windows is WSL2 only.** Native Windows is no longer documented as a path —
not as working, not as working-with-caveats. Under WSL2 clay is a Linux install
and the instructions are the Linux ones unchanged.

`INSTALL.md` also absorbed the **Where clay keeps things** and **Install path
status** sections from `QUICKSTART.md`, the latter recording what was verified
per platform with the file and line behind each failure: non-editable installs
(gopher's repo-root walk at `adapters/gopher.py:14-19`, plus `clay/data` not
declared as package data) and the curl one-liner, which does a non-editable
install and so inherits the first.

## `clay` is the only invocation

Every command in `QUICKSTART.md` is now `clay`, not `.venv/bin/clay`. The venv
never needed activating: `pip install -e .` writes `.venv/bin/clay` with an
absolute shebang naming the venv interpreter, so the script selects its own
Python from any shell. Only the *name* has to be reachable, so `INSTALL.md`
symlinks it into a directory already on `PATH` rather than putting `.venv/bin`
there and shadowing the system `python` and `pip`.

`python -m clay.cli` is now documented as **not** an entry point.
`clay/cli.py:847` has its `__main__` guard commented out, so that form imports
the module, calls nothing, and exits 0 while appearing to succeed —
`QUICKSTART.md` had advertised it as equivalent to `clay`. The console script is
unaffected: `pyproject.toml:18` binds `clay = "clay.cli:cli"` directly.

## Docs

`QUICKSTART.md` and `README.md` rewritten against what the code actually does.
`README.md` no longer advertises the `curl … | sh` one-liner as working, and its
`configs/default.json` and `workflows/templates/…` links point at the moved
locations. Implementation detail and roadmap notes were removed from it — it is
a user-facing document.

Every workflow reference used as an example in either document was checked to
resolve.

## Two path bases, and one rule each

`clay/lib/paths.py` was rewritten around the two questions clay actually asks,
which had been answered by four resolvers that disagreed.

**Where a workflow's assets are.** A workflow's `loadContext` file, its
sub-workflow, its loop body: found beside that workflow, or not at all. Nothing
is searched. The engine pushes the running workflow's directory onto a stack
(`paths.in_workflow`, popped in `finally`), and nesting works because a
sub-workflow's own `engine.run` pushes a frame of its own — so a loop body's
`./goal.json` is the loop body's, not its caller's.

This removes a real silent failure: the old resolver fell back to the process
directory, so a `goal.json` sitting in whatever directory clay happened to be
launched from would shadow the one the workflow shipped with, producing a run
that could not be reproduced anywhere else. It is now an error naming the
workflow directory that was searched.

`engine.run_from_data` pushes nothing, because JSON off the wire genuinely has
no directory. `loadContext` says so rather than reading out of wherever clayd
was started.

**Where clay works.** `paths.project_dir()` — the directory clay was started in,
fixed once at startup instead of read from the live cwd at call time. Symlinks
are followed, because `run/workspaces.py` follows them before deciding whether a
directory is approved; storing the unfollowed name meant clay could print one
path and check permission against another.

This fixes a daemon bug. `workspaces.DEFAULT_ROOT` is `'.'`, and clayd runs its
children with cwd set to clay's own checkout (`daemon/server.py:150`), so a
workflow with no explicit `root` was writing **into the program** instead of
into the caller's project. Relative roots now resolve against the project
directory (`workspaces._base_for`).

### `__workflow_dir__` is gone

The running workflow's directory used to travel as a reserved context key,
seeded into the result dict by the engine, re-extracted by the dispatcher,
passed as a `workflow_dir=` argument to three handlers, and stripped back out of
the result on the way home. All of it is deleted: `ENGINE_KEYS`, the seeding,
the strip, the dispatcher's `loadContext` special case (it is now dispatched
like any other handler), and the kwarg on each handler.

`engine.run` now requires a resolved file rather than accepting a name and
normalizing it. `paths.workflow_file` is public because `clay run -f PATH` asks
exactly that question about an exact path.

### Tests

`clay/tests/test_paths.py` rewritten: the project directory does not follow a
later `chdir`, a workflow's assets do not fall back to the process directory,
the stack unwinds when a workflow raises, and nested workflows each resolve
against their own directory.

`test_workflow_actions.py` was asserting that `engine.run` received the *bare
reference*, and one of its cleanup tests was passing vacuously — the handler
bailed before the call-stack set was ever touched. Both now run inside a real
workflow frame with files on disk.

The two `invalid_json_returns_none` tests were removed. They contradicted
`loadContext`'s actual contract: a file that does not parse as JSON loads as
text under the action's id, which is how prompts and training prose are read.
Replaced with tests for that behaviour.

---

## The repo-root `workflows/` folder is gone

Everything clay ships now lives under `clay/data/workflows/`. The checkout no
longer has a top-level `workflows/` directory, and nothing searches the
directory clay is run from.

| was | is |
| --- | --- |
| `workflows/registry/` | `clay/data/workflows/system/registry/` |
| `clay/data/workflows/registry/` | *(deleted — it was a second copy of the same generated tree)* |
| `workflows/test/` | `clay/data/workflows/test/` |
| `workflows/dev/` | `clay/data/workflows/dev/` |

Two copies of the registry tree existed because `clay build` wrote one into the
checkout root while seeding shipped another inside the package. There is one
now. It sits under `system/` with the rest of clay's own operating content,
because it is generated from the action schemas and has to move with the code
that generates it — a schema change and its example tree land in the same
commit.

For the same reason `workflows/registry` was dropped from `SEEDED_DIRS`. Seeding
copies once and never overwrites, so a seeded copy would have frozen the action
fields that existed on the day of install and gone on teaching them to an LLM
long after the schema changed.

**If you installed before this release**, `~/.clay/workflows/registry` is a
seeded copy that is now orphaned — it shadows nothing and will not be updated.
Delete it:

    rm -rf ~/.clay/workflows/registry

### `clay build` is a checkout-only command

It writes into the package. `clay/data` is read-only by contract on an
installed clay: a wheel may sit somewhere the user cannot write, and its
contents are replaced wholesale on upgrade, so anything written there would be
silently discarded. `clay build` now checks for write access up front and says
that plainly, rather than failing on a permission error three lines later.

### There is no workflow folder in a project directory

`clay lint` with no argument, `clay push` with no paths, `clay pull` with no
destination, and both UI surfaces used to look for a `workflows/` directory
beside wherever clay happened to be running, or walk up from `__file__` to find
the checkout. All five now call `paths.workflow_folder()` — `$CLAY_HOME/workflows`.

The UI had hardcoded `~/.clay/workflows`, which meant the UI and the CLI
disagreed about where a user's workflows live whenever `CLAY_HOME` was set.

### The system editor read its own tutorial through the wrong action

`system/editor/main.json` loaded `workflow/training.txt` with `readFile` and
`"root": "./workflows/system/editor/"`. `readFile` is a *project-file* action —
its `root` resolves against the project directory and never beside the workflow
— so this only ever worked because the process happened to be running from the
clay checkout. Removing the repo-root `workflows/` folder made it a dead path in
every case.

It is `loadContext` now, with no `root`. The file sits beside `main.json`, so it
resolves as the workflow asset it always was, and `loadContext`'s plaintext
fallback puts it under `tutorial` exactly as before.

The two are not interchangeable, and the distinction is the whole point of the
release: `loadContext` reads what ships *with* a workflow, `readFile` reads what
the user is *working on*.

### `clay workflows` no longer offers a heading it cannot fill

The listing looped over a `cwd` group labelled "In the working directory". That
folder stopped being a search root, so the branch was dead and the label
described something clay no longer does. The `--help` for every workflow
argument said the same thing and now names the two real folders.

---

## `--project-dir`, and the end of the daemon's borrowed directory

A workflow started through `clayd` now works in the directory the *caller* was
standing in. It used to work in clay's own install.

clayd is a long-lived process started from somewhere unrelated to anyone who
talks to it, and a subprocess does not inherit the cwd of a peer that merely
sent it a message. So the directory has to be sent. `DaemonClient` puts it on
every `start` and `start-json` request, the daemon passes it to the child as
`--project-dir`, and the child sets it once at startup.

`--project-dir` is a global flag on every clay command. Without it, the project
directory is the shell's cwd, exactly as before — nothing changes for `clay run`
typed by hand. It is repeated on `clay daemon run`, so it shows up in that
command's `-h`: that is the one place where the directory is a genuine question,
because the workflow runs under clayd rather than in your shell. The repeat is
declared with `default=argparse.SUPPRESS` so omitting it leaves whatever the
global flag parsed, instead of a subparser default overwriting it with `None`.

The client sends its own `paths.project_dir()` rather than reading `os.getcwd()`,
because a client is frequently *itself* running inside a workflow — the Telegram
bot is one — and that workflow already knows where it works.

**`project_dir` is not required on the wire.** A start request that omits it —
any client that is not the clay CLI — gets `$CLAY_HOME/workspaces` (default
`~/.clay/workspaces`), created on first use. What it never falls back to is the
daemon's own cwd: defaulting to *that* is what made a workflow with no explicit
`root` write into the program. A directory clay owns is a real answer; the
directory clayd happened to be launched from is not. An explicit `project_dir`
that is not a directory is still refused, with an error naming the path.

The fallback directory is created but **not approved**. Nothing grants itself a
workspace — a socket message must not be able to enlarge the register. If you
want unattended runs to work there, approve it once:

```
clay dirs add ~/.clay/workspaces
```

The child's `cwd` is now the project directory too, not clay's install. The two
are set together on purpose — an action that resolves a relative path through
clay and a shell command that resolves one itself must land in the same place.

### The unit suite stopped negotiating with the developer's approvals

`workspaces.load()` and `approve()` read and write `$CLAY_HOME/workspaces.json`.
Two test modules worked in `tempfile` directories without isolating that file,
so the suite consulted whatever the person running it happened to have approved:
on a machine that had never approved a temp directory it stopped dead on an
approval prompt, and on a machine that had, it quietly rewrote a real register.
A green suite on one machine was not a green suite on a fresh checkout, and CI
could not run it at all.

`test_file_ops.py` and `test_write_file_set.py` now use the fixture
`test_workspaces.py` already had: each test patches `REGISTER_PATH` to its own
temporary file and approves the directory it created. The register is kept in a
second temp directory rather than in the workspace, because `listWorkspace`
enumerates the workspace and would otherwise report the register as content.

## A coding agent that knows where it is: `system/coding3`

`clay run system coding3` starts a conversational agent that builds and edits a
real codebase in the project directory. Seven files under
`clay/data/workflows/system/coding3/`. It is a new template, not a revision of
`system/coding2`, and the four places it diverges are the interesting ones.

**It has no `workspace` setting.** Not one action names a `root`. An omitted
root is `DEFAULT_ROOT`, and `workspaces._base_for` resolves a relative root
against the project directory — so the agent's workspace *is* `--project-dir`,
authorized once, with nothing in between. The previous template threaded a
`{workspace}` placeholder holding `"./"` through every action and every prompt,
which resolved to the same place while looking like a setting.

**It reads the project before the first question.** Boot lists the directory,
reads whichever of eleven manifest files exist — `README.md`, `pyproject.toml`,
`package.json`, `Makefile` and so on — and spends one model call turning them
into a brief that every later turn receives: what the project is, its language,
its layout, and the command that runs its tests. The brief is built with
`serveFileReads`, not `readFile`, because a missing `README.md` through
`readFile` is an error on every boot, while `serveFileReads` returns
`(not found)` and moves on.

**Files are fetched from the plan, not from a tag.** After the thinking pass a
second, hidden call emits nothing but paths, one per line, and those go straight
into `serveFileReads`'s `pathsKey`. The writing pass therefore always has the
current contents of every file it is about to edit, without the model having to
remember a `<read_file>` tag — the older template's own prompt admits a tag sent
even one pass late "arrives too late to help this turn". A path that does not
exist yet comes back `(not found)`, which tells the writer the file is genuinely
new rather than something it is about to overwrite unseen.

**The review loop doubles as the repair path.** `applyFileWrites` refuses a
reply all-or-nothing when any fence fails to name its file: nothing lands, not
even the fences that were named correctly. Gating review on `files_written` —
which is what `system/coding2` does — skips review on exactly that turn. coding3
gates on whether the turn intended to write, and has the review pass read the
*planned* files off disk. A file the plan promised that comes back `(not found)`
is the signal that the write was refused, and the review prompt leads with it.

Two other shapes were built and rejected, both for reasons in the engine rather
than in taste: a retry loop around write-and-apply lints as broken because
`merge: true` publishes ids the linter's scope check cannot see, and a repair
action reusing `files_written` as its id deletes the good value on success,
because a skipped action pops its id from the store.

Known gap, not worked around: `runReplyCommands` takes no `cwd` here, so
commands run in the process working directory. That is right for `clay run` and
right under clayd, and wrong for `clay --project-dir X run …` issued from
somewhere else, where commands would run in the shell's directory while file
actions use `X`. The fix is `shell_actions` defaulting its `cwd` to
`paths.project_dir()`, which is a platform change rather than a template one.
