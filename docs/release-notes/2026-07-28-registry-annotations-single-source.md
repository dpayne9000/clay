# Release notes — registry annotations as single source of truth

Date: 2026-07-28
Covers: commits `5517522` (*action registry rework 1*), `06f5167` (*action
registrry cleanup 2*), and the currently staged lint-output change in the
working tree.

Implements
[registry-annotations-single-source.md](../tasks/completed/registry-annotations-single-source.md).
Continues from
[2026-07-28-lint-unknown-fields.md](2026-07-28-lint-unknown-fields.md).

---

## 1. Schemas moved off `registry.py` onto their handler modules

Each action's dataclass schema (`@action('type')` + `req()`/`opt()` fields)
now lives on the same module as the `@handler_for('type')` function that
reads it, instead of being declared centrally in `registry.py`. `registry.py`
dropped from 465 lines to 212 and now holds only the decorator mechanism —
`_REGISTRY`, `validate()`, `export_json()`, `discover()` — no per-action data.

This closes the exact bug class the lint unknown-field work
([2026-07-28-lint-unknown-fields.md](2026-07-28-lint-unknown-fields.md)) had
to patch by hand:

- `readFile` had a handler (`_HANDLERS`) but no schema (`_REGISTRY`) — lint
  reported "unknown action type" and it never appeared in `__schema__`.
- `writeFile` declared 3 of its 10 real fields; the other 7
  (`root`, `encoding`, `append`, `createParent`, `stripCodeFence`,
  `requireCodeFence`, `ensureFinalNewline`) were read by the handler but
  invisible to validation and to the manifest.

Both are now structurally impossible: `@action` and `@handler_for` write into
the same registry entry, so a type with one and not the other is a
first-class condition, not a coincidence of two hand-maintained lists staying
in sync.

## 2. `_HANDLERS` deleted; discovery walks the package instead of an import list

`dispatcher.py`'s hand-written 26-line import block (one line per action
module) is gone. `registry.discover()` walks `clay.actions` with
`pkgutil.walk_packages` in sorted module-name order and imports each module,
which fires its `@action`/`@handler_for` decorators as a side effect.
Six types (`scramda2`, `humanDecision`, `workflow`, `loop`, `humanShell`,
`loadContext`) keep explicit branches in `dispatch()` because they take extra
engine arguments (`auto`, `workflow_dir`, etc.), not because they need a
separate lookup table — those branches now resolve their callable through the
registry like everything else.

**Invariant test added** — `clay/tests/actions/test_registry.py`:
- every type in `_REGISTRY` has a handler in `_HANDLERS`, and vice versa
  (the `readFile` failure mode, asserted in both directions)
- every non-special type is actually routable through `dispatch()`
- the six special types are present in the registry
- repeated `discover()` calls produce the same registration order
- registration order matches sorted module-name order

## 3. Three sibling-module-import bugs found and fixed

`discover()`'s sorted-order guarantee only holds if action modules don't
import each other at module scope — an eager top-level import registers the
imported module's types early, ahead of its alphabetical position. Found by
tracing an actual order-mismatch failure, not by inspection:

- `alert_actions.py` imported `email_actions` at the top for
  `_send_email_alert`. Moved the import into that function.
- `skill_actions.py` imported `tag_actions` at the top for two handlers
  (`listSkills`, `searchSkills`). Moved into each function.
- `memory_actions.py` imported `tag_actions` and `skill_actions` at the top
  for `writeMemory`. Moved into that function.

All three now import their sibling lazily, inside the function that uses it.
Verified in real `clay` usage that registration order across all 33 types is
now genuinely alphabetical by module (`mods == sorted(mods)` → `True`).

## 4. Schema caching: `clay build`, and a pre-existing double-encoding bug

Previously every `clay` invocation re-ran `discover()` and re-serialized the
full schema on every process start via `cli.py`'s `_load_config()`. That's
now split into two things that don't need to happen at the same cadence:

- `discover()` populating live `_HANDLERS`/`_REGISTRY` — must run once per
  process, can't be cached (handlers are function objects).
- The JSON Schema text fed into `__schema__` / model prompts — pure data,
  now cached to `~/.clay/schema.json` and only regenerated on demand.

`_load_config()` now reads the cached file via `lib.config.load_schema()`
instead of recomputing it. A new `clay build` subcommand (registered ahead of
`lint` in the CLI) calls `lib.config.rebuild_schema()`, which force-reruns
`discover()` and overwrites `~/.clay/schema.json`. Anyone who changes an
action's fields needs to run `clay build` for the manifest to pick it up —
that ordering (edit → rebuild → use) is manual, not automatic.

While wiring this up, found and fixed a pre-existing bug in
`create_user_config()`: it called
`json.dump(_schema_json(), f, indent=4)`, but `_schema_json()`
(`export_json()`) already returns a JSON string via `json.dumps(...)` —
wrapping it in `json.dump()` again double-encoded it into an escaped string
literal. Confirmed empirically: loading `~/.clay/schema.json` back with
`json.load()` returned a Python `str`, not a `dict`. Fixed to write the
string directly (`f.write(_schema_json())`).

The five `discover()` call sites were collapsed to the minimum needed:
`dispatcher.py` (the real owner — first thing `cli.py` imports) keeps its
call; `lint.py` and `lib/config.py` keep theirs because both are used
standalone (e.g. by `test_lint.py`) without going through `cli.py`, so each
must be able to trigger discovery on its own; the redundant call in `cli.py`'s
`docs()` was removed.

## 5. Lint now lists every file it checks, clean or not

`clay/lint.py`'s `report()` previously only printed a per-file line for files
with errors or warnings, unless `--verbose`/`-v` was passed. A fully clean run
against a large tree therefore produced a single easy-to-miss summary line
(`148 files · 148 clean · 0 with errors`) and looked like nothing had run.
`report()` now always prints one line per file (`✓`/`△`/`✗` + role), followed
by the summary. The now-meaningless `--verbose`/`-v` flag was removed from
both `clay/lint.py`'s `main()` and `clay/cli.py`'s `parser_lint` rather than
left in place as a no-op.

## 6. Verification

- `.venv/bin/python3 -m unittest clay.tests.actions.test_registry -v` — user
  ran directly; passes.
- `docs/documentation/action-reference.json` regenerated via `clay docs`;
  diffed against the pre-move baseline — identical type set, zero schema
  differences across all types.
- `.venv/bin/python3 -m clay.cli lint workflows` — user ran directly; now
  lists all 148 files with role and status, exits 0 on a clean tree.

## What's not done

`docs/plans/redesign/current.puml` has not been updated to reflect the schema
relocation. Not yet raised with the user.
