# Architecture

This document describes the current runtime. Historical plans and completed
tasks are implementation records, not architecture references.

## Runtime flow

```text
CLI / Qt / Telegram
        |
        v
daemon permission preflight ----> workspaces.json
        |
        v
DaemonClient ---- Unix socket ----> clayd
                                      |
                                      v
                              workflow subprocess
                                      |
                                      v
engine -> preflight -> dispatcher -> action handler
   |                       |
   +---- logger/events ----+----> terminal, Qt, Telegram
```

## Entry surfaces

- `clay/cli.py` parses commands, fixes the project directory, performs the
  advisory model check, and starts local or daemon workflows.
- `clay/ui/preflight.py` displays the Qt daemon-permission prompt.
- `clay/actions/agent/telegram_actions.py` displays the Telegram prompt and
  relays workflow events and replies.
- `clay/daemon/client.py` sends commands to clayd. Commands and event
  subscriptions use separate connections.
- `clay/daemon/server.py` validates daemon requests and starts workflow
  subprocesses in the caller's project directory.

## Daemon permission preflight

Unattended workflows require advance permission to read files, write files,
and run commands in their project directory.

1. `workspaces.daemon_access()` reads the effective grant from
   `~/.clay/workspaces.json`.
2. CLI, Qt, or Telegram shows the directory, missing permissions, and register
   path before clayd starts.
3. `authorize_daemon_workspace()` saves only the missing permissions and reads
   the grant back for verification.
4. The daemon client and server both reject unattended launches that still
   lack permission.

An attended workflow may ask when an action first needs a directory. An
unattended workflow cannot add a directory by itself.

## Execution core

- `clay/run/engine.py` owns root-run setup, workflow loading, preflight, step
  order, result storage, and cleanup.
- `clay/run/preflight.py` performs blocking checks required to run a workflow.
- `clay/run/dispatcher.py` resolves action fields, validates the action, builds
  its context, calls the registered handler, and emits lifecycle events.
- `clay/actions/registry.py` is the source of truth for action schemas and
  handlers. Action modules register both with decorators.
- `clay/lib/context.py` applies `includedData` and nested key selection.
- `clay/run/failure.py` defines `WorkflowFailure`, the expected run-failure
  signal used by the CLI and clients.

Workflow state is a dictionary. `defaults` are loaded first; caller-provided
`initial_data` wins on the same key. A normal action result is stored under its
`id`. A result with `merge: true` merges its data into the workflow state.

## Events and interfaces

The engine and dispatcher do not draw interface output directly. They emit the
event names defined in `clay/run/events.py` through `clay/run/logger.py`.

- `clay/run/renderers/terminal.py` renders CLI output.
- Qt consumes daemon events through its manager and panels.
- Telegram consumes the same daemon events and renders chat messages.
- Prompt answers return through `input.response` on the workflow event socket.

## Model configuration

`clay configure`, also available as `clay config`, writes `provider.url`, the
`models` profile map, and the default `maxTokens` response limit atomically to
`~/.clay/config.json`. The value must be a positive integer.

`scramda2` uses `maxTokens` when an action omits `max_tokens`. An action-level
`max_tokens` value takes precedence. New installations seed `maxTokens` with
`4096`; upgrades add the key without replacing existing user settings. A
read-only older config remains usable because runtime lookup also supplies the
built-in default.

At CLI startup, `clay/lib/config_check.py` performs an advisory check. It uses
`GOPHER_URL` when set, otherwise `provider.url`, reads `/v1/models`, and checks
every configured model profile. The advisory never blocks unrelated commands.
Workflow execution has a separate blocking preflight.

## Shell actions

`clay/actions/agent/shell_actions.py` executes one argv with `shell=False`.
The executable must be in the code-owned allowlist. Shell operators,
redirection, substitution, newlines, and dangerous `find` flags are refused.
Placeholder values are quoted as one argument. Every accepted command still
passes through the approval gate.

Development executables such as Python, Node, npm, make, git, and pytest are
powerful commands, not a sandbox. The project directory controls where they
start, not everything they can access.

## Canonical references

- Current class/module diagram: `docs/plans/redesign/current.puml`
- Workflow schema: `docs/documentation/02-workflow-schema.md`
- Generated action schema: `docs/documentation/action-reference.json`
- Active defects: `docs/bugs/README.md`
- Active tasks: `docs/tasks/README.md`
