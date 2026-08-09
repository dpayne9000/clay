# 2026-07-30 — the outgoing prompt is capped from config.json

Task doc: `docs/tasks/prompt-cap-from-config.md`

## What changed

The prompt going **to** the model is now cut to a character limit you set in
one place. The model's **answer** is never cut, by this or anything else.

```json
"display": {
    "promptMaxChars": 2000
}
```

in `~/.clay/config.json`. `0` means uncapped — the behaviour before this
change.

Over the limit, the CLI and Telegram both show the head of the prompt and then:

```
… 25412 more characters — full prompt in the run log
```

which is literal. `logger.output` writes to the log file before any renderer
sees the event, so this hides text from a screen and never from the record.

## Why only the prompt

They are two different events, so this is a change to one of them rather than
a filter over text:

- the prompt is `action.output` with `kind == 'prompt'` — for a coding
  workflow, the mission, protocol, workspace listing and whole transcript,
  resent on every single turn
- the answer is `action.complete` with `action_type == 'scramda2'` — the
  result of the run, and a truncated one is the work thrown away

## Existing installs get the cap

`create_user_config()` only writes `~/.clay/config.json` when it is missing,
so an existing file is never back-filled with the new key. Treating "absent"
as "uncapped" would have meant this change did nothing for anyone who has run
clay before. Instead the key falls back to a baked-in `2000` and says so, once
per process:

```
config: display.promptMaxChars not set in ~/.clay/config.json — using 2000
```

Add the `display` block to your config to silence it and choose your own
number.

## Two old knobs removed

There were already two caps, in two formats, both defaulting to `0`:

| removed | was in |
|---|---|
| `PROMPT_BOX_MAX_CHARS` | `clay/run/termui/themes/default.theme` |
| `PROMPT_PREVIEW` | `clay/run/renderers/chat.py` |

Setting a limit meant two edits in two files, and drift between them was
silent. A theme styles output; it does not decide how much of a prompt you may
see. Both are replaced by one `prompt_body()` helper in
`clay/run/renderers/detail.py`, called by the terminal and the chat, so a
terminal and a Telegram chat watching the same run now see the same prompt.

**If you had set `PROMPT_BOX_MAX_CHARS` in a custom theme, it no longer does
anything** — move the number to `display.promptMaxChars`.

## Every surface, not just the CLI

The cap applies to `clay`, `clay ui` (log panel, manager and dashboard),
`clay attach` and Telegram. The Qt and attach surfaces all draw payloads
through `payload_lines()`, so the cut lives there as well as on the terminal's
own prompt-box path — one setting, same result everywhere.

Only prompts are cut. A file's contents, a command's output and a read's
result are drawn whole, as is the model's answer.

## Verify

```
.venv/bin/python -m clay.tests
```
