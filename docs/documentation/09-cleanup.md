# 09 — Cleanup / Old Paradigms — Consolidated Findings

This document consolidates cleanup observations from across the codebase. No
code changes are made here — this is a reference for future refactoring.

> **Bug-class items have moved to [`docs/bugs/`](../bugs/README.md).**
>
> Everything here that was a *defect* — something with a wrong behaviour and a
> fix — is now a spec file under `docs/bugs/`, so it can carry a status and be
> closed. What remains below is the other half: naming, structure and paradigm
> observations that describe how the code is shaped rather than what is broken
> about it. Those have no "fix" to track; they are input to the redesign in
> [`docs/plans/redesign/`](../plans/redesign/plan.md).
>
> | Moved from this document | Now at |
> | --- | --- |
> | Unused theme feature flags | [F-22](../bugs/F-22-assorted-hygiene.md) §22.10 |
> | `startup_banner` plain/rich width mismatch | [F-22](../bugs/F-22-assorted-hygiene.md) §22.11 |
> | `RESERVED_KEYS` is empty | [F-21](../bugs/completed/F-21-reserved-keys-empty.md) |
> | `pymongo` soft import | [F-22](../bugs/F-22-assorted-hygiene.md) §22.16 |
> | `workflow_actions` `model` parameter never populated | [F-16](../bugs/F-16-model-daemon-not-propagated.md) |
> | `logger.trace()` unused | [F-22](../bugs/F-22-assorted-hygiene.md) §22.9 |
> | `run_from_data` missing `daemon` param | [F-16](../bugs/F-16-model-daemon-not-propagated.md) |
> | `_PREVIEW_CHARS` unused | [F-22](../bugs/F-22-assorted-hygiene.md) §22.2 |
> | `web_actions.py` duplicate comment block | [F-22](../bugs/F-22-assorted-hygiene.md) §22.12 |
> | `test_agent_actions.py` has no tests | [F-22](../bugs/F-22-assorted-hygiene.md) §22.13 |
> | `ACTION_TYPES` drift and missing wizard prompts | [F-05](../bugs/F-05-action-list-drift.md), [F-22](../bugs/F-22-assorted-hygiene.md) §22.15 |
> | `loop` return value vs `outputKey` (the misleading schema description) | [F-23](../bugs/completed/F-23-loop-id-contract-mismatch.md) |

---

## Naming inconsistencies

### `step_output` vs `previous_data` vs `result_data`

The accumulating context dict has three names depending on which file you are
reading. All refer to the same dict structure.

- `runWorkflow.py:173`: `step_output = dict(initial_data or {})`
- `loop_actions.py:47,73`: `prev_result_data`
- `workflow_actions.py` docstring: references `previous_data`

Not a defect — nothing behaves wrongly — but it is the single biggest obstacle
to reading the engine, because the same value appears to be three things as it
crosses module boundaries.

The redesign resolves this by giving the dict an owner: `WorkflowRun.data`,
named once (`docs/plans/redesign/plan.md` §2.4). Renaming in place would work
too and is a smaller change; either is better than three names.

### `loop` return value vs `outputKey`

The `loop` action stores the full `step_output` dict from the last iteration
under `result["id"]`, not the `outputKey`-extracted scalar. `outputKey` is only
used for logging to `loop_history`. This is documented in the `loop_actions.py`
docstring (loop_actions.py:7–20) but is a persistent source of confusion.

The behaviour is deliberate; the *documentation* of it is wrong in
`registry.py:84`, which is tracked as
[F-23](../bugs/completed/F-23-loop-id-contract-mismatch.md). The naming confusion that
survives even after the docs are corrected belongs here: `outputKey` is a
misleading field name for something that does not determine the output.

---

## Duplicate code

### `_SafeMap`, `_executables_in`

Both `shell_actions.py` and `human_shell_actions.py` define their own
`_SafeMap` and `_executables_in` with nearly identical logic. They differ only
in their `_INJECTION_RE` patterns:

- `shell_actions.py:27`: `` r'[;&|`$<>()\\\n\r\t]' ``
- `human_shell_actions.py:36`: `` r'[`\n\r\t]|\$\(' ``

There is also a `_SafeMap` in `scramda2_actions.py`, `human_decision.py`,
`file_actions.py`, `web_actions.py`, `skill_actions.py`, and
`writecode_actions.py` — twelve copies in total, each slightly different in
behaviour (some strip injection characters, some do not, some quote values).

This is the largest single piece of duplication in the codebase, and the
divergence between the two `_INJECTION_RE` patterns is not cosmetic — it is the
mechanism of [F-10](../bugs/F-10-shell-whitelist-template-gap.md).

`docs/plans/redesign/plan.md` §3.1 replaces all twelve with three classes —
`Template`, `ShellTemplate`, `PathTemplate` — one per genuinely distinct
behaviour.

### Action handlers not registered in the schema registry

`workflow` **is** registered: the `Workflow` dataclass at `registry.py:76–80`
carries `@_action('workflow')`. Earlier revisions of this document claimed
otherwise; that claim was wrong and is corrected here.

The real registry gap is `readFile`, which has a dispatcher branch and no
registry entry — see [F-05](../bugs/F-05-action-list-drift.md).

---

## Test layout

The active test files are:

- `clay/tests/test_core.py` — engine integration tests
- `clay/tests/test_lint.py` — linter tests
- `clay/tests/integration/` — integration tests (run-json, load-config, web
  mode, logger, terminal output)
- `clay/tests/actions/` — individual action unit tests

`test_core.py`'s header lists the per-action test files, and not all of the
listed files are present on disk. The header is a hand-maintained index of a
directory the test runner already enumerates, so it can only ever drift.
Deleting the index is better than correcting it.

See [F-22](../bugs/F-22-assorted-hygiene.md) §22.4 and §22.13 for the two test
files that are actively misleading rather than merely stale.
