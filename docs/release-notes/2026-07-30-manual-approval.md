# 2026-07-30 — manual approval, and diffs instead of file dumps

Task doc: `docs/tasks/manual-approval-and-diffs.md`

Picks up from `2026-07-30-gated-passes-and-review.md` (commit `664796e`).

---

## Nothing changes until you ask for it

The shipped default is **off**. A run behaves exactly as it did yesterday until
someone turns manual mode on, and an existing `~/.clay/config.json` — which
never gains new keys — falls back to the same built-in default silently. There
is no notice for this one, because "ask about nothing" *is* the old behaviour.

---

## Three gates, switched independently

```
fileWrites   applyFileWrites     before anything reaches disk
fileReads    serveFileReads      before anything is opened
commands     runReplyCommands    before anything is executed
```

A master switch turns the whole thing on; the three gates say what it covers.
Two levels rather than one because `/manual off` has to silence everything with
one word, while the gates stay set underneath — turning it back on restores the
arrangement you chose rather than a blanket default.

**Reads are off by default.** `serveFileReads` is read-only inside a workspace
you chose, and the review loop serves up to twenty files a turn; gating it by
default would stop every turn twice before anything happened. It is still
switchable, because "read the whole workspace" is a different proposition on a
machine holding more than the project.

```json
"approval": {
    "manual": false,
    "fileWrites": true,
    "fileReads": false,
    "commands": true
}
```

That block is the settings a **new session starts with**. It is never written
by a toggle — a switch typed mid-run that edited a file you maintain by hand
would outlive the session that set it, and tomorrow's unrelated run would start
gated because of something you typed today.

---

## The session is the process

There is no session file and no session id, because there was never anything to
key. clayd spawns **one subprocess per workflow**, `clay run` is its own
process, and `clay ui` runs its workflow on a worker thread of the app. So the
setting lives in module state in `clay/run/approval.py`, which makes it
per-session by construction: independent across runs, nothing to plumb, and
nothing left behind when a run crashes.

---

## Switching it

### CLI — a command, drawn as a command

Type it at **any** prompt. It is recognised, applied, drawn in its own colour,
and the same question is asked again — the workflow never sees the line.

```
  » /manual on
    manual approval on — writes on, reads off, commands on

what would you like me to do?
>
```

```
/manual                              show the current settings
/manual on | off                     the master switch
/manual writes|reads|commands on|off one gate
/help                                the list
```

`writes`, `write` and `fileWrites` all work. A gate set while manual mode is off
says so instead of quietly turning the master switch on for you. An
unrecognised `/word` is answered rather than passed through — `/undo` typed at a
coding prompt must not become the request.

This lives in `TerminalIO.prompt`, not in `humanDecision`, so it covers every
terminal prompt including the approval prompt itself, and no action's behaviour
changed to get it.

### Telegram — the same words

`/manual on`, `/manual reads on`, and so on, registered alongside `/start`,
`/status` and `/cancel`.

The bot cannot hold the live setting — that is in the workflow process clayd
spawned — so it keeps the chat's *choice* and pushes it into every run it
starts, **including one already running**. That is what makes `/manual on`
typed between turns take effect on the current turn rather than the next
launch. Settings are pushed on a run's first event, which is the proof its
event socket is up.

New daemon command, alongside `input`:

```
client.set_option(wf_id, 'manual', True)
    → clayd → {"type": "option.set", "key": ..., "value": ...} → the workflow
```

Same socket, same lock, same relay as an answer to a prompt. It is not an
`input.response` with a magic body, because it is not an answer to anything.

### clay ui — four checkboxes

`ask first: [ ] manual  [x] writes  [ ] reads  [x] commands` under the log.
The gates grey out when the master is off rather than clearing themselves: the
arrangement you chose survives being switched off and comes back, and a box
that silently unchecked itself would read as a setting that was lost.

Wired straight to `clay.run.approval` — `clay ui` runs its workflow in this same
process, so there is no relay to cross.

---

## What the prompt looks like

One prompt per action, listing every item, with per-item rejection:

