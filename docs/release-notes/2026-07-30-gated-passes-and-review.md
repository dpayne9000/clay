# 2026-07-30 — gated passes, a review loop, and the prompt cap settled

Task doc: `docs/tasks/gated-passes-and-coding2-review.md`

Picks up where `2026-07-30-prompt-cap.md` left off (commit `2861766`) and
covers everything since.

---

## Part 1 — finishing the prompt cap

Three commits landed after the prompt-cap note was written and are not
described in it.

### The cap now reaches `clay ui`, `clay attach` and the dashboards

The first version only cut the prompt on the CLI's own prompt-box path and in
the Telegram chat. Every other surface draws payloads through
`payload_lines()` in `clay/run/renderers/detail.py`, so the cut moved inside
that helper. One setting, same result on the terminal, Telegram, `clay attach`,
the Qt log panel, the manager and the dashboard.

There is no double-cut: the terminal returns at `kind == 'prompt'` before it
reaches `payload_lines`, and the chat builds its own strings.

If you saw `clay ui` ignoring the setting while the CLI honoured it, that was
a running process holding the old module in memory — Python does not
hot-reload. Restart `clay ui` after changing renderer code. Each `clay run` is
a fresh interpreter, which is why the CLI appeared to work first.

### The fallback is now 200, not 2000

`DEFAULT_PROMPT_MAX_CHARS` in `clay/lib/config.py` is **200**. That is what an
existing `~/.clay/config.json` gets, since `create_user_config()` only writes
the file when it is missing and never back-fills the new key.

> **Note:** `configs/default.json` still ships `"promptMaxChars": 2000`, so a
> **fresh** install gets 2000 and an **existing** one gets 200. Both are
> deliberate numbers in their own right, but they disagree. Set
> `display.promptMaxChars` in your own `~/.clay/config.json` to pin it.

### Spinner label

`SPINNER_LABEL` in `clay/run/termui/themes/default.theme` is now `processing`,
and the terminal renderer starts the spinner with that label.

---

## Part 2 — `when` and `whenNot`: actions that run only sometimes

Any action may now carry a gate:

```json
{"id": "review", "type": "scramda2", "when": "files_written", "...": "..."}
{"id": "no_review", "type": "loadContext", "whenNot": "files_written", "...": "..."}
```

- `when` — run only if that earlier output means **yes**
- `whenNot` — run only if it means **no**, for the other half of a branch
- both — both must hold
- neither — always, which is every workflow written before this

**What counts as no:** `false`, `done`, `0`, `no`, `stop`, empty. Anything else
is yes. This is exactly the list `loop`'s `continueKey` has always used; it now
lives in `clay/lib/flags.py` and both read it, so they cannot drift.

The useful consequence: **a model answering `NO` in one word gates natively.**
No comparison operator, no second field — `when` stays one string.

The key is read from the run's accumulated output and **does not need to be in
`includedData`**. A gate is not data the action consumes; requiring it would
mean pouring a value into a prompt purely to be allowed to test it.

### It will not go quiet on you

- **A skipped action stores nothing, and clears its id.** Inside a loop, an
  action skipped on pass 2 would otherwise leave pass 1's answer standing for a
  later gate to read.
- **A gate naming a key nothing produced warns.** That is a typo or a renamed
  action id. It still skips, but it says so.
- **A gated action is still validated.** A typo in an action that did not run
  this turn is reported now, not on the turn the gate happens to open.

### `action.skipped`

A new event carrying `id`, `action_type`, `key`, `value` — drawn on every
surface:

```
  skipped review_log (no files_written)
```

and as a dimmed node border in the `clay ui` graph. `"visible": false` silences
it like any other event. A run where three actions simply are not there is
unreadable unless it says which ones and what decided.

---

## Part 3 — `loop` gained `merge`

A loop stores its sub-workflow's entire final `step_output` as one dict under
its own id, which cannot go in a prompt or be gated on without rendering the
whole nested run.

```json
{"id": "review_log", "type": "loop", "file": "./review.json", "merge": true}
```

