# 2026-08-01 — `system/clay`, a conversational agent with web lookup

## A helpful dragon: `clay run system clay`

A new system workflow at
[`clay/data/workflows/system/clay/`](../../clay/data/workflows/system/clay/):
Clay talks, answers questions, looks things up on the web when the answer is not
already in the model, and writes files when asked. Eight files — five loaded at
boot, one turn body, one branch file.

The character is deliberate and lives in data, not in code:
[`goal.json`](../../clay/data/workflows/system/clay/goal.json) carries the
mission, [`character.json`](../../clay/data/workflows/system/clay/character.json)
carries `voice` and `boundaries`. The distinction the prompts are built around is
between being *agreeable* and being *good* — saying the true thing when a
pleasanter thing is available, saying "I don't know" in those words, declining
harm in one sentence without a lecture and then helping with the part that was
fine. Ten worked examples in
[`training.json`](../../clay/data/workflows/system/clay/training.json) cover a
cited lookup, an empty lookup, a file write, a SEARCH/REPLACE edit, a refusal, an
uncomfortable-but-fair question answered properly, a vague request met with one
clarifying question, and a disagreement stated once and then dropped.

**Web lookup runs on Google Custom Search.**
[`search-keys.json`](../../clay/data/workflows/system/clay/search-keys.json)
ships with `google_api_key` and `google_cx` blank and **must be filled in before
the workflow can search**. The default `duckduckgo` engine was rejected on
inspection: it calls the Instant Answer API
([web_actions.py:229](../../clay/actions/agent/web_actions.py#L229)), which
returns abstracts and related topics rather than search results, and comes back
empty for most real questions.

With the keys blank, `searchWeb` logs `searchWeb(google): missing 'apiKey' or
'cx'` and returns `None`. There is no fallback to another engine and no silent
degradation — Clay reports that the lookup did not work.

**Credentials reach the action through `{"override": ...}`, not interpolation.**
`searchWeb` reads `apiKey` and `cx` off the action dict directly with no
`format_map` ([web_actions.py:323-327](../../clay/actions/agent/web_actions.py#L323-L327)),
so an inline `"{google_api_key}"` would be sent to Google verbatim.
`{"override": "google_api_key"}` is resolved by
[`_resolve_action_fields`](../../clay/run/dispatcher.py#L106-L121) before the
handler runs, reading raw `step_output`, so the key never has to be poured into
an `includedData` list to be usable.

**The lookup branch is one gate level deep, with a `loadContext` for the negative
half.** All four lookup actions gate on the same always-present `needs_web`.
Chaining them — gating `browseWeb` on `chosen_url` — would have been natural and
is wrong: a skipped action pops its own id
([dispatcher.py:221-227](../../clay/run/dispatcher.py#L221-L227)) and
[`_gate_value`](../../clay/run/dispatcher.py#L133-L145) warns when a gate names a
key nothing produced, so a conversational turn would print a warning every time.
[`no-lookup.json`](../../clay/data/workflows/system/clay/no-lookup.json) runs in a
later step under `whenNot: "needs_web"` and merges honest text back under the
three popped names, so the answering prompt never carries an unresolved
`{placeholder}`.

**`applyFileWrites` runs on every turn, ungated.** A reply with no fences parses
to no changes and returns an empty string without complaint
([file_ops.py:856-866](../../clay/actions/core/file_ops.py#L856-L866)), so there
is no "did they ask for a file?" classifier to get wrong. The all-or-nothing
refusal for an unnamed fence
([file_ops.py:846-855](../../clay/actions/core/file_ops.py#L846-L855)) is trained
against directly:
[`abilities.json`](../../clay/data/workflows/system/clay/abilities.json) leads
with it and tells Clay never to mix an illustrative snippet with a real write in
the same message.

**No action sets a `root`.** Same as `system/coding3` — an omitted root is
`DEFAULT_ROOT` (`'.'`), which
[`workspaces._base_for`](../../clay/run/workspaces.py#L227-L242) resolves against
`paths.project_dir()`, so the workspace *is* `--project-dir`.

Full design notes, including the two shapes that were rejected:
[`docs/tasks/clay-chat-agent.md`](../tasks/clay-chat-agent.md).

---

## A unit test no longer stops on an approval prompt

`RootInterpolationTest.test_unresolved_placeholder_is_left_intact_not_crashed`
in [`clay/tests/actions/test_file_ops.py`](../../clay/tests/actions/test_file_ops.py)
ran `listWorkspace` with `"root": "{nosuchkey}"` and asserted the action shrugged
and reported an empty listing. That expectation predates the workspace register.
The placeholder survives interpolation intact, becomes a literal directory name
under the project directory that nothing has approved, and
[`workspaces.authorize`](../../clay/run/workspaces.py#L245-L271) now asks a human
about it — so a full test run stopped and waited for an answer.

The refusal is the correct behaviour and the test now asserts it: `data` is
`None` and the error names the offending path. Reporting "no files yet" for a
directory whose name is a typo is how a workflow runs to completion having read
nothing and says so nowhere.

`approval.set_unattended(True)` is what turns that question into a
`WorkspaceDenied` the test can assert on, and it is set **inside that one test**,
not in `WorkspaceTestCase.setUp`. Putting it in the shared fixture looks tidier
and breaks two other tests: the flag also short-circuits `approval.confirm()`
([approval.py:316-321](../../clay/run/approval.py#L316-L321)), so the read and
write gate tests auto-approve everything and never exercise the refusal they
exist to check. [`workspaces.authorize`](../../clay/run/workspaces.py#L245-L271)
says as much in its own docstring — the workspace question and the per-file
question are two decisions that happen to share one flag.

**Unblocking the run exposed a test whose result depended on the developer's own
config.** `unittest` runs classes alphabetically, so `RootInterpolationTest` came
before `ServeFileReadsApprovalTest`; the suite had been stopping at the prompt
and never reaching that class at all. Two things were wrong in it.

`test_a_refused_read_is_told_not_silently_dropped` asserted
`assertEqual('(not approved', result['data'])` and then, two lines later,
`assertIn('B\n', result['data'])` on the same value — the served body of the file
that was *not* refused. No string satisfies both; it is now `assertIn`, which is
what the neighbouring assertions already meant.

The failure underneath it was the fixture. `WorkspaceTestCase.setUp` approved its
temporary root with no `gates` argument, so
[`_clean_gates`](../../clay/run/workspaces.py#L107-L119) filled them from
`get_approval_defaults()` — that is, from the real `~/.clay/config.json`.
`ApprovalGateTestCase.setUp` then switched `fileReads` on, and the *handler call*
was the first entry into that directory, so
[`authorize`](../../clay/run/workspaces.py#L245-L271) ran `_apply_gates` and
stamped the config's gates over it. `approval.confirm` saw a closed gate,
returned everything without prompting, and the refusal path the test exists to
check never executed. On a machine whose config asks about reads, the same test
passed.

`setUp` now calls `workspaces.authorize(self.root)` immediately after approving.
Gate seeding is once per directory per session by design, so doing it in the
fixture means it is finished before any test sets a gate, and no test result
depends on the config file of the machine it runs on. That was already the
stated purpose of redirecting `REGISTER_PATH` in the same fixture; it covered
the register and not the gates inside a grant.

---

## Two upstream problems found, not fixed

Both were found by reading while building the above. Neither is changed by this
release; both are one-line-ish fixes that belong to their own change.

**`scramda2`'s `examples` field is documented with the wrong keys.**
[scramda2_actions.py:15](../../clay/actions/scramda2_actions.py#L15) describes
few-shot examples as `[{"input": ..., "output": ...}]`. The adapter reads
`ex['question']` and `ex['answer']`
([scramda3.py:37-38](../../clay/adapters/scramda3.py#L37-L38)) and would raise
`KeyError` on `input`/`output`; every `training.json` in the repo uses
question/answer. The schema description is the first thing a workflow author
reads, and it describes a shape that cannot work.

**`browseWeb`'s `siteKey` writes into the source tree.**
[web_actions.py:43-44](../../clay/actions/agent/web_actions.py#L43-L44) derives
`WEBACTIONS_BASE` from the module's own path, so site profiles land in the
checkout rather than under `$CLAY_HOME` — the same class of bug as the
project-directory work in the previous release. `system/clay` does not use
`siteKey`, so nothing here depends on it.