```
applyFileWrites wants to write 3 file(s):

  1. update todo/store.py
     --- todo/store.py (before)
     +++ todo/store.py (after)
     @@ -12,7 +12,7 @@
     -    def add(self, task):
     +    def add(self, task: Task) -> None:
  2. create todo/cli.py
     new file, 48 lines
  3. update todo/task.py
     …

[y] approve all   [n] reject all   or list the numbers to skip, e.g. "2 4"
```

**Numbers are what to skip, not what to keep.** Rejecting one bad command out
of five should not mean typing the other four.

On Telegram the same text arrives with ✅ **Approve all** / ❌ **Reject all**
buttons. Per-item rejection stays free text — typing "2 4" already reaches the
prompt, so no stateful button toggling was needed.

### It fails closed, every time

- an answer it cannot read (`maybe`, `2 or 3`) approves **nothing**
- a number that is not in the list approves **nothing**
- the input channel dropping mid-prompt approves **nothing**

A typo must never be read as consent to write files.

The one exception is an **unattended run** (`daemon`), which auto-approves and
says so on the bus — the same choice `humanShell` has always made, because
there is nobody to ask and hanging forever is worse.

### Skipping one file is not the partial write we just banned

`applyFileWrites` refuses a whole reply when a fence loses its filename. That
rule exists because a *silent* partial write reads as success. A human ticking
off one file is the opposite: chosen, named in a warning, and reflected in
`files_written`. So per-item reject writes the approved subset.

A rejected read is served as `=== path ===\n(not approved — the human declined
this read)`, and a rejected command appears in the transcript as `[skipped: not
approved]`. Neither is silently dropped: a model handed fewer files with no
explanation writes code around what it imagines is there, and a command that
vanished would have the next pass conclude the check passed.

---

## Edits now show a diff

Independent of manual mode — this applies to every run.

```
  ▸ applyFileWrites  files_written
    todo/store.py updated (+7 −3)
    --- todo/store.py (before)
    +++ todo/store.py (after)
    @@ -12,7 +12,7 @@
    ...
    todo/cli.py written (48 lines)
```

- **an edit** draws a unified diff (payload `kind: 'diff'`)
- **a new file** keeps its whole body (payload `kind: 'file'`)

A diff of a new file is every line prefixed `+`, which is strictly noisier than
the file itself, so creation was left alone.

A file changed twice in one reply diffs against **disk**, not against the first
change's result — the intermediate was never on disk and describes a state
nobody can look at.

**It reaches every surface with no renderer change.** No renderer branches on
payload `kind` — only `kind == 'prompt'` is special-cased — so the terminal,
Telegram, `clay attach`, the Qt panel, manager and dashboard all draw it as-is.

---

## Two bugs found while building this

- **`"1"` would have approved everything.** The on/off word lists contain `'1'`
  and `'0'`, and approval answers were checked against them first — so
  answering "1" to skip the first file read as "yes, all of it", and "0" as
  "reject everything". Approval answers now use their own word lists, with no
  digits in them.
- **The read limit notice stopped firing.** Trimming the request list to
  `maxFiles` in place broke `serveFileReads`' "N further read request(s)
  skipped", which counts from the untrimmed list. Caught by an existing test.

---

## Something is always working — the busy indicator

Task doc: `docs/tasks/busy-indicator.md`

### The silence

`"visible": false` suppresses every event a front-end can see. `action.start`,
`action.complete`, `action.skipped` and every payload from `logger.output` are
gated on `logger.visible(action)`; only `action.error` was not. And the terminal
spinner had exactly **one** trigger — an `action.output` of `kind == 'prompt'`,
which is itself gated. So a hidden model call drew nothing at all, for as long
as it took.

Telegram and the Qt panel were worse: they had no indicator whatsoever, hidden
or not. A **visible** `scramda2` posted its prompt and then sat silent for the
whole model call.

### One event, three surfaces

```
busy   active, action_type, preview
```

It is the one event `"visible": false` does not gate, and the only event that
never reaches the run log — a spinner is not a thing that happened, so
`logger.busy()` calls the listeners directly instead of going through `emit`.

`active` is a **level, not a counter**. A second `active=True` is a relabel, so
a listener holding one flag needs no nesting arithmetic.

