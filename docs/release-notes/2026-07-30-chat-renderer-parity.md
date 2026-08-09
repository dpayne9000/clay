# 2026-07-30 — Chat renderer parity, and reply parsing

## Fixed — the prompt shown was never the prompt sent

Every front-end echoed the **raw json template**, with `{mission}`,
`{workspace_files}` and `{transcript}` still literal. The text that actually
reached the model was displayed nowhere — not in the CLI, not in Telegram, not
in the log file.

`dispatcher._action_fields` copies `action['prompt']` onto `action.start`,
emitted before the handler runs; substitution happens inside the handler, at
`scramda2_actions.py:29`. `resolved_prompt` existed for two lines and went
straight to `gopher.fire`, which logs nothing.

The handler now emits it. The uncapped prompt echo added earlier in this
release was, until now, showing the whole of the wrong thing.

## Added — `action.output`, one event for what an action shows a person

```
action.output    id, action_type, kind, label, text
```

`kind` is a stable token — `prompt`, `file`, `command`, `read` — with `label`
the one-line header and `text` the body.

It replaces `logger.info` as the way `applyFileWrites`, `runReplyCommands` and
`serveFileReads` emit their payloads. A `log` event carries only a level and a
string, so a front-end receiving one could not tell a file write from a file
read, and "show writes but silence workspace scanning" was not expressible
without matching on message text.

Now it is data. **This is what a per-front-end visibility list filters on** —
in the chat, `ChatRenderer._output()` is the single place, and its module
docstring carries the map. To keep file writes and commands but drop prompts
and scanning:

```python
if event.get('kind') in ('prompt', 'read'):
    return None
```

The CLI is a separate renderer and is unaffected by anything done there.

Every front-end that drew these payloads got a branch: the terminal renderer,
the chat renderer, and both Qt panels (`ui/dashboard.py`, `ui/manager.py`) —
which drew them through their `log` branch and would otherwise have gone
silently blank. The daemon needed no change; it relays the whole event dict.

Two consequences worth knowing:

- **The spinner moved** from a scramda2 `action.start` to the `prompt` payload,
  which is emitted immediately before `gopher.fire`. It now spans exactly the
  model call, and a scramda2 that returns early spins not at all.
- **`action.start` no longer carries a prompt for any action type**, and
  `action_detail` lost the `omit` parameter that existed to hide it. That event
  fires before the handler substitutes `{placeholders}`, so its prompt was
  always a template. `humanDecision` needed no replacement event: interactively
  the question goes out on `input.request`, and under `--auto` it dispatches a
  real `scramda2` which emits its own. A third copy would have asked it twice.

Details in `docs/tasks/action-output-event.md`.

## Added — `turn_report`, a curated statement of what the turn did

`workflows/system/coding2/iteration.json`, first action in `settle`. A short
first-person report composed from `files_written` and `command_output`: which
files were created or updated, which commands ran, what the output showed. It
is told to report only what it was given — no invented file, command or
outcome, and nothing about what it intends to do next.

It reaches the CLI and the chat with no code change, because `ChatRenderer`
already relays every `scramda2` answer. Cost is one model call per turn.

Nothing else was suppressed: the full event stream still goes to both
front-ends, and the report sits on top of it. `ChatRenderer`'s docstring now
carries a map of which method draws which line, so silencing anything in the
chat is a one-line change in one file — and cannot affect the CLI, which reads
the same events through a separate renderer.

## Changed — writes and commands show their full content

Both actions reported only that something happened. `applyFileWrites` logged a
path; `runReplyCommands` logged `$ command` and kept the output to itself, in
the returned data, where nobody watching the run ever saw it.

Both now emit the whole thing onto the event bus, so the CLI and the chat show
it identically — no renderer changes were needed, because both already relay
`log` events.

- **`applyFileWrites`** — `path written (N lines)` followed by the file's full
  contents, exactly as they landed on disk.
- **`runReplyCommands`** — the command and every line it printed, as **one**
  event. Two commands running back to back cannot interleave, and a front-end
  cannot show a command without its output.

Uncapped by default, with the knob at the definition in each module:

| where | knob |
|---|---|
| file contents | `ECHO_MAX_CHARS` in `clay/actions/core/file_ops.py` |
| command output | `ECHO_MAX_CHARS` in `clay/actions/agent/shell_actions.py` |

`0` means no limit; a positive number of characters caps the echo.

Two things had to follow:

- **`TerminalRenderer._on_log` indents every line**, not just the first. A
  multi-line message previously left its body in column 0.
- **`MessageBatcher` splits oversized messages.** A file echo can be many
  kilobytes in a single `add()`, and Telegram refuses anything over 4096
  characters, so the whole message failed rather than the echo being trimmed.
  `_split()` breaks on line boundaries, and cuts a single over-long line only
  when it exceeds the limit by itself.

## Changed — the coding2 protocol teaches one way to write a file

The `<write_file>` tag paragraph is out of
`workflows/system/coding2/context.json`. It was there as a fallback for a file
whose own content contains a closing fence — and a fallback in a prompt is an
invitation. Models reached for the tag in place of the fence, and each shape
they reached for was another parser bug. The prompt now teaches the named code
fence and nothing else.

The parser still accepts the tag, in every shape, and always will: a model
reaching for it out of pretraining must not be silently dropped. Teaching a
format and tolerating a format are separate decisions and this splits them.

**Known consequence:** a file whose content contains a closing fence has no
form the prompt teaches. The tag was the only way to carry it. If that turns up
in practice the answer is a fence-length escape (````` ```` `````), not
restoring the tag to the prompt.

## Fixed — a bare ``` fence wrote nothing, silently

The fence models emit most often — no language token, the info string on the
body's first line — matched nothing at all:

```
```
python output/coding2/dumdum.py
<<<<<<< SEARCH
=======
def greet_dumdum(name):
    return f"Dumdum, {name}!"
>>>>>>> REPLACE
```
```

`_FENCE_BLOCK` required the language, buying fence pairing at the cost of every
unlabelled block. `has_unwritten_code` iterates the same regex, so the loss was
not even flagged.

- **The fence lines are anchored to a line start** and the match runs opener to
  closer, which buys pairing back and lets the language be optional.
- **New `Fence` class** resolves a block's language, path and body once;
  `parse_changes`, `has_unwritten_code` and `_command_filenames` all read it.
  Each used to re-derive that from the raw match, which is why one regex flaw
  disabled all three at once.
- **An info string on the body's first line is read and stripped** — both
  tokens required, the first from the closed `FENCE_LANGUAGES` set, because
  `import os.path` is a line of Python and not a declaration of the file
  `os.path`.
