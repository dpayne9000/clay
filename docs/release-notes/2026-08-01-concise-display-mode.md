# 2026-08-01 — `clay run` is quiet now, and `-v` is the old output

## The default run shows the turn, not the machinery

`clay run` and `clay dryrun` now draw through a new
[`ConciseRenderer`](../../clay/run/renderers/concise.py). `-v` / `--verbose`
selects [`TerminalRenderer`](../../clay/run/renderers/terminal.py) and reproduces
today's output exactly — the flag picks a renderer and nothing else:

```
clay run system coding2          # concise — the new default
clay run -v system coding2       # exactly what it looked like before
```

**`"visible"` did not move, and structurally could not have.** That flag is
applied at the source, in [`logger.emit`](../../clay/run/logger.py#L104) and
[`logger.output`](../../clay/run/logger.py#L127), before any renderer exists. A
hidden action's events never reach a front-end at all, so no renderer can change
what the flag means. Both modes show exactly the actions a workflow marked
visible. What changed is how much surrounding chatter is drawn, and how the
payloads of file writes, file reads and shell commands are formatted.

**Five things concise mode drops**, each an overridden method that returns:
step headers, the `▸ action → id` line, skipped actions, outgoing model prompts,
and `INFO` log lines. `WARN`, `ERROR` and `action.error` are never silenced by
any display mode, and neither is the spinner — in this mode it is the only sign
the run is still alive.

**Nothing is lost.** `logger` writes every event to the run log before any
renderer sees it — `show=False` gates the bus, never the file — so `logs/` is
byte-identical under both modes.

**Manual approval is untouched, and that is structural rather than careful.** An
approval question is printed by
[`approval.confirm`](../../clay/run/approval.py#L336) through `io.get().prompt()`,
the same channel a `humanDecision` uses, because `TerminalIO.prompt` must print
the question and read the answer on one call. No renderer draws either. That is
why a mode drawing almost nothing still asks every question it should — and also
why a banner written *inside* a prompt string is the one piece of chrome no
display mode can take back.

## File writes, reads and commands are drawn as what they are

| kind | drawn as |
|---|---|
| `file` | `✎ greet.py written (3 lines)` — named, no body |
| `diff` | `✎ utils/text.py updated (+4 −1)` then the diff, `+` green, `-` red, `@@` dim |
| `read` | `▪ utils/text.py read` — never the contents |
| `command` | the command, its output indented beneath |

The labels are unchanged: they were already written sentences composed by the
action that did the work, the only place that knew what it had done. The new
`termui` functions add a symbol, a colour and the body worth seeing, and never
rewrite the words — so an action that improves its label improves every surface
at once.

A created file shows no body and an edited one shows only its diff, which is the
judgement [`diff_body`](../../clay/actions/core/file_ops.py#L802-L813) already
documents from the other end. The `--- (before)` / `+++ (after)` header is
dropped: the label above already names the file, and those two lines start with
the same characters as a real removal and a real addition, so a themed terminal
would colour the header as a change.

**An unrecognised payload kind falls through to the parent's drawing.** A kind
this class has not been taught about is still something an action wanted shown;
swallowing it is the failure mode this design would otherwise have every time a
new action type is added. There is a test for it.

## coding2, the demo

Two changes, both required before it could run at all.

The `user_request` prompt in
[`iteration.json`](../../clay/data/workflows/system/coding2/iteration.json) drew
a 44-character `────` bar above and below *"what can I do for you?"*. It is now
the question and the caret, with a `_comment` recording why it must not come
back.

[`review.json`](../../clay/data/workflows/system/coding2/review.json) **was
invalid JSON** — a trailing comma after the `read` actionSet, line 62 column 3.
Nothing that loads coding2 could parse it, so this was a hard blocker rather than
a tidy-up.

## `system/clay` and `system/editor` lost their banners too

The same treatment, for the same reason — a bar drawn inside a prompt string is
printed by the channel and no display mode can take it back.

- [`clay/iteration.json`](../../clay/data/workflows/system/clay/iteration.json) —
  *"Clay is listening."* and a caret.
- [`editor/iteration.json`](../../clay/data/workflows/system/editor/iteration.json) —
  *"ask me to make an agent"* and a caret; and `check save`, which was
  `---- check file saved ----`.

Editor's `script_approved` prompt is the one that is not purely chrome: it
interpolates **two** bodies, a build plan and a script, and the `BUILD PLAN` /
`SCRIPT TO RUN` labels are what tells them apart. The labels stay, in sentence
case; the five rule lines are replaced by blank lines.

Still carrying banners, and untouched because they were not named:
`dev/system/editor/iteration.json`, `dev/developer/`, and the
`templates/skunkworks/*` set. (`coding3` was on this list and came off it —
see below.)

## Under it, one refactor

`run.start`, `run.complete` and `step.start` moved out of `TerminalRenderer.handle()`
into methods. `handle()` stays the single description of the event vocabulary and
a subclass overrides a hook instead of copying the dispatch — the reason
`detail.py` exists, applied to dispatch instead of to formatting.

New tests in
[`clay/tests/run/test_concise_renderer.py`](../../clay/tests/run/test_concise_renderer.py).
Several render the *same* event through **both** renderers and assert the
difference: a silencing rule that quietly stops silencing is invisible if only
one side is asserted.

Design notes, including what was deliberately kept:
[`docs/tasks/concise-display-mode.md`](../tasks/concise-display-mode.md).

---

# Also in this release — `system/coding3` reviewed, and two fixes underneath it

Prompted by a question about whether the workflow overcalls the model, whether
its training examples show what we actually want, whether editing survives the
way data is moved, and whether it knows what is on the filesystem versus what it
believes it wrote. The full trace is in
[`docs/tasks/coding3-workspace-review.md`](../tasks/coding3-workspace-review.md).
Seven items came out of it; six are fixed.

## A file that is not UTF-8 no longer breaks the turn

The two halves of the workspace protocol disagreed. `serveFileReads` read with
`errors='replace'`, so a binary or mis-encoded file was handed over as text
peppered with U+FFFD — text a model can quote but whose SEARCH side can never
match. `applyFileWrites` then read the same file strictly and let
`UnicodeDecodeError` escape into the run.

Now serving answers `(unreadable: not valid UTF-8 — this file cannot be read or
edited as text)`, and applying catches the error beside `OSError` and returns a
workflow error. A file that cannot be edited is a fact to report, not a crash,
and one refused file does not stop the others being served.

## Truncation says that it truncated

The old marker was `… (truncated)`. The write prompt independently instructs the
model to send a restructured file *whole* — and doing that from a truncated read
deletes everything below the cut, silently, in a step reported as success. The
marker now gives the cap and the real length, states that the whole file was not
shown, and says to edit with SEARCH/REPLACE instead.

Note that `maxBytes` is **per file**, not a total budget.

## One spelling of a path

`files_written` now reads `CREATED: todo/cli.py`, not an absolute path, and so do
the `read` / `diff` / `file` payload labels, the manual-approval question and its
skipped-files warning. The listing, the read blocks and the write report finally
agree, which matters most at the approval prompt — a human was being asked about
`/Users/…/todo/cli.py` having been shown `todo/cli.py`.

`WorkspaceRoot.relative` stays: `pathsKey` still accepts an absolute list a
workflow assembled itself, and older transcripts still name files that way.

Tests: `PathNamingTest`, `UndecodableFileTest`, `TruncationNoticeTest` in
[`test_file_ops.py`](../../clay/tests/actions/test_file_ops.py). These land for
`system/coding2` at the same time — both workflows share the handlers.

## New action: `matchText`

[`clay/actions/match_text_actions.py`](../../clay/actions/match_text_actions.py).
A whole-string, stripped, lower-cased comparison of a context key against a list
of literals, emitting one of two fixed strings.

It exists because coding3's `keep_going` was a model call asking, every turn,
whether the user had typed a quit word — and the answer then had to survive
`is_truthy`, whose falsy set holds `no` but not `no.`. A model replying "NO."
meaning *stop* was read as *carry on*, and the session continued after the user
asked to end it. That class of failure is gone: the two outputs are fixed
strings the action chooses between, not text a model composes. A model call per
turn goes with it.

Whole-string matching is deliberate — substring would make a `values` list
holding `"no"` fire on *"no, make it blue"*. `onMatch`/`onMiss` are read without
a `.get` default so a workflow can emit `''` on purpose, which is how `is_truthy`
spells no. 17 tests in
[`test_match_text_actions.py`](../../clay/tests/actions/test_match_text_actions.py),
including one that states the limitation rather than hiding it: `quit.` is a
miss, and the session continues, which is the recoverable direction.

**`clay build` must be run** before `clay lint` recognises the type.

## coding3's review pass was being taught to keep writing

Its few-shot examples were `write_examples` — the write pass's examples, where
every one ends in file fences. A review pass primed on four examples that all
write files is being told that writing is the expected outcome, on the one pass
whose most common correct answer is *"I found nothing."*

It now has `review_examples`, and the first of the three is the found-nothing
case: one sentence, no fences. The other two are a planned file that came back
`(not found)` and a real cross-file defect — `json.dumps` with no `import json`
— fixed by SEARCH/REPLACE.

`write_examples` #4 was rewritten in the same pass. It showed a file marked
`(not found)` producing a *refusal*, which is the opposite of what that marker
means: not found is how the workflow says "this one is new, create it."

## The report no longer under-reports

Two fixes, one cause. A turn whose write step is refused wholesale — one fence
missing a path discards the reply, by design — and whose review then repairs and
writes it produced files that `files_written` does not list. The transcript and
the report were both built from `files_written` alone, so the next turn read a
record saying nothing was written when two files had been. Both now carry
`review_writes`, as its own transcript entry: *"the write step wrote nothing and
the review wrote these two"* is a different history from *"these two were
written."*

At the same time `turn_report` and `turn_summary` — two `reports` calls over
near-identical inputs, differing in length and in whether they named paths —
became one call doing both jobs. A third model call per turn goes. The merged
prompt names the paths: the person can see them on screen, but a future session
reading this out of memory cannot recover a path by guessing.

## The one item not delivered

`will_write` was to be dropped, gating the review on `target_files` coming back
empty instead. Traced, that costs more than it saves: `target_files` is
contractually *"every file the plan touches **or needs to read**"*, and its own
worked example shows a pure question about `todo/store.py` returning
`todo/store.py`. Gating on it would run the review's one or two model calls on
exactly the turns that are otherwise cheapest.

`will_write` stays — it is the smallest prompt of the nine and answers a question
nothing else answers. Two other routes are recorded in §6 of the task doc;
neither was taken here.

## coding2 has three of the same defects

Named so the divergence is deliberate: `write_examples` on its review pass
(`coding2/review.json:18`), `keep_going` as a model call
(`coding2/iteration.json:162`), and the `turn_report`/`turn_summary` split. Not
in scope for this pass. The `file_ops` fixes above already apply to it.

---

## Correction to the previous note

[`2026-08-01-clay-chat-agent.md`](2026-08-01-clay-chat-agent.md) reported two
upstream problems. **The first of them was wrong**, and it is withdrawn here
rather than edited out of a committed note.

**`scramda2`'s `examples` field is documented correctly.** The claim was that
[scramda2_actions.py:15](../../clay/actions/scramda2_actions.py#L15) documents
`[{"input": ..., "output": ...}]` while the adapter reads `question`/`answer`.
That traced the wrong adapter. [`scramda3.py`](../../clay/adapters/scramda3.py)
is not on this path: `scramda2` calls
[`gopher.fire`](../../clay/adapters/gopher.py#L40), and the connector's
`_normalize_example`
([fewshot.py:89-102](../../connectors/gopher/gopher/fewshot.py#L89-L102))
accepts `input`/`output`, `question`/`answer`, `prompt`/`completion`,
`role`/`content` and 2-tuples. Both shapes work — `system/clay` uses
question/answer, `system/coding2` uses input/output, and neither is a defect.

The second finding stands: `browseWeb`'s `siteKey` still writes into the source
tree ([web_actions.py:43-44](../../clay/actions/agent/web_actions.py#L43-L44)).