The dispatcher raises it before every handler and drops it in a `finally`, so a
handler that raises — or an unknown action type, which returns from inside the
`try` — cannot leave three front-ends claiming to be working. Four types are
excluded, because they are not the thing being waited on:

```python
_NO_BUSY_TYPES = {'workflow', 'loop', 'humanDecision', 'humanShell'}
```

Nothing on the transports had to change: the socket bridge relays every event
without a filter, `TelegramBridge.api` is generic, and `WorkflowRunner`'s Qt
signal already queues anything it is handed onto the GUI thread.

### The preview says what you are waiting for

Up to 100 characters, collapsed to a single line — a label containing a newline
breaks its own redraw.

The dispatcher's `busy` can only carry the action **type**, because at dispatch
time `action['prompt']` is still the raw template with `{workspace_files}`
literal in it; substitution happens inside the handler. That is the exact bug
`action.output` was introduced to fix, so it is not reintroduced here. Instead
`logger.output`'s prompt path **re-emits** `busy` with the resolved text, and
the indicator relabels from `scramda2` to the real question.

**This deliberately exposes the first 100 characters of a hidden prompt.** The
prompt body itself still never leaves the log file. This is what makes the
indicator informative rather than a bare dot, and it was chosen knowingly.

### Handing the floor to a human

Every `prompt()` implementation — terminal, socket and queue — drops the
indicator **first**, before the question goes out and before the
closed-channel check. A spinner writing over `builtins.input()` is unusable,
and a Qt panel showing "working" beside a live input row is lying about both.

It sits at the io layer rather than in a dispatcher exclusion list on purpose:
with manual approval, `applyFileWrites` now blocks on a human too, and no list
of action types could have known that.

### Per surface

- **CLI** — the same braille spinner, now driven by `busy` rather than by the
  prompt payload, labelled with the preview truncated to 56 columns.
- **Telegram** — the native *typing…* hint. Telegram expires it after about
  five seconds, so a daemon thread re-sends every 4s, with a 10-minute ceiling
  for a run whose socket dropped and never sent its own `active=False`. Queued
  chat lines are flushed **before** the hint is raised so the ordering reads
  right, and a prompt, a finished run or the bot stopping all drop it.
  `ChatRenderer` names no `busy` case, so it renders nothing — no chat text.

  **A plain conversation gets it too.** A message sent with no workflow running
  falls through to the chat model, which has no engine and no bus behind it and
  so emits no `busy` at all — the wait people sit through most often was the one
  with no indicator. `_on_message` now raises the hint around that call itself,
  in a `try/finally` so a model that times out cannot leave the keepalive
  running for its full ten minutes. It shares the one keepalive with a running
  workflow: a chat turn typed mid-run drops the run's hint on reply, and the
  run's next action raises it again.
- **clay ui** — an animated `QLabel` beside the approval row, cycling the same
  frames on an 80 ms `QTimer`, cleared on run complete, cancel and error.

---

## The `@handler_for` mis-binding

Reported live: `TypeError: diff_body() missing 1 required positional argument:
'label'` out of `dispatcher.py:254`.

A decorator binds to the function on the line immediately below it. Two helpers
had been inserted directly beneath a `@handler_for`, which quietly handed the
registration to the helper:

```
applyFileWrites  →  diff_body(old, new, label)     instead of apply_handler
serveFileReads   →  _refused_reads(action, requested)  instead of serve_handler
```

`serveFileReads` never surfaced because the reads gate ships off, so
`approval.confirm` returned early and the action "succeeded" while serving
nothing. Both decorators were moved onto the real handlers; the other 33
bindings in the tree were checked and are correct.

Nothing caught it because action tests import handlers **by name** — the
registry was never exercised. It now is:

```python
def test_every_handler_takes_action_and_ctx(self):
    """Every entry in _HANDLERS must be callable as handler(action, ctx)."""
```

---

## Approved working directories

Task doc: `docs/tasks/approved-workspaces.md`

### The guard that wasn't there

Every file action refuses a path that escapes its `root` — absolute paths on
sight, `..` collapsed, symlinks resolved, then `relative_to(root)`. Sound, and
it was never the whole story: **nothing bounded the root itself.** It comes
straight out of the workflow file, `{placeholder}`-interpolated from context, so