`merge` publishes the last iteration's action ids into the calling workflow
instead, the way `loadContext` already does — so a nested pass composes with
the workflow around it. **Off by default**: it writes into the caller's
namespace, and an existing workflow must not start doing that because it was
upgraded.

---

## Part 4 — coding2 writes better code

`orient → ask → converse → resolve → apply → execute → review → settle`

### The thinking pass now plans

For a request touching more than one file, `reply` lists the files in the order
it will write them, says what each depends on, and settles the design decisions
— because the acting pass does not get to reconsider. For a question or a
one-line change it says so and answers; a plan for a one-liner is noise.

**This costs nothing.** It is the existing call doing a better-defined job.

### A review pass that finds and fixes

`workflows/system/coding2/review.json` runs after the files land and the
commands run. Each pass is one model call that finds real defects *and* fixes
them as named fences; the fixes are applied and the commands re-run to prove
them.

**Repeat-until-clean is free.** The loop continues on `review_writes`, and
`applyFileWrites` returns nothing when a reply has no file fences — so a pass
that changed something earns another pass to check it, and a pass that found
nothing stops the loop. No model call is spent asking "are we done"; the answer
is already on disk.

### It also fixes what it was told to fix

The review is told what the user asked for, not just what was written. A file
that runs but does not do the requested thing is treated as a defect.

### Earlier in the same tune-up

- `final_reply` now receives `{relevant_memory}` — the acting pass had been
  writing code without the memory the thinking pass was given.
- `final_reply`'s fence-naming sentence no longer contradicts `protocol`. It
  said the filename could go on the fence line *or* in a first-line comment;
  `protocol` says the fence line, every time. Two rules for one thing is how a
  model ends up following neither.
- `turn_report` says "Files written this turn", not "Files the workspace wrote
  this turn".

### What a turn costs

| turn | model calls |
|---|---|
| conversation (no files written) | **5** — exactly as before |
| code turn, review finds nothing | 6 |
| code turn, review fixes something | 7 |

The gate is what makes that true: a conversational turn skips the review
entirely and runs the same five calls it ran yesterday.

---

## Part 5 — memory, skills and reads no longer paste whole files at you

Task doc: `docs/tasks/payload-char-cap.md`

A `searchMemory` or `listSkills` echoed its entire result to the screen, and
`serveFileReads` echoed every file it handed the model. On a terminal that
scrolls the run away; in a Telegram thread it is several messages of something
already on disk.

Each of those actions now has its **own** character cap:

```json
"display": {
    "promptMaxChars": 2000,
    "payloadMaxChars": {
        "writeMemory": 800,
        "searchMemory": 800,
        "listMemory": 800,
        "readMemory": 800,
        "writeSkill": 800,
        "listSkills": 800,
        "searchSkills": 800,
        "removeSkill": 800,
        "serveFileReads": 1200
    }
}
```

One number per action, not one shared number: a memory entry is a paragraph
and a served file set is several screens, so a single knob would have to be
wrong for one of them. Set any of them to `0` to draw that action whole.

**Keyed by action type, not by payload `kind`.** `kind` says what a payload
*is* — a file, a listing — and several actions share each one. What earns a cap
is an action that quotes something already on disk back at you, which is a fact
about the action.

**What is deliberately not capped:** `applyFileWrites`, `runReplyCommands`, and
a model's answer. A file the turn just wrote and a command's output are the
turn's *result*, and the reasoning that leaves a model's answer whole applies to
them too. An action with no entry in the table is drawn whole, so nothing you
already watch changes size.

**Nothing is lost.** `logger.output` writes to the run log before any renderer
sees the event, so a cut hides text from a screen and never from the record.
The tail says so:

```
… 4210 more characters — full text in the run log
```

It reaches every surface — terminal, Telegram, `clay attach`, the Qt panel,
manager and dashboard — because the cut is in `payload_body()` in
`clay/run/renderers/detail.py`, beside `prompt_body()`.

**On an existing install it works with no config edit.** `create_user_config()`
only writes `~/.clay/config.json` when it is missing, so an existing file never
gains the key; the caps above are baked into `DEFAULT_PAYLOAD_MAX_CHARS` and
clay prints a one-time line saying it is using them. Add the `payloadMaxChars`
block to your own config to override.

