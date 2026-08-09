# 2026-07-29 — Event-bus output refactor

Spec: [event-bus-output-implementation.md](../tasks/completed/event-bus-output-implementation.md)
Fixes: Telegram showed `Started "…" (wf-0002)` and then nothing — workflow
output never reached chat front-ends.

## What changed

**The engine never prints.** Every `termui` call in `engine.py` and
`dispatcher.py` is replaced by `logger.emit(...)`. The vocabulary lives in the
new `clay/run/events.py` — including `input.request` / `input.response`, so
`io.py` and `server.py` no longer retype wire strings.

**New `clay/run/renderers/terminal.py`.** `TerminalRenderer` subscribes to the
bus and draws what the engine used to print — banners, step headers, action
lines, the scramda2 prompt echo, spinner, and answer. The CLI attaches it in
`run` and `dryrun`; a clayd-managed run (`--events-socket`) attaches nothing
and the events travel the socket instead.

**`logger.info/warn/error` emit `log` events** instead of printing, so errors
reach every front-end. Listener fan-out (`_notify`) reports a raising listener
to stderr and continues instead of swallowing it.

**Action events carry `action_type`** (the event's own name stays `type`).
Consumers updated: `ui/manager.py`, `ui/dashboard.py`, `daemon/server.py:339`
(which would otherwise have shown `action.start:id` as the current action).

**Auto-mode humanDecision answers are visible.** The auto branch of
`human_decision.py` now dispatches a real scramda2 action instead of calling
the model privately, so the call emits standard lifecycle events, gains the
handler's 10× gopher retry, and renders in every front-end. Prompt text is
brace-escaped through the nested dispatch so JSON in accumulated context
survives `format_map`.

**Telegram relays content.** `_on_workflow_event` sends scramda2 answers,
`action.error` / `run.error`, and WARN/ERROR logs to the chat; progress
announcements are ignored. The closing summary comes from what was relayed
(`ActiveRun.output`) — `client.tail()` is gone from that path since stdout is
now empty. `clay daemon attach` gained the same content branches.

## Tests

- `tests/run/test_event_emission.py` — event sequences, payload fields,
  `_notify` robustness, log-file ordering of `run.complete`, `_action_fields`,
  auto-humanDecision on the bus, brace-escape survival.
- `tests/run/test_terminal_renderer.py` — synthetic sequences reproduce the
  terminal look; every terminating event stops the spinner.
- `tests/run/test_io_roundtrip.py` — input.request/response round-trip over a
  real socketpair, asserted against the events constants.
- `tests/daemon/test_server_events.py` — `current_action` uses `action_type`;
  prompt broadcast; workflow wrapping.
- Updated: `test_terminal_output.py` (renderer attached in `_capture`; the
  auto answer is now asserted **visible**), `test_core.py` (bus listeners
  instead of `print` mocks), `test_human_decision.py` (patch `gopher.fire`,
  not the deleted `_call_scramda2`), `test_telegram_actions.py` (new
  `ContentRelayTest`; finish summary no longer tails stdout).

Run: `.venv/bin/python -m clay.tests`
Manual check: `.venv/bin/clay run workflows/templates/skunkworks/socratic-tutor/main.json`

## Not covered

- No Qt widget test for the dashboard scramda2 branch (needs a QApplication);
  covered by the manual check.
- `docs/plans/redesign/current.puml` updated alongside.

---

# 2026-07-29 — coding2 conversational workflow + workspace protocol

Spec: [coding2-conversational-workflow.md](../tasks/completed/coding2-conversational-workflow.md)

**New workflow `workflows/system/coding2/`** (main.json, iteration.json,
goal.json, context.json, training.json) — a conversational session that asks
"what can I do for you?", recalls and saves memories in the `system-coding2`
namespace, converses via scramda2, reads the code that already exists, and
writes complete code files under `output/coding2/`. Session ends when the user
says quit/done/bye (loop `continueKey`).

Organised on the `workflows/registry/` blank: `goal.json` holds the mission,
`context.json` the file-tag protocol and workspace root, `training.json` the
few-shot examples, `iteration.json` the turn. The protocol is written once and
interpolated into both model passes rather than restated in each prompt.

**New action module `clay/actions/core/file_ops.py`** — one workspace protocol
in the models' own convention (`<read_file>` / `<write_file>` tags, as
DeepSeek R1 and Qwen are trained on), three actions sharing `WorkspaceRoot`:

- `listWorkspace` — sorted root-relative paths; missing directory is not an
  error.
- `serveFileReads` — answers the model's read requests as `=== path ===`
  blocks; a missing file is reported inline, not fatal.