```json
{"type": "listWorkspace", "root": "~"}
```

was honoured, and every check below it then passed while a whole home directory
was in scope. Because the root is interpolated, context a model produced could
build it.

### One register

```
~/.clay/workspaces.json
```

A root is usable when it is a registered directory or beneath one. Anything
else asks, once:

```
clay wants to use a directory it has not been given access to:

    /Users/me/projects/foo

Approving covers this directory and everything under it.

[y] approve and remember   [o] allow once   [n] refuse
```

Grants are by **subtree** — approving `/Users/me/projects` covers everything
under it — decided by `resolve()` then `relative_to()`, the same primitive the
path guards already use. One escape story rather than two.

**Nothing is approved implicitly, including the directory you launched in.**
That is the decision the whole thing rests on: auto-approving CWD would mean
one `cd ~ && clay run` puts an entire account permanently in scope without ever
drawing a prompt.

`[o]` is session-scoped, never written to the register, gone when the run ends.
Anything unrecognised refuses, **blank included** — a blank line approves
everything at an approval prompt, and that must not carry over to "may clay
have this directory".

### Each directory carries its gates

```json
{"path": "/Users/me/projects/foo",
 "added": "2026-07-30T11:04:12+00:00",
 "gates": {"fileWrites": false, "fileReads": false, "commands": true}}
```

Same keys and the **same polarity** as everywhere else: `fileWrites: true`
means *ask before writing*. Naming them for the inverse sense would have put
one word with two opposite meanings in two files, which is the kind of bug that
reads correctly in review.

They apply on first use of a directory in a session, not on every action — so a
`/manual` toggle typed mid-run is not overwritten by the next file action.

### Unattended runs refuse

```
✕ listWorkspace: /var/data is not an approved working directory, and this run
  has no human to ask. Approve it with:  clay dirs add /var/data
```

Deliberately the opposite of `approval.confirm()` and `humanShell`, which
auto-approve when unattended. Those decide whether an action proceeds inside a
boundary a human already drew; this decides *where the boundary is*, and a
scheduled run must not widen its own reach because nobody was watching.

```
clay dirs list                    every approved directory and its gates
clay dirs add <path>              approve it and everything under it
clay dirs forget <path>           remove one
```

### The default root changed

`"output"` → `"."`. The old default resolved to `$CWD/output`, so the same
workflow wrote to a different place depending on where it was launched, and a
coding workflow read its sources from one directory and wrote to another. It is
now one constant imported by all four modules rather than a copy of the string
in each — which is how they came to disagree.

**A workflow that relied on the default now writes to the launch directory
rather than a subdirectory of it.** One that names its own `root` is unaffected.

---

## Upgrading

```
.venv/bin/python -m clay build
```

No action gained or lost a field. Two behaviour changes to know about, both
from the working-directory register:

- the first run under any directory **asks once** before it can read or write
  there, or `clay dirs add <path>` it up front
- a workflow with no explicit `root` now writes to the launch directory rather
  than `./output` under it

## Verify

```
.venv/bin/python -m clay.tests
.venv/bin/python -m clay lint workflows/system/coding2
```

## Known gaps

- **`clay attach` has no toggle and no spinner.** It renders the same events and
  can answer an approval prompt, but its input loop and its event switch are
  both its own rather than `TerminalIO`/`TerminalRenderer` — so `/manual` is not
  recognised there, and `busy` falls off the end of its if/elif chain unused.
- **The Telegram setting is per bot process, not per chat.** Two chats talking
  to one bot share it.
- **`WorkspaceRoot` still lives only in `file_ops.py`.** The other three file
  modules keep their own copies of the containment code. All four are now
  bounded by the same register, so this is duplication rather than a hole — but
  it is still three places for one rule.
- **`~/.clay` is outside the register.** Memory and skills write there by their
  own paths and take no `root`.
- `clay/daemon/` and `clay/ui/` are still absent from
  `docs/plans/redesign/current.puml`, which covers entry/run/lib/actions. The
  `option.set` protocol is documented on `SocketIO` there; the clayd and Qt
  sides are not.