A non-numeric value (`true`, `"800"`) draws that action whole and says so once
— never silently.

---

## Part 6 — a reply that loses a filename now loses nothing else

Task doc: `docs/tasks/fence-naming-and-review-reads.md`

### The bug

A multi-file reply that named its first fence and drifted on the later ones
wrote the named files, **dropped the rest in silence**, and reported success.
`files_written` listed a subset, the workspace held half a design, and nothing
said why — the "reply shows code in a fence that names no file" warning only
ever fired when *nothing at all* was written.

### applyFileWrites now refuses the whole reply

One unnamed code fence and nothing is written, including the correctly named
files in the same reply:

```
ERROR  applyFileWrites: 2 code fence(s) name no file — nothing was written,
including the 1 named change(s) in the same reply. Name the file on the fence
line (```python path/to/file.py), in a first-line comment, or on the line above
the fence — every fence, not only the first.
```

All-or-nothing is recoverable; half-written is not. The turn continues,
`files_written` is empty, and the review is skipped by its own gate.

**The one inference still works.** A lone unnamed fence whose commands mention
exactly one file is still attributed to that file and written — `unwritten_fences()`
exists specifically so the refusal does not swallow a form that has always worked.

A broken `<write_file>` tag still warns rather than refusing: it cannot appear
alongside writes that succeeded, so there is nothing for a refusal to protect.

**A fence inside a `<write_file>` body is content, not a fence of the reply.**
A markdown document containing a ```` ```python ```` example is one file, not
three blocks — the tag already named it. `fences()` now skips those regions
outright, which also stops them reaching `parse_changes` and the lone-fence
inference. An unclosed tag is unaffected: that file really is lost.

### The prompts say it much harder

`protocol`, `final_reply` and the review prompt now all say **every** fence,
not just the first — that later fences are where the drift happens, that one
unnamed fence discards the entire reply, and that naming a file in prose, a
heading or a bullet does not write it. A new training example writes **three**
files in one reply; the set previously topped out at two, below where the drift
starts.

---

## Part 7 — the review pass now reads the disk

### It was reviewing a claim, not code

`review.json` was given `final_reply`, `files_written` and `command_output` —
the reply text and a list of `CREATED:` lines. It had **never seen the file
contents**. It was checking the model's account of what it wrote. A second pass
also could not see the fix the first one made.

### `serveFileReads` gained `pathsKey`

```json
{
  "id": "reviewed_files",
  "type": "serveFileReads",
  "reply": "review_reply",
  "pathsKey": "files_written",
  "root": "{workspace}",
  "maxFiles": 20
}
```

It serves a plain newline list of paths outright — with or without
`CREATED:`/`UPDATED:` prefixes — before any `<read_file>` tag, duplicates
removed. The absolute paths `applyFileWrites` reports are converted to
workspace-relative ones; anything outside the workspace is dropped and warned
about.

A new `read` step runs at the top of the review loop, so the review sees what is
on disk *now*, including a fix an earlier pass made. **No extra model call** —
the files are handed over rather than asked for.

### You can now tell a real read from a claimed one

`logger.warn` and `logger.info` never consult `"visible"` — only payloads do. So
`file_context` stays hidden and `serveFileReads` still reports:

```
serveFileReads: read 2 file(s) — todo/store.py, todo/cli.py
serveFileReads: nothing was read this turn — the next pass works from the file
listing and its own assumptions about files it has not seen
serveFileReads: could not read ghost.py — the model was told so in place of the
contents
```

The "nothing was read" line is suppressed when the workspace is empty — nothing
to read means no assumption to make. It does still fire on a purely
conversational turn in a populated workspace, which is accurate but chatty.

---

## Upgrading

The schema cache is generated, so rebuild it before `when`/`whenNot` reach a
model prompt or the linter's copy:

```
.venv/bin/python -m clay build
```

Nothing else changes for an existing workflow — an action with no gate runs
exactly as it did.

## Verify

```
.venv/bin/python -m clay.tests
.venv/bin/python -m clay lint workflows/system/coding2
```
