# 2026-08-09 — `startup.json` is yours to edit

## Fixed

### Which workflow bare `clay` starts was fixed at build time

`load_startup()` read `clay/data/configs/startup.json` from inside the
installed package and nowhere else. `_DATA_DIR` is derived from `__file__`, so
on a release that path resolves under
`<release>/venv/lib/python3.11/site-packages/clay/data` — meaning the value was
whatever the archive was built with, and the only way to change it was to edit
a file inside `site-packages`.

That is not theoretical. `9bd63f9` changed `user` from
`workflows/system/clay/main.json` to `workflows/system/coding/main.json` after
the installed 0.1.0 archive was built, so the repository and the installation
disagreed with no supported way to reconcile them.

Packaging was never the cause — `startup.json` is already whitelisted in all
three places that decide what ships: `pyproject.toml:51` (wheel),
`pyproject.toml:79` (source archive), and
`scripts/git_release/publish.py:94` (public repo).

`startup.json` is stored beside `config.json`. The packaged copy supplies its
initial value; explicit user selections in `~/.clay/startup.json` are
authoritative:

- `_STARTUP_PATH` names the user's copy, beside `config.json` and
  `schema.json`; `_BASE_STARTUP_PATH` names the packaged one.
- `create_user_startup()` copies it in with `open(..., "xb")` — create-or-fail,
  the idiom `create_user_config()` uses, so concurrent starts cannot race. The
  current implementation advances versioned managed defaults on upgrade while
  preserving explicit user choices. A file that will not parse, or that is not
  a dict, is recreated and says so on stdout.
- `load_startup()` falls back to the packaged copy only when the user directory
  could not be written, so an installed clay on a read-only home still starts
  something rather than nothing.

To change what bare `clay` starts, edit `~/.clay/startup.json`. No rebuild.

### Not added to `SEEDED_DIRS`

`seed_user_dir()` walks its entries as directories — it calls `os.makedirs` on
the destination before testing `os.path.isdir(source)` — so a file entry would
create a directory named `startup.json` and copy nothing.

`workflows/system` remains unseeded. The reasoning at `config.py:44-59` is
what made this bug recoverable: clay's own operating logic has to update with
the program, while which workflow starts is a user preference.

## Tests

- `clay/tests/lib/test_startup_config.py` — new: the packaged copy is seeded on
  first read, the user's copy wins, an upgrade does not revert it, a corrupt or
  non-dict user copy is recreated from the package, a read-only home still
  resolves a workflow, and nothing readable anywhere returns `{}`. Path
  assertions pin the user copy beside `config.json` and the packaged copy to
  `data/configs/startup.json`.

Run: `.venv/bin/python -m clay.tests`

## Documentation

- `docs/tasks/startup-json-user-copy.md` — new: the report, the traced cause,
  the change, and why `SEEDED_DIRS` was not the mechanism.
