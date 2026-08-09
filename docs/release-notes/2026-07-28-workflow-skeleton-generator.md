# Release notes — deterministic workflow skeleton generator

Date: 2026-07-28
Covers everything since
[2026-07-28-registry-annotations-single-source.md](2026-07-28-registry-annotations-single-source.md)
(committed in `27efe0d`), so there is no gap in the record:

- `f62e046` ("fix linter") — already fully described in that prior file's
  item 5 (lint `report()` listing every file, `--verbose` removal). No new
  content to add here; listed only for continuity.
- `27efe0d` ("updated docs") — committed `QUICKSTART.md`,
  `docs/plans/redesign/current.puml`, the prior release-notes file itself,
  and the `registry-annotations-single-source.md` status update. Docs-only,
  no code change; not separately release-noted at the time.
- Everything below this line is **new, currently uncommitted** work
  (`git diff --stat HEAD` against `27efe0d`) implementing
  [workflow-skeleton-generator.md](../tasks/completed/workflow-skeleton-generator.md),
  the task queued immediately after registry-annotations-single-source.

---

## 1. `skeleton=False` flagged on 27 of 33 registered action types

Every `@action(...)` / `@_action_decorator(...)` call for a type that should
**not** appear in the generated example tree now carries `skeleton=False`:
`API`, `browseWeb`, `createAgentAction`, `deriveTags`, `humanShell`,
`listMemory`, `listSites`, `listSkills`, `loadContext`, `loadSite`, `mongo`,
`python`, `readMemory`, `removeSkill`, `report`, `runCode`, `searchMemory`,
`searchSkills`, `searchWeb`, `sendAlert`, `sendEmail`, `shell`, `telegram`,
`transformData`, `writeCode`, `writeMemory`, `writeSkill`.

The remaining 6 keep the `skeleton=True` default: `humanDecision`, `loop`,
`readFile`, `scramda2`, `workflow`, `writeFile`. `clay/actions/registry.py`
itself was not touched — the flag mechanism (`req()`/`opt()`/`@action`
accepting `skeleton=`) was already in place from the prior task.

## 2. New module: `clay/actions/skeleton.py`

`WorkflowSkeleton` builds an example workflow tree directly from the live
registry:

- `action(type_name) -> dict` — one fully-instrumented action. Required
  fields, and optional fields whose declared default is `None`, render a
  type marker (`"<string>"`, `"<integer>"`, ...); optional fields with a
  non-`None` default render that literal default. Field order follows
  `dataclasses.fields()` declaration order, with `id` always emitted first
  and `type` inserted immediately after it, matching every real workflow
  JSON file in the repo (verified by reading precedent, not assumed).
- `build() -> dict[str, dict]` — the 5-file tree as parsed documents.
- `write(dest) -> list[str]` — writes the tree to `dest` (`indent=2`,
  trailing newline), returns the paths written.

No values are invented for fields the registry can't derive semantics for
(a `content` key name vs. a `file` path both type as `str` — see the task
doc's rationale). The tree is a format shell, not a runnable example.

## 3. Generated tree: `workflows/registry/`

Five files, composed from two real precedents named directly by the user
(`workflows/templates/research/main.json` and `workflows/system/editor`),
not invented from scratch:

| File | Demonstrates |
|---|---|
| `main.json` | `autoContext`, `workflow.steps`, `actionSets`, `loadContext` of `goal.json`/`context.json`/`training.json`, a `humanDecision` action, a `loop` into `iteration.json` with `includedData` |
| `iteration.json` | the loop body — `readFile` → `scramda2` (with `examples: {"override": "training_example"}`) → `writeFile` → `humanDecision` → `workflow`, one actionSet per step |
| `goal.json` / `context.json` | flat key/value context files loaded via `loadContext` |
| `training.json` | a few-shot array addressed by `"examples": {"override": "training_example"}` |

Design points settled by direct user decision during this task (not
inferred):

- `training.json` is loaded once in `main.json`, then its key flows into
  `iteration.json` via the loop action's `includedData` — diverging from
  the literal `research/pipelines/research.json` precedent, which colocates
  the `loadContext` with the `override` usage in the same file.
- `core_io` was split into two purpose-named actionSets, `read_input` and
  `write_output`, with `write_output` sequenced *after* `scramda2_actions`
  in `workflow.steps` (the write depends on the `scramda2` result).
- No separate `loop_actions` actionSet — the `main.json` → `iteration.json`
  loop call already serves as the loop example.
- Both `humanDecision` actions (`focus` in `main.json`,
  `human_decision_response` in `iteration.json`) carry instructional
  placeholder text in `prompt` ("Enter the prompt to show a human, or to
  send to the AI when running in `--auto` mode.") rather than a fabricated
  example question — teaching that this field doubles as the AI's prompt
  in `--auto` mode, without asserting a fake scenario.

## 4. `clay build` regenerates `workflows/registry/`

`clay/cli.py`'s `build(args)` now calls `WorkflowSkeleton().write(...)` in
addition to `app_config.rebuild_schema()`, and prints a line for each. This
had been decided earlier in the task but was not actually wired up until
the user ran `clay build` themselves and caught that it only rebuilt
`schema.json`.

## 5. Validation

- `.venv/bin/python -m clay.lint workflows/registry` — user ran directly;
  5 files, 5 clean, 0 errors, 0 warnings.
- New test file `clay/tests/actions/test_skeleton.py`:
  - `TestWorkflowSkeletonStaleness` — asserts the committed tree on disk
    equals a fresh `WorkflowSkeleton().build()`, and that the file set
    matches exactly (no extra/missing files). Makes staleness a test
    failure rather than silent rot, per the task doc's explicit
    requirement.
  - `TestWorkflowSkeletonValidation` — every action's `type` is present in
    `_REGISTRY`; every action passes `registry.validate()`; `clay.lint`'s
    `lint_dir()` (the same cross-file, includedData-scope-aware machinery
    `clay lint` runs) reports zero errors and zero warnings for the tree.

Command for the user to run directly:
`.venv/bin/python -m unittest clay.tests.actions.test_skeleton -v`

## Size

Current `{__schema__}` injection is ~7,223 tokens (28,894 chars). The built
`workflows/registry/` tree measures 3,239 chars across 5 files (`wc -c`) —
~810 tokens at the same chars-per-token ratio, roughly a 9x reduction.

## What's not done

- The six `{__schema__}` injection sites (`system/editor/iteration.json`
  ×4, `system/coding/iteration.json`, `dev/system/editor/iteration.json`)
  have not been swapped to reference the new tree — explicitly out of
  scope for this task per the task doc; a separate, reviewable change.
- Nothing from this section (Task 2) has been committed to git this
  session.
- The task doc's validation checklist names a `DEMO_ACTIONS` entry check;
  no literal `DEMO_ACTIONS` list exists in the implementation. The
  equivalent invariant (every emitted `type` is a real registry key) is
  enforced structurally — `action()` does a `_REGISTRY[type_name]` lookup
  that raises `KeyError` on an unknown type — and covered by
  `test_every_action_type_is_registered`. Flagged to the user; task doc
  wording not changed without confirmation.
