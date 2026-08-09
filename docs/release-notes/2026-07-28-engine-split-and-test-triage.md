# Release notes — engine split, config self-healing, test-suite triage

Date: 2026-07-28
Covers: commit `58c3261` (*first round of fixups MAJOR CLASS REVISION*),
commit `3badf2c` (*test suite fix round 1*), and the uncommitted round-2 test
fixes in the working tree.

---

## 1. Engine split — `clay/run/runWorkflow.py` removed (58c3261)

The 345-line `runWorkflow.py` was split by concern into three PEP 8-named
modules. **No compatibility façade** — every import site was updated.

| New module | Responsibility |
|---|---|
| `clay/run/engine.py` | Run orchestration: `run()`, `run_from_data()`, `dry_run()`, `process_steps()`, `load_file()`, private `_execute()` |
| `clay/run/dispatcher.py` | Per-action validation, routing, logging. `_HANDLERS` dict of direct function references for the ~27 uniform `(action, ctx)` handlers; explicit branches for the 6 non-uniform types (`humanDecision`, `workflow`, `loop`, `humanShell`, `loadContext`, `scramda2`) |
| `clay/run/cancellation.py` | `request_cancel()` / `clear_cancel()` / `is_cancelled()`, moved verbatim |

### Breaking changes (internal API)

- `from clay.run import runWorkflow` → `from clay.run import engine`
- `runWorkflow.loadFile` → `engine.load_file`; `runWorkflow.dryrun` → `engine.dry_run`
- Cancellation moved: `runWorkflow.request_cancel()` → `cancellation.request_cancel()`
- Engine flags are keyword-only: `run(filename, initial_data=None, *, auto=False, daemon=False)`
- The dead `model=` parameter thread was deleted end-to-end (`run` →
  `_execute` → `process_steps` → `process_action` never read it), including
  the always-`None` `model` params on `workflow_actions.handler` and
  `loop_actions.handler`. Partially addresses the model half of
  [F-16](../bugs/F-16-model-daemon-not-propagated.md).

### Dead code removed

Unused `import requests`, `RESERVED_KEYS` import, `_PREVIEW_CHARS`, and the
dead `file_actions` import (its only use was commented out).

### Deliberately not built (design audit)

No `ActionDispatcher`/`CancelToken` classes (zero instance state), no
`RunOptions` dataclass or adapter-lambda layer, no public `process_action`
shim. The audit criterion: remove abstraction, never add it.

Details: [docs/tasks/split-runworkflow-into-engine.md](../tasks/completed/split-runworkflow-into-engine.md)

---

## 2. Config self-healing (3badf2c)

`create_user_config()` (clay/lib/config.py) is the single routine:

- **Missing** `~/.clay/config.json` → created from the baked-in
  `configs/default.json` (pre-existing behavior)
- **Corrupt / not a JSON object** → stdout message
  `config: … is corrupt — recreating from defaults` + rewrite from defaults
- **Valid** → untouched

`load_config()` now calls `create_user_config()` before its (unchanged) read,
so every entry point — CLI, API, tests — gets the real defaults. The silent
`{}` fallback for a missing config is gone. Covered by
`TestLoadConfigSelfHealing` (missing / corrupt / non-object / valid-untouched).

---

## 3. Debug prints removed (3badf2c)

- `engine.process_steps`: the 4 action-loop demo prints — they leaked
  humanDecision/scramda2 answers into stdout, breaking the two no-leak
  guarantee tests. Fixes [F-03](../bugs/completed/F-03-debug-prints-in-action-loop.md).
- `scramda2_actions`: resolved-prompt and models prints (full prompts dumped
  on every AI call).
- `adapters/gopher.py`: prompt/examples prints, which also sat **above**
  `fire`'s docstring — `fire.__doc__` was broken and is now restored. Fixes
  [F-25](../bugs/completed/F-25-gopher-debug-prints-dead-docstring.md).

---

## 4. termui: no more import-time drawing (3badf2c)

Importing `clay.run.termui` (and therefore the engine) no longer fires the
intro animation thread. `termui.intro()` is explicit; `clay run` calls it
after `set_plain`. The Qt UI path never imports termui (verified) and is
unaffected. Terminal-output tests force `set_plain(True)` in `setUpModule` so
results don't depend on running from a TTY (`IS_TTY` is frozen at import;
rich mode uses themed `═`×52 banners vs plain `═`×56).

---

## 5. Test tooling (3badf2c)

`python3 -m clay.tests` (`clay/tests/__main__.py`): identical to
`python3 -m unittest discover -s clay/tests -t .` plus a compact
`Failed tests (N)` list at the bottom — one line per failure/error with the
test id and final traceback line. Stock loader/runner, no subclasses.

---

## 6. Test triage round 1 (3badf2c)

All failures traced by reading code — none were caused by the engine split.

- **test_training paths (33)** — `workflows/research-doc/` moved to
  `workflows/templates/research/`; constants updated, plus the loadContext
  assertion (pipelines reference `../training.json` relative to their dir).
- **test_load_config (3)** — patched the nonexistent `clay.cli._read_json`;
  rewritten against real files + the self-healing behavior.
- **test_run_from_data (3)** — asserted `body["prompt"]`; gopher sends
  OpenAI-style `messages`, assertions now join `messages[].content`.

Details: [docs/tasks/test-suite-triage.md](../tasks/completed/test-suite-triage.md)

---

## 7. Test triage round 2 (working tree, uncommitted)

- **test_training format/wiring (14)** — training.json values changed from
  `"Example\nInput:…Output:…"` strings to lists of
  `{"question", "answer"}` few-shot dicts, consumed by scramda2 via
  `"examples": {"override": "training_key"}`. Structure tests rewritten for
  the list format; the prompt-substitution class replaced by
  `TestTrainingExamplesWiring` (override resolution through
  `dispatcher._resolve_action_fields`); pipeline assertions now require the
  examples override and no longer expect training keys in `includedData`.
- **test_scramda2 model tests (2)** — the handler reads models from
  `lib.config.get_models()` (not ctx `__config__`), and the self-healed
  config always supplies a default model. Tests patch `get_models`; a new
  test pins the config-default fallback.
- **test_run_from_data mocks (2)** — mock response updated to the
  OpenAI-compatible shape (`choices[0].message.content`).
- **`TestRunJsonSeedsConfig` (2) — deleted.** `run_json` intentionally does
  not seed `_load_config()`: scramda2 reads config directly from the config
  file now. This supersedes [F-19](../bugs/completed/F-19-runjson-missing-config-seed.md)
  (closed by design decision, not by re-adding the seed).

## Open items

- **Vestigial `{training_*}` placeholders** in the three research pipeline
  prompts: the keys aren't in `includedData`, so the literal placeholder text
  reaches the model; `test_each_scramda2_prompt_contains_training_template_variable`
  still enforces their presence. Awaiting decision to strip them.
- [F-01](../bugs/completed/F-01-telegram-import-crash.md): `telegram_actions` reads
  `TELEGRAM_BOT_TOKEN` at import — without it, all 16 engine-importing test
  modules error at collection.
- `cli.ACTION_TYPES` drift ([F-05](../bugs/F-05-action-list-drift.md)).
