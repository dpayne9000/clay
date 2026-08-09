# Release notes — unified workflow I/O and telegram control channel

Date: 2026-07-29
Previous file:
[2026-07-28-workflow-skeleton-generator.md](2026-07-28-workflow-skeleton-generator.md)
(committed in `0e2dcbe`), so this file starts fresh.

Implements [telegram-action-redesign.md](../tasks/telegram-action-redesign.md)
and its design companion
[telegram-action-redesign-design.md](../tasks/telegram-action-redesign-design.md).

## 1. The bug this started from

`clay/actions/agent/telegram_actions.py:19` built the Telegram bridge at
**import** time:

```python
bot = TelegramBridge(os.environ["TELEGRAM_BOT_TOKEN"] or "")
```

`clay.actions.registry.discover()` imports every action module on every
command and every workflow run, so a missing `TELEGRAM_BOT_TOKEN` raised
`KeyError` and took down the whole app — not just workflows using Telegram.
The `or ""` was dead code (the subscript raises before it evaluates), and an
empty token would have failed anyway in `TelegramBridge.__init__`. The
`if not bot: return` guard in the handler was also dead — the bridge is always
truthy.

Verified fixed: `discover()` now completes with the variable unset.

## 2. New: one input channel for every workflow (`clay/run/io.py`)

Previously a workflow reached its human over three ad-hoc channels: a
**write-only** events socket, `__WEB_INPUT__` stdout markers, and the raw
stdin pipe — with the marker path gated behind a `WEB_MODE` env var that only
`humanDecision` honoured and only `run-json --no-auto` ever set.

That is replaced by a single interface with two implementations, selected by
launch mode rather than an env var:

| Situation | Channel | Transport |
|---|---|---|
| `clay run` in a terminal | `TerminalIO` | `builtins.input` |
| clayd-managed (`--events-socket`) | `SocketIO` | JSON lines over the events socket |

The events socket is now **bidirectional**:

```
workflow → clayd   {"type": "input.request",  "id": ..., "prompt": ...}
clayd → workflow   {"type": "input.response", "id": ..., "text": ...}
```

`SocketIO` runs one reader thread, matches responses to the waiting prompt by
id (falling back to the single outstanding prompt when ids drift), and shares
a send lock with the logger's event writer so two threads cannot interleave
halves of a JSON line. If the socket drops while a prompt is outstanding it
raises `ChannelClosed` — a workflow that can no longer reach its human fails
loudly instead of hanging forever.

## 3. WEB_MODE and the stdout markers are gone

- `clay/cli.py` no longer sets `WEB_MODE`; `clay/actions/human_decision.py` no
  longer reads it, and its marker branch is deleted in favour of
  `io.get().prompt(...)`.
- `clay/daemon/server.py` no longer parses `__WEB_INPUT__` /
  `__END_WEB_INPUT__` from stdout; `_process_stdout_line` is now one line and
  stdout carries logs only. `WorkflowProc` loses `in_web_input` /
  `web_input_lines` and gains `event_conn` / `event_conn_lock`.
- `send_input()` writes an `input.response` down the workflow's event socket
  instead of its stdin pipe, and returns False (with a log line) when there is
  no event connection rather than failing silently.
- `_handle_engine_event()` turns an `input.request` into the same `prompt`
  event clients already consume, so **the client-facing daemon protocol is
  unchanged and the Qt UI needs no changes**.

Side effect worth noting: file-based non-auto workflows run under clayd could
not surface prompts at all before (no markers were emitted on that path), so
this fixes prompting for the Qt UI too, not only for Telegram.

## 4. `humanShell` approval is no longer terminal-only

`clay/actions/agent/human_shell_actions.py` drew the proposed command in a
box-drawing block printed to **local stdout**, then asked the bare question
through `input()`. A remote approver would have seen "[Y]approve / [n]reject"
with no idea what they were approving. The command now travels inside the
prompt text through the same channel.

**This changes local terminal appearance** — the ASCII box is gone, replaced
by an indented command line. Behaviour (approve / reject / edit, and the
whitelist re-check on an edited command) is unchanged.

## 5. `ensure_daemon()` moved into the daemon client

`_ensure_daemon` lived in `clay/cli.py`. The telegram action needs it too, and
an action importing `clay.cli` would invert the dependency, so it now lives in
`clay/daemon/client.py` as `ensure_daemon()`, alongside a small
`daemon_running()` helper. `clay/cli.py` delegates to it; logic is unchanged.

## 6. `telegram` action rewritten

The bot is now a clayd front-end — a peer of the Qt UI — and runs no workflows
itself:

```
Telegram chat ↔ TelegramWorkflowBot ↔ clayd ↔ workflow subprocess
                (DaemonClient + EventSubscriber)
```

- **Import-safe.** The module only defines things; the token is read and the
  bridge built inside the handler. A missing token raises
  `ValueError('telegram action requires TELEGRAM_BOT_TOKEN — ...')` for that
  run only, matching the convention in `email_actions.py:54`.
- **Menu comes from the action**, not from code. New optional `workflows`
  param: `[{"label": "...", "path": "workflows/.../main.json"}]`. Adding a
  workflow to the panel is a JSON edit. Buttons carry `wf:<index>` callbacks
  because Telegram caps `callback_data` at 64 bytes, so paths cannot be
  embedded. Malformed entries raise at startup rather than silently vanishing
  from the menu.
- **One workflow at a time** (single admin chat, by design): a second launch
  answers `"<label>" is already running. Cancel it before starting another.`