- `applyFileWrites` — validates every path before writing anything, so a bad
  block writes nothing.

`root` supports `{placeholder}` interpolation on all three, so a workflow
declares its workspace once in context and every action says
`"root": "{workspace}"` rather than repeating the literal path.

Because all three resolve through one `WorkspaceRoot`, a path the listing
prints is a path reads accept. Turn cadence is think → serve reads → act, so
the model reads and writes within a single turn.

**`shell` gains `find`, behind an argument guard.** `_executables_in`
whitelists only the first token of each segment, so `find . -exec rm -rf {} ;`
would have passed as `find` with `rm` unexamined. New `BLOCKED_ARGUMENTS`
(`-exec`, `-execdir`, `-ok`, `-okdir`, `-delete`, `-fprint`, `-fprint0`,
`-fprintf`, `-fls`) is checked against every token of the resolved command,
catching flags that arrive through `{placeholder}` interpolation too.

`serveFileReads` and `applyFileWrites` now log `<path> read` / `<path> written`
per file through `logger.info`, so the events reach the terminal renderer and
every other front-end on the bus rather than a bare print.

**New action `runReplyCommands`** (`clay/actions/agent/shell_actions.py`) —
runs the ```` ```bash ```` blocks a model writes. Previously a model that
finished with *"here's the command to run it"* wrote a command nobody
executed.

The `shell` handler's validation and execution were extracted into
`refusal_for(command)` and `execute(command, timeout, cwd, include_stderr)`,
and `runReplyCommands` calls the same two — the whitelist and
`BLOCKED_ARGUMENTS` checks exist in exactly one place, which matters most here
because these commands come from model output. Guards: `maxCommands` (default
5) refuses the whole block rather than running a prefix; `cwd` interpolates
unquoted through the new `_PlainMap` (a subprocess argument, not a command
string) and a missing directory is reported, never created; a refused command
is recorded as `[refused: …]` and the rest still run. Output is folded into
the transcript so the model sees its own traceback next turn.

**Bug fix — braces in a shell command no longer kill the run.** The `shell`
handler resolved `{placeholder}` with `str.format_map`, which raises
`ValueError: Format string contains positional fields` on `{}`. Shell syntax
is full of braces that are not placeholders — `{}` in `find -exec`, `${VAR}`,
`{1..3}` — so `find . -exec rm -rf {} ;` crashed the action instead of being
refused by `BLOCKED_ARGUMENTS`: a security guard unreachable behind a parse
error. Substitution is now a regex over named identifiers only
(`_interpolate`, replacing `_SafeMap`/`_PlainMap`), leaving every other brace
untouched. Values are still `shlex.quote`d for command strings and passed raw
for subprocess arguments such as `cwd`; an unknown key is still left as
written.

**`ALLOWED_COMMANDS` gains a dev toolchain**: `python3`, `python`, `node`,
`pytest`, `npm`, `make`, `git`. Unlike every other entry these are not
read-only and cannot be made so by any argument guard — `python3 -c '...'` is
arbitrary code execution by construction. This is a deliberate decision: a
coding workflow that cannot run the code it just wrote is not a coding
workflow. `cwd` bounds where they run, not what they can do. Because the
frozenset is global, this widens the plain `shell` action for every workflow
in the repo, not only coding2.

`writeFileSet` is unchanged and retained — the manifest module remains the
right tool for a model that emits a manifest; coding2 just speaks tags.

**New action `appendTranscript`** (`clay/actions/agent/transcript_actions.py`)
— folds each turn into a rolling transcript key carried across loop
iterations (the loop keeps only one iteration of memory by design), capped
at `maxChars` with whole-turn trimming.

**New action `writeFileSet`** (`clay/actions/core/write_file_set.py`) — the
model outputs `{"files": [{"path": …, "content": …}]}`; the action validates
every path (relative, confined to `root`) before writing anything, and an
empty manifest is a successful no-op. Replaces the old `coding` workflow's
pattern of executing a model-written Python script to create files.

Tests: `clay/tests/actions/test_file_ops.py`,
`clay/tests/actions/test_transcript_actions.py`,
`clay/tests/actions/test_write_file_set.py`,
`clay/tests/actions/agent/test_shell_actions.py` (`TestBlockedArguments`,
`TestRefusalFor`, `TestExecute`, `TestParseCommands`, `TestRunReplyCommands`).

Run: `.venv/bin/python -m clay.tests`
Lint: `.venv/bin/clay lint workflows/system/coding2`
Session: `.venv/bin/clay run workflows/system/coding2/main.json`
Optional: `clay build` to refresh the cached `~/.clay/schema.json` with the
new action schemas.

**Regression fixed — ```bash support stopped files being written.** Adding the
bash-fence section to coding2's protocol ended it with a fenced block, and the
model generalised that fences are how code is emitted: it replied with a
```python block and prose telling the user to save the file, so
`applyFileWrites` found no `<write_file>` tags and wrote nothing, then the
command ran against a missing file. Step order was never wrong — `apply` runs
before `execute`. **Resolved by making the fence the write form** rather than suppressing it —
telling a coding model never to use a code fence spends prompt budget fighting
its strongest habit, and leaves every turn one lapse away from silently
producing nothing.

`applyFileWrites` now accepts a fence that names its file, on the fence line
(`​```python pkg/module.py`) or as a first-line `#` / `//` / `--` / `;` path
comment, which is stripped from the content. `_looks_like_path` requires a
separator or an extension and no whitespace, so `# draw the finger` stays
prose. `SHELL_LANGUAGES` are never writes — they are commands, and that set
must stay in step with `_FENCE` in `shell_actions.py`, since a language in
both would be written *and* run. `parse_changes` returns tags and fences
interleaved by position.

