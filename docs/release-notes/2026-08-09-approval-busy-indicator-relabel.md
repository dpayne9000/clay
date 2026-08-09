# 2026-08-09 — approval gate re-raises the busy indicator after it resolves

## Fixed

`clay/run/approval.py:confirm()` now calls `logger.busy(True, gate)`
immediately after `io.get().prompt()` returns an answer, before
`_parse_answer()`.

Every input channel's `prompt()` calls `io._floor_to_human()` first, which
drops the busy indicator (`logger.busy(False)`) so a terminal spinner or a
Telegram typing hint doesn't eat the question it's about to draw
(`clay/run/io.py:42-56`). Nothing raised it back once the question was
answered: `confirm()` returned straight into the calling handler, which then
did the actual work — executed generated source, wrote files, ran a shell
command — with every front-end's indicator dark for the whole of it. This
was worst on precisely the slowest actions in the system, the ones gated
because they're consequential.

## Not changed

- The gates themselves: still fire, still render their diff, still refuse on
  "no". This only affects what a front-end shows while the approved work
  runs.
- `logger.busy()`'s contract — `active` is a level, not a counter — is
  unchanged; the fix relies on it directly (a relabel, not a second "started"
  event).

## Tests

`clay/tests/run/test_busy.py` — new `ApprovalRelabelTest`:

- `test_the_indicator_relabels_once_the_gate_is_answered` — a real
  `io.QueueIO()` channel, answered from a background thread, asserts the full
  bracket `[True, False, True]` around `approval.confirm(..., required=True)`.
- `test_a_refused_prompt_still_relabels` — same bracket on a "no" answer; the
  handler still has bookkeeping to do either way.
- `test_a_closed_channel_does_not_relabel` — `[True, False]` only: nothing is
  about to run, so nothing should claim to be working.

These go through a production `QueueIO`, not a scripted double that bypasses
`_floor_to_human()` — the sequence being asserted is the one a real channel
actually produces.

## Verify

```
.venv/bin/python -m clay.tests -v clay.tests.run.test_busy
```
