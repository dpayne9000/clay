# Release notes — workflow prompt cleanup, registry accuracy, lint unknown-field detection

Date: 2026-07-28
Covers: commit `467e1ef` (*test fixes and release notes*), commit `a893aaa`
(*removed fewshot templates from some workflow prompts*), and the uncommitted
lint/registry work in the working tree.

Supersedes nothing; continues from
[2026-07-28-engine-split-and-test-triage.md](2026-07-28-engine-split-and-test-triage.md).

---

## 1. Dead training placeholders removed from research prompts (a893aaa)

13 `{training_*}` placeholders were stripped from the tails of scramda2 prompts
in `workflows/templates/research/pipelines/` — `research.json` (5),
`draft-document.json` (6), `review.json` (2).

**Why they were broken.** Traced end to end:

1. `load_training` (`loadContext`) merges `training.json` into `step_output`.
2. [dispatcher.py:154](../../clay/run/dispatcher.py#L154) resolves
   `"examples": {"override": "training_x"}` to the real few-shot list — this
   half always worked.
3. [dispatcher.py:176](../../clay/run/dispatcher.py#L176) builds ctx via
   `build_ctx`. These actions declare `includedData`, so
   [context.py:44-56](../../clay/lib/context.py#L44-L56) returns **only** the
   listed keys — the training key is not among them.
4. [scramda2_actions.py:16](../../clay/actions/scramda2_actions.py#L16) runs
   `prompt.format_map(_SafeMap(ctx))`; `_SafeMap.__missing__` re-wraps the key
   in braces.

Result: the literal string `{training_generate_queries}` was sent to the model
as the final line of the prompt — the highest-salience position — on every one
of those 13 calls. It failed silently by design: `_SafeMap.__missing__` never
raises, and unlike a missing `{"override": ...}` key (which does
`logger.warn` at [dispatcher.py:124](../../clay/run/dispatcher.py#L124)) an
unresolved prompt placeholder produced no error, no warning, no log line.

**Confirmed there is no duplicate-injection path.** Few-shot examples travel as
a separate `fewshot_examples` argument
([adapters/gopher.py:63-69](../../clay/adapters/gopher.py#L63-L69)) and are
inserted as their own message objects by
[fewshot.py:61-65](../../connectors/gopher/gopher/fewshot.py#L61-L65). Nothing
in the codebase stringifies examples into prompt text.

`test_each_scramda2_prompt_contains_training_template_variable` — which
*enforced* the leftover — was removed.

### Left in place deliberately

19 placeholders in other trees, untouched:

- `workflows/templates/debug/research/` (13) — a copy of the pipelines,
  overrides present, same dead-text situation.
- `shared/research/web-research.json` (3) and
  `skunkworks/domain-translator/main.json` (3) — these have **no**
  `"override"` entries at all. The placeholders are the only training
  reference in those files, so they are unfinished wiring, not vestigial
  text. Stripping them would delete intent.

---

## 2. Registry accuracy: readFile and writeFile

Both are recent additions whose schemas had not caught up.

- **`readFile` added.** It was routable at
  [dispatcher.py:50](../../clay/run/dispatcher.py#L50) but missing from
  `_REGISTRY` — the only one of 32 routable types absent. Consequences: lint
  reported `unknown action type 'readFile'` and skipped validation for those
  actions entirely, and the action did not appear in `__schema__`, so any
  model generating workflows from the schema had no way to know it exists.
  Fields mirror [core/read_file.py](../../clay/actions/core/read_file.py):
  `id`, `file`, `root` (default `"output"`), `encoding`, `maxBytes`.
- **`writeFile` completed.** The handler reads seven fields the schema never
  declared — `root`, `encoding`, `append`, `createParent`, `stripCodeFence`,
  `requireCodeFence`, `ensureFinalNewline`
  ([core/write_file.py](../../clay/actions/core/write_file.py)).

All additions are `opt()`, which can never produce a validation error. No
`req()` field was added to an existing type — that would break every workflow
missing it. No broader handler-vs-schema drift sweep was performed; these two
were the only recent additions.

### `__schema__` note

The direct `export_json()` imports in [clay/cli.py](../../clay/cli.py) and
[clay/lib/config.py](../../clay/lib/config.py) stay as they are. A note above
`export_json()` records that the payload needs formatting work later: it is raw
JSON Schema (~27k chars / ~6.7k tokens) and is pulled into model prompts by
`workflows/system/editor/iteration.json`, `system/coding/iteration.json` and
`dev/system/editor/iteration.json`, so every field added here grows those
prompts.

---

## 3. `clay lint`: undeclared action fields

**The gap.** `registry.validate()` iterates the *schema's required fields* and
asks whether each is present in the action. It never iterates the action's own
keys. So validation was one-directional: omitting a required field was caught
(lint, and at runtime by [dispatcher.py:158](../../clay/run/dispatcher.py#L158)),
while adding a field that isn't real was silent everywhere. Handlers read what
they want via `action.get(...)`; anything else in the dict is never read.

**The check.** Each action's keys are diffed against its schema's declared
fields. Undeclared names are reported as **warnings**, listing the type's real
field names. Always allowed: `type`, `includedData` (555 uses, consumed by
`build_ctx`), and underscore-prefixed keys (`_comment`, 69 uses).

Deliberate limits:

- **Name-level only** — `"timeout": "banana"` still passes. Value types and
  ranges are not validated.
- **Per-action-type** — `queryKey` is real on `searchWeb` and passes there;
  `urlKey` on `browseWeb` is flagged.
- **Warning, never error** — the emitted JSON Schema declares
  `"additionalProperties": true`
  ([registry.py:340](../../clay/actions/registry.py#L340)), and warning level
  means a stale schema produces noise rather than a broken build.
- No new dependency. Detection is a set difference; `dataclasses.fields` was
  the only import added.

### Findings on the current workflows

47 undeclared field usages, all silently ignored at runtime today. **Reported
only — no workflow JSON was modified.**

| Field | Uses | Handler actually reads |
|---|---|---|
| `loadContext.key` | 24 | only `file` + `id` |
| `writeMemory.tags` | 15 | `tagsKey` |
| `browseWeb.urlKey` | 4 | `url` |
| `shell.cwd` | 2 | `command`, `timeout` |
| `scramda2.maxTokens` | 2 | `max_tokens` |

`shell.cwd` is the one worth a look: those commands run in the process working
directory, not the one the JSON names. Deciding what to do about any of these
is separate work — note that making `maxTokens` or `cwd` match the handler
would *activate* a dormant parameter and change how those workflows run, so it
is a behaviour change rather than a cleanup.

### Reporter

`report()` now ends with a flat, greppable findings list — `Errors (N)` then
`Warnings (N)`, one line per issue with the file path — after the existing
grouped per-file output and totals. Nothing aborts early; the report always
runs to completion. Mirrors the `Failed tests (N)` block on
`python3 -m clay.tests`.

### Corrected documentation

The `clay/lint.py` module docstring claimed "Actions with a 'file' field
reference a path that exists on disk". No such check exists in `_lint_workflow`
— `_resolve_file_ref` is used only for scope analysis. That line was replaced
with an accurate description of the new field check.

---

## 4. Tests

`TestUnknownFieldDetection` added to `clay/tests/test_lint.py` (12 tests):
undeclared field warns; warning lists valid names; never an error; declared
optional field is clean; case mismatch (`maxTokens`) caught and `max_tokens`
accepted; `includedData` and `_`-prefixed keys never flagged; unknown action
type produces no field warnings; multiple undeclared fields each warn; and
regression guards pinning the full `readFile` and `writeFile` field sets.

Previous coverage was `includedData` scope only (17 tests, 3 classes).

## Commands

```bash
python3 -m clay.tests                      # full suite + failure list
python3 -m unittest clay.tests.test_lint -v   # lint tests only
clay lint workflows                        # full report + findings list
clay lint workflows/templates/research     # single folder
```

## Open

- End-to-end workflow data-flow contract test suite (`engine.run` layer,
  covering scramda2 / humanDecision / readFile / writeFile wiring) — requested,
  sequenced after the lint work, not started.
- [F-01](../bugs/completed/F-01-telegram-import-crash.md) was then open: `telegram_actions`
  reads `TELEGRAM_BOT_TOKEN` at import, so 16 engine-importing test modules
  error at collection. `clay lint` is unaffected — it imports no handlers.