- **A path alone on the fence line** (```` ```output/d.py ````) no longer has
  its first segment eaten as the language, which used to leave `/coding2/d.py`
  and get the write refused as an escape.
- **Fence bodies are dedented**, as `<write_file>` bodies already were. A fence
  nested under a list item pushed SEARCH/REPLACE markers off column 0, where
  `_HAS_EDIT_MARKERS` stopped seeing them and the markers were written into the
  file as content.

Details, including the pairing trade-off this accepts, in
`docs/tasks/unlabelled-fence-parsing.md`.

## Fixed — `<write_file>` wrote nothing without a `<content>` wrapper

A reply that named its file and showed its whole content produced no files:

```
<write_file><path>hey.py</path>
  # hey.py
  print("Hey fucka you!")
  </write_file>
```

`_WRITE_TAG` required `<content>…</content>`. With the body placed directly
after `</path>` the regex found no match, `parse_changes` returned `[]`, and
`apply_handler` took its "a conversational turn writes nothing" branch. Its one
guard, `has_unwritten_code`, only inspects fences, so the turn was silent — and
the `execute` step then ran `python hey.py` against a file that did not exist.

The workflow json was intact throughout: `apply` / `applyFileWrites` is at
`workflows/system/coding2/iteration.json:71`, before `execute`.

- **`<content>` is now optional** — everything between `</path>` and
  `</write_file>` is the body, wrapped or not.
- **The body is dedented** (`textwrap.dedent`, so only whitespace common to
  every non-blank line goes). A body indented to sit under the tag is layout,
  not content; written verbatim it produced a Python file that raised
  `IndentationError` on its first statement.
- **`has_broken_write_tag()`** warns when a reply opens `<write_file>` and
  parses to no write — unclosed, or with no `<path>` — the same way an unnamed
  fence already warned.

Same principle as the fence and SEARCH/REPLACE work: support the format the
model actually emits. The refusal rule is unchanged — a write still needs an
explicit path, and a filename is never lifted from prose.

Details in `docs/tasks/write-file-tag-parsing.md`.

## Fixed — Telegram showed less than the terminal

Prompt text and action messages appeared in the CLI and never in the chat.
Three causes, all in the front-end's event filter:

- `events.CONTENT` excluded `action.start`, so the chat drew no action lines
  and never echoed the prompt going to the model — it sat silent for the whole
  length of a model call.
- INFO logs were filtered to WARN/ERROR only, dropping every action message the
  handlers emit: `$ python3 flap.py`, `flap.py written`, `flap.py read`.
- `step.start` and `run.cancelled` were excluded as well.

The `humanDecision` question was never affected — it reaches the chat over
`input.request`, not over the content filter.

## Changed

Rendering now lives with the front-ends instead of in the shared event
vocabulary.

- **New `clay/run/renderers/chat.py`** — `ChatRenderer.render(event) -> str |
  None`, the counterpart to `TerminalRenderer`. Handles every event the
  terminal handles and returns `None` for the same draws-nothing cases. Pure
  formatting: no bus, no bridge, no daemon, so it is tested directly.
- **New `clay/run/renderers/detail.py`** — `action_detail()`, previously
  `terminal._detail`. Both renderers share it, so a field added to one cannot
  go missing from the other.
- **New `clay/channels/message_batcher.py`** — `MessageBatcher` coalesces
  relayed lines into whole messages: they go out once the stream is quiet for
  `interval` seconds (1.5) or the buffer passes `max_chars` (3500). This is
  what makes relaying the full event stream affordable in a message thread —
  the reason the events were dropped in the first place.
- **`clay/actions/agent/telegram_actions.py`** — relays through the renderer
  and the batcher. `renderer` and `batch_interval` are injectable. The bot
  flushes before a prompt and before the closing summary so narration cannot
  land after the thing it narrated. Outbound sends now report a transport
  failure through `logger.error` instead of raising on the subscriber's reader
  thread and stopping all further relaying.

## Changed — the prompt echo is uncapped

Both front-ends truncated the outgoing model prompt to 200 characters. Both now
print the whole thing, with its line breaks intact: a truncated prompt hides
exactly the part you need when a model misreads its instructions.

| where | knob | to re-cap |
|---|---|---|
| CLI | `PROMPT_BOX_MAX_CHARS` in `clay/run/termui/themes/default.theme` | set a positive number; `0` = no limit |
| chat | `PROMPT_PREVIEW` in `clay/run/renderers/chat.py` | set a positive number; `0` = no limit |

Both carry a comment saying so at their definition.
`FEATURE_SCRAMDA_INPUT_BOX=false` still hides the CLI box entirely.

The one-line action summary used to repeat the prompt truncated to 80
characters. With the whole prompt printed directly below it, that stub was a
misleading second copy — `action_detail` gained an `omit` parameter and both
renderers pass `('prompt',)` for `scramda2`. Every other action type keeps its
`prompt=` field; `humanDecision` in particular, since nothing else echoes it.

## Removed

- **`events.CONTENT`.** It decided what a user sees — a rendering decision —
  from inside the shared vocabulary module, and had exactly one consumer. A
  comment in its place records why there must not be another.

## Tests

- `clay/tests/actions/test_file_ops.py` — new `UnlabelledFenceTest`,
  `SpilledInfoTest` and `IndentedFenceTest`.
- `clay/tests/actions/test_file_ops.py` — the reported reply verbatim
  (`test_the_reply_that_wrote_nothing`), the optional `<content>` wrapper,
  dedenting (including that inner indentation survives), a new
  `BrokenWriteTagTest`, and an end-to-end
  `test_write_tag_without_content_wrapper_lands_on_disk`.
- `clay/tests/run/test_chat_renderer.py` — per-event rendering, the uncapped
  prompt echo and its restorable cap, and `ParityTest`, which fails if the chat
  renderer draws nothing for an event the terminal renderer draws.
- `clay/tests/run/test_terminal_renderer.py` — new `PromptBoxTest` (the box is
  rich-mode only, so it is driven directly) and `SummaryLineTest`.
- `clay/tests/channels/test_message_batcher.py` — buffering, joining, the
  max-chars early send, automatic flush on a quiet stream, and that a failing
  send does not kill the drain thread.
- `clay/tests/actions/agent/test_telegram_actions.py` — `ContentRelayTest`
  rewritten: action lines and model prompts reach the chat, INFO logs reach the
  chat, lines are batched into one message, and buffered lines land before a
  prompt.

Run with `.venv/bin/python -m clay.tests`.