A fence naming no file is still not written: the only remaining clue is prose,
and a filename lifted from a sentence creates a real file under a name the
user never chose. `has_unwritten_code()` warns and names both ways to fix it.

`<write_file>` is retained and still parses — a fence cannot carry content
containing its own closing fence — but is no longer the taught form; it is
mentioned once as the escape hatch. `training.json`'s write examples are now
fences, including the write-then-run pairing that was missing.

**New — aider/Cline SEARCH/REPLACE edits.** The model replied with an edit
block, which exposed a defect: a *named* fence carrying those markers would
have written `<<<<<<< SEARCH`, `=======` and `>>>>>>> REPLACE` into the file as
literal content. The format is now supported instead of suppressed.

A change is an object rather than a `(path, content)` pair —
`FileChange.apply(existing)`, with `WholeFile` and `SearchReplace`
implementations. `applyFileWrites` resolves every path *and* derives every
file's new contents before writing anything, so an edit that does not match
leaves the workspace untouched instead of half-applied. Two changes to one
file compose: the second sees the first's result, not the stale copy on disk.

`SearchReplace` requires its search text to appear exactly once — zero matches
means the model is editing a file it never read, several means the edit does
not say which it meant — and raises `EditError` with a message telling it what
to do instead. An empty SEARCH side creates the file. Output is now `CREATED:`
or `UPDATED:` per path.

**Two more ways to name a fence.** A bare filename on the line *above* the
fence (aider's own convention). And one inference: exactly one unnamed code
fence plus exactly one filename across the reply's shell commands means that
fence is that file — `python flap.py` under a lone unnamed block. A second
unnamed fence or a second filename refuses. The attribution is logged, since a
file appearing under a name the model never typed should not be silent.

**Clarification, no code change:** commands never depended on writes. The
`execute` step runs unconditionally and `runReplyCommands` fires on any bash
fence. The protocol wording ("it runs after your files are written") implied a
condition and has been reworded to describe ordering only. The acting-pass
prompt also now says a `<read_file>` tag emitted in that pass is not answered
until the next turn, closing the one place a read could be silently dropped
while the turn's commands ran.

## Test maintenance from the event-bus migration

Three tests still asserted against pre-bus mechanisms and were failing. The
production code is correct in each case; the tests were updated, not the code.

- `test_workflow_actions.test_cycle_warning_printed` captured `builtins.print`,
  but `workflow_actions.py:28` emits `logger.warn`. Renamed
  `test_cycle_warning_emitted` and asserts on bus `log` events via the existing
  `_EventLog` helper.
- `test_run_from_data` and `test_workflow_io` patched
  `human_decision._call_scramda2`, a helper that no longer exists — auto mode
  now dispatches a real `scramda2` action so the model call rides the bus.
  Both now mock at the connector, `patch.object(scramda2_actions.gopher,
  'fire')`, matching the pattern already used in `test_core.py`.

## Correction recorded

[fewshot-role-claim-correction.md](../tasks/fewshot-role-claim-correction.md)
— during this design I reported a bug in `connectors/gopher`'s few-shot path,
claiming its emitted `prompt`/`completion` roles violated the connector's own
allowed-role set and were silently breaking every workflow's examples. That
was false: the set in question validates *caller-supplied* examples and is not
an output contract, and `prompt`/`completion` is a documented input idiom of
that library. Nothing in the submodule was changed. One narrow untested
question is recorded there.
