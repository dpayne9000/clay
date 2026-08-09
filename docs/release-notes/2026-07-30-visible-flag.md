# 2026-07-30 — `"visible": false`, and payloads from memory and skills

Task doc: `docs/tasks/visible-flag-and-memory-skill-output.md`

## Any action can be hidden

Add `"visible": false` to an action and it **disappears entirely** from every
front-end — no start line, no result line, no file/command/prompt payload:

```json
{ "id": "bookkeeping", "type": "writeMemory", "visible": false, ... }
```

Two things are never hidden:

- **`action.error`** — an action you chose not to watch is still one you have
  to be told about when it fails.
- **the log file** — `logger.emit` gained a `show` keyword that gates
  listeners only, so the full run record survives. Hiding an action is a
  decision about a screen, not a licence to lose the evidence.

A `humanDecision` is likewise unaffected: its question travels through
`clay/run/io.py`, not the event emit, because a hidden question is one nobody
can answer.

Omitting the field means visible, so every existing workflow is unchanged.
`"visible": "false"` (the string, a plausible slip in hand-written json) is
parsed, not passed to `bool()`, and hides as intended — as do `"no"`, `"off"`,
`"0"` and `""`.

This is per-action only. There is no workflow-level default and no allow-list:
one concept, read in one place, `logger.visible()`.

## Memory and skill actions now show their work

Eight handlers that previously logged a one-line summary now put the real
thing on the bus as `action.output`:

| action | shows |
|---|---|
| `writeMemory` | path, tag count, and the entry json as written |
| `writeSkill` | path, line count, and the file contents |
| `removeSkill` | the path removed |
| `readMemory` | path, and the formatted entry |
| `searchMemory` | namespace, hit count, query, and the matches |
| `listMemory` / `listSkills` | folder, count, and the listing |
| `searchSkills` | folder, count, query, and the ranked list |

Reads carry their **full contents**, not a count, because that text is what
lands in context and, downstream, in a model prompt.

Writes serialise once and both write and show the same string, so what a
front-end draws cannot disagree with what is on disk.

A `writeMemory` with a `skillset` writes twice; the second write now inherits
the parent's `id`, `type` and `visible`, so payloads stay attributable and a
hidden `writeMemory` cannot leak through its skill half.

## One truncation cap

`ECHO_MAX_CHARS` / `_echo()` existed in both `file_ops.py` and
`shell_actions.py`, and memory plus skills would have made four copies. Both
are gone. The cap is now `clay/run/logger.py:OUTPUT_MAX_CHARS`, applied inside
`logger.output`, and covers every payload on the bus. Default `0` — uncapped,
as before. The label is never truncated: it is the header that tells you which
file a shortened body belongs to.

## Also

- `clay/lint.py` accepts `visible` as a universal field, alongside `type` and
  `includedData`.
- The JSON Schema declares it once, in `$defs.universalFields`, rather than in
  all 39 per-type schemas — `registry.py` warns that the export is pulled
  verbatim into model prompts, and 39 copies would have added ~5k characters
  to a 27k payload for one boolean.

## Upgrading

Regenerate the schema so models can use the field:

```
clay build
```

Run the suite:

```
.venv/bin/python -m clay.tests
```
