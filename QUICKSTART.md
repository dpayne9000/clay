# Quickstart

Common commands for working in this repo. Run them from `platformCli/`.

Everything below is the `clay` command. Installing it, and getting that name
onto your `PATH`, is covered once in **[docs/INSTALL.md](docs/INSTALL.md)** —
including where clay keeps its files and which install paths do not work yet.

## Telegram remote control

Go to @botfather in telegram and ask for a new token

export TELEGRAM_ALLOWED_CHATS=
export TELEGRAM_BOT_TOKEN=""
clay daemon run workflows/system/messaging/telegram.json --project-dir ~/.clay/workspaces/default

then, in telegram, you can chat directly with your LLM, or use the /start command
to run any of the predefined workflows in $CLAY_HOME/data/workflows/system/messaging/telegram.json


## Naming a workflow

Every command that takes a workflow takes it the same way.

```
clay workflows                        # list everything findable
clay workflows research               # filter by substring
clay workflows --paths                # show the file each resolves to
```

The reference printed by `clay workflows` is what you type back:

```
clay run templates content quick-explainer
clay run system coding2
```

Segments are searched under three roots, in this order — working directory,
then `$CLAY_HOME`/`~/.clay`, then the package. A checkout always wins over an
installed copy. Each root is tried with and without a `workflows/` prefix, so
`clay run workflows templates research` and `clay run templates research` are
the same thing, and a whole path as one argument still works:

```
clay run workflows/templates/content/quick-explainer.json
```

To skip the search entirely, name the file with `-f`:

```
clay run -f ./scratch/thing.json
clay run -f ./clay/data/workflows/templates/research   # main.json inside
```

A directory means the `main.json` inside it, and a name without an extension
finds its `.json` — both forms behave identically on that. Giving both `-f`
and segments is rejected rather than guessed at.

## Run a workflow

```
clay run templates content quick-explainer
clay run templates content quick-explainer --auto   # AI answers humanDecision steps
clay dryrun templates content quick-explainer       # validate without executing
```

Commands return real exit codes: an unresolved name or a lint failure exits
non-zero, so `clay run x && something-else` behaves.

## Rebuild the action registry cache

Action schemas live next to their handlers (e.g.
`clay/actions/core/write_file.py`), not in one file. `clay/lib/config.py`
caches the combined JSON Schema to `$CLAY_HOME/schema.json` so it isn't
recomputed on every run — that cache is what gets fed into model prompts as
`__schema__`.

**If you add, remove, or change the fields on any `@action` class, run this
before testing that change** — nothing else regenerates the cache for you:

```
clay build
```

This force-reruns discovery and overwrites `schema.json`. Without it,
`clay run` / `clay run-json` will keep using the stale cached schema.

## Lint workflow JSON

```
clay lint                 # lints workflows/ in the current directory
clay lint path/to/dir     # lint a specific directory or file
clay lint templates       # lint a whole subtree by segments
```

Lint acts on a subtree, so a directory is linted whole rather than collapsed
to its `main.json`. An existing path on disk always wins over a search hit.

Prints one line per file checked (`✓` clean, `△` warnings, `✗` errors),
followed by a summary. Exit code is `0` if nothing errored, `1` otherwise.

## Regenerate the action reference docs

```
clay docs
```

Writes `docs/documentation/action-reference.json` and `.html` from the
current registry. Checkout-only — it writes into the repo.

## Run tests

```
.venv/bin/python -m clay.tests                              # whole suite
.venv/bin/python -m unittest clay.tests.test_lint -v        # one module
```

Use `.venv/bin/python`. A pyenv shim on `PATH` lacks this project's
dependencies and breaks action discovery.

## Daemon

```
clay daemon start
clay daemon status
clay daemon list
clay daemon run templates content quick-explainer
```

`daemon run` takes the same segment and `-f` forms as `clay run`, and resolves
the reference before sending it — clayd does not share your working directory.