- **Prompt relay**: clayd `prompt` events go to the chat; the next chat
  message is returned to clayd as that workflow's input. With nothing pending,
  messages fall through to the chat model as before.
- **On finish**: status, non-zero exit code, and the last 20 stdout lines via
  `DaemonClient.tail`.
- **Shutdown**: handles SIGTERM (clayd `stop` sends it) and `KeyboardInterrupt`,
  stopping the subscriber and the bridge.

Deleted: the import-time bridge, the `pending` / `pending_lock` module
globals, the per-chat `engine.run` threads, the hard-coded menu handlers, and
the `builtins.input` monkeypatch. That monkeypatch was also a latent bug —
two concurrent workflows would each capture the other's patch as
`original_input` and restore in the wrong order.

## 7. Tests

New:
- `clay/tests/integration/test_workflow_io.py` — drives the real `SocketIO`
  over a `socket.socketpair()` standing in for clayd: request/response
  round-trip, id-drift delivery, non-JSON and unrelated events ignored,
  duplicate prompt id rejected, dropped channel raises instead of hanging,
  and `humanDecision` routing through both channels.
- `clay/tests/actions/agent/test_telegram_actions.py` — 25 tests over fakes
  for the bridge, daemon client, and event subscriber; no network, no daemon.
  Covers the import-safety regression, menu construction from action params,
  the 64-byte callback budget, launch/reject/cancel/status, prompt relay, and
  finish reporting.

Changed:
- `clay/tests/integration/test_web_mode.py` — **deleted**. Every test in it
  patched `hd_mod.WEB_MODE` to exercise a protocol that no longer exists; its
  guarantees (prompt id, resolved placeholders, response handling, auto-mode
  priority, placeholder preservation) are carried over to
  `test_workflow_io.py`.
- `clay/tests/integration/test_run_json_cli.py` — the two WEB_MODE env
  assertions are replaced by one asserting `run_json` sets no env flags at all.

Existing tests that patch `builtins.input` (`test_human_decision.py`,
`test_human_shell_actions.py`) still exercise the terminal path unchanged,
since `TerminalIO` calls `input()`.

Commands for the user to run directly:

```
python3 -m unittest clay.tests.actions.agent.test_telegram_actions -v
python3 -m unittest clay.tests.integration.test_workflow_io -v
python3 -m clay.tests            # full suite
```

## 8. Three suite failures fixed

Running the full suite after the work above surfaced three failures unrelated
to Telegram. All three are fixed.

### `discover()` did not honour its own ordering contract (real bug)

`discover(force=True)` calls `importlib.import_module()` for every action
module, but that call does nothing when the module is already in
`sys.modules`, and the `@action` decorators only run on a module's first
import. Registration order was therefore first-import order, not the sorted
walk order the docstring promises. Anything importing an action module
directly before `discover()` — a unit test, for instance — pulled that
module's types to the front of `_REGISTRY`.

That order is not cosmetic: `all_schemas()` iterates `_REGISTRY`, and
`export_json()` output is pulled into model prompts by the editor and coding
iteration workflows.

Fix: new `_apply_module_order()` in `clay/actions/registry.py`, called at the
end of `discover()`. It sorts `_REGISTRY` by position in the module walk list.
The sort is stable, so types from the same module keep their definition order
and types registered from outside the walk (test throwaways) keep their
relative position at the end.

Caught by `test_registry.TestDiscoveryOrderStable.test_order_is_alphabetical_by_module`.

### `test_skeleton.py` throwaway class had invalid field order

`TestActionFieldExclusion` declared `hidden` (a `req()` field, no default)
after `visible` (an `opt()` field, has a default). `dataclass()` rejects that,
so the class raised `TypeError` at `registry.py:56` during `setUp`. Both
`req()` fields now precede both `opt()` fields; the assertions are unchanged.

### `test_training.py` asserted a mechanism that does not exist

`test_each_scramda2_prompt_contains_training_template_variable` required every
scramda2 `prompt` string to contain its `{training_*}` placeholder. Training
data does not travel through the prompt. `loadContext` merges `training.json`
into `previous_data`; `dispatch()` calls `_resolve_action_fields`
(`dispatcher.py:64-68`), which replaces `{"override": "training_key"}` on the
`examples` field with the real list; the handler passes that list to the model
as `examples=` (`scramda2_actions.py:45`). No prompt in any of the three
pipeline files carries such a placeholder, so the test failed for all 13
mapped actions and merely stopped at the first.

Replaced by `test_each_scramda2_action_receives_its_training_examples`, which
tests the real path end to end: it builds the context by running the
pipelines' own `load_training` step through `engine.process_steps`, resolves
each mapped action the way `dispatch()` does, and asserts the resolved
`examples` equals the training list and is non-empty. It also asserts each
mapped action id is actually present in its pipeline — the previous lookup
would have passed vacuously if `PIPELINE_KEY_MAP` and a pipeline drifted apart.

This differs from the existing `TestTrainingExamplesWiring` tests, which feed
`_resolve_action_fields` the raw `training.json` dict and so never exercise
`loadContext`.

## 9. What is not done

- Not committed to git this session.
- `test_web_mode.py` deletion is staged in the working tree only.
- No end-to-end run against a live Telegram bot or a live clayd has been
  performed — the socket round-trip was verified in isolation over a
  `socketpair`, and the daemon-side wiring is covered by reading, not by an
  integration run.
- `docs/plans/redesign/current.puml` updated for the new classes; the
  `assessment.md` / `plan.md` documents were not touched.
