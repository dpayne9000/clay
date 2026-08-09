# Documentation queue reconciliation

The bug, task, and plan directories now distinguish active work from completed
history. Nine fixed, obsolete, or explicitly by-design bug records and completed
task/audit records moved into `completed/` folders without renumbering bug IDs.

The active bug index was reverified against current source. Stale broad reports
for registry drift, daemon/model propagation, hygiene, and workflow `outputKey`
were narrowed to their remaining behavior. A new numbered
`confirmed-engine-priorities.md` task records both verification and implementation
checkboxes so confirmed findings are not misreported as completed fixes.

The current PlantUML diagram was also reconciled with the live nested-run
signatures, layered `autoContext`, engine-global reseeding, dot-path access to
full loop results, ignored workflow `outputKey`, and interactive seeded-workflow
upgrade component. It continues to show global run state as global rather than
drawing the proposed session object prematurely.

## F-24 response-rendering control flow

The terminal response renderer no longer catches every `BaseException` and
prints `broken line`. It performs rendering only; ordinary renderer failures
are isolated and reported by the existing event-listener boundary, while
`KeyboardInterrupt` and `SystemExit` propagate normally. Focused tests cover
both the direct renderer and listener boundary behavior.

## Startup configuration and legacy transform documentation

Starting `clay` without a subcommand now validates the startup configuration
before reading its first workflow reference. Missing, malformed, empty, and
blank values produce a concise error and status 1 instead of `KeyError` or
`IndexError`; focused tests cover validation and resolution.

The unused `transformData` action is now identified in source and schema text
as legacy compatibility behavior. Its existing `map` result is unchanged, with
TODOs recording possible future contracts and the validation/migration work
required before one is selected.

## File-write refusal guidance

The atomic file-write refusal again tells the model to put a path on **every
fence**. This restores the exact actionable requirement expected by the
workflow training and its regression test; parsing and write behavior are
unchanged.

## F-04 pre-fix lifecycle reproductions

Test-only regression coverage now captures the currently broken root lifecycle:
raised execution leaves the active logger and log handle behind, causes the
next independent run to lose its root events, and behaves the same for
`KeyboardInterrupt` and `SystemExit`. Production lifecycle behavior is not yet
changed; these tests are intentionally expected to fail before the fix.

A temporary F-04/F-14 pause recorded the concern that a broad failure redesign
could alter legitimate no-output workflows. The narrow implementation below
supersedes that pause without reinterpreting those workflows.

## Exception-safe lifecycle and minimal workflow failure

The temporary pause was lifted for a narrow implementation. Root execution now
owns and releases its logger through `finally`, including on ordinary and
control-flow exceptions, so one failed in-process run cannot poison the next.

One `WorkflowFailure` signal now stops unambiguously invalid workflows: action
schema failures and unknown action types. Successful `{id, data}` and `None`
no-output behavior are unchanged. Failed roots reuse `run.error`, already
handled by terminal, Qt, Telegram, daemon and attach clients, and never emit
`run.complete`. CLI `run` and `run-json` return status 1 for known failures;
unexpected exceptions remain exceptions after the client-visible error event.

## Marketplace MVP workstream

A new coordinating task filters the active bug/task catalog into six concrete
release gates: baseline verification, installability, trust boundaries,
preflight structural refusal, bounded nested execution, and shipped-workflow
acceptance. It links existing detailed records rather than duplicating their
plans, records platform/trust/concurrency decisions explicitly, and separates
true launch work from compatibility cleanup and post-MVP architecture.

The first installability change explicitly includes Clay's packaged data tree
and terminal themes in setuptools wheel configuration. Wheel-content and clean
installation verification remain pending.

Marketplace scope is now macOS/Linux with best-effort POSIX operation under
WSL2, and marketplace workflows are untrusted by default. Native Windows work
is deferred. Qt inspection found that ordinary Run/Run Auto still execute
in-process through `WorkflowRunner`; only Run Daemon uses clayd, so daemon-only
UI execution remains an explicit MVP decision rather than an assumption.

That Qt decision is now implemented. The PySide6 desktop actions are labeled
as interactive, auto, and unattended clayd runs; all three launch isolated
daemon-managed subprocesses, with the selected run's events mirrored into the
editor and all runs available in the process dashboard. PySide6 is now the
optional `ui` dependency, and `clay ui` explains how to install `clay[ui]`
instead of failing with an import traceback. On WSL2 this remains best-effort
through the same Qt/WSLg POSIX path, not a separate Windows UI implementation.
The obsolete in-process Qt runner was removed; generic `QueueIO` remains for
embedded callers and tests, while the desktop uses clayd `SocketIO` events.

Daemon-backed Qt terminals now display the workflow `busy` level in a dedicated
non-scrolling label and clear it on completion, error, or process exit. Coding3
was not failing validation or aborting a loop: its visible output ended at the
initial model prompt while the request was still running, and recent stops were
SIGTERM before the outer loop began.

Three pre-existing tests were reconciled with the minimal F-14 contract:
hidden schema errors remain visible, gated actions remain validated before
skipping, and unknown action types now stop instead of being silently omitted.
