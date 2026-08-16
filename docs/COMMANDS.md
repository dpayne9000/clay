# Clay command reference

This document lists the commands currently registered by `clay/cli.py`.
Commands shown in older plans but absent here are not available.

## General syntax

```text
clay [GLOBAL OPTIONS] COMMAND [COMMAND OPTIONS]
```

Running `clay` without a command starts the workflow selected in
`~/.clay/startup.json`.

### Global options

| Option | Purpose |
|---|---|
| `-h`, `--help` | Show top-level help. |
| `--version` | Print the installed Clay version and exit. |
| `--daemon` | Run unattended: AI answers human decisions and Clay uses advance approval settings. |
| `--plainStdout`, `--ci` | Disable ANSI colors and animations. |
| `--theme PATH` | Load a terminal `.theme` file. `CLAY_THEME` provides the same setting. |
| `--project-dir PATH` | Set the project directory used by workspace file and command actions. The default is the current directory. |

Global options belong before the command. Options documented under a command
belong after that command.

## Naming workflows

Commands that accept a workflow support two mutually exclusive forms.

Search by segments:

```bash
clay run workflows system editor3
```

Clay searches the user workflow folder first, then workflows shipped with the
application.

Use one exact file or directory without searching:

```bash
clay run -f ./workflow/main.json
clay run -f ./workflow
```

A directory resolves to its `main.json`. Do not combine segments with `-f`.

## `clay create`

Interactively create one basic workflow JSON file.

```text
clay create WORKFLOW_NAME
```

If the name does not end in `.json`, Clay adds the extension. The command asks
for step names and actions and asks before overwriting an existing file.

## `clay run`

Run a workflow in the current process.

```text
clay run [SEGMENT ...]
clay run -f PATH
```

| Option | Purpose |
|---|---|
| `-f PATH`, `--file PATH` | Run an exact workflow file or directory. |
| `--auto` | Replace `humanDecision` prompts with model-generated answers. |
| `--events-socket PATH` | Send JSON-line workflow events to a Unix socket. Used by application interfaces. |
| `-v`, `--verbose` | Show the complete event stream, including prompts, skipped actions, and informational messages. |

## `clay dryrun`

Load a workflow and display its dry-run action sequence without executing the
workflow actions.

```text
clay dryrun [SEGMENT ...]
clay dryrun -f PATH
```

| Option | Purpose |
|---|---|
| `-f PATH`, `--file PATH` | Inspect an exact workflow file or directory. |
| `-v`, `--verbose` | Show the complete dry-run event stream. |

## `clay workflows`

List workflows Clay can resolve.

```text
clay workflows [TERM] [--paths]
```

| Argument or option | Purpose |
|---|---|
| `TERM` | Show only references containing this text. |
| `--paths` | Print each resolved filesystem path. |

Results are grouped into user workflows and workflows shipped with Clay.

## `clay default`

Show or change the workflow started by bare `clay`.

```text
clay default
clay default set [SEGMENT ...]
clay default set -f PATH
clay default reset
```

- `clay default` prints the current startup reference.
- `clay default set` saves the selected workflow as the user-managed default.
- `clay default reset` restores the default shipped with the application.

## `clay run-json`

Run an in-memory workflow JSON document. This interface is intended for API and
application integrations and never resolves child assets from a workflow file
directory.

```text
clay run-json [--file PATH] [--no-auto] [--events-socket PATH]
```

| Option | Purpose |
|---|---|
| `--file PATH` | Read JSON from a file. Without it, read JSON from standard input. |
| `--no-auto` | Disable automatic human decisions and exchange prompts through JSON markers. |
| `--events-socket PATH` | Send JSON-line workflow events to a Unix socket. |

Automatic decisions are enabled by default for `run-json`.

## `clay docs`

Regenerate the action-reference JSON and HTML from the live action registry.

```text
clay docs
```

Outputs are written under `docs/documentation/` in a source checkout.

## `clay ui`

Launch the PySide6 desktop application through `clayd`.

```text
clay ui [WORKFLOW ...]
```

Each workflow argument is opened in a separate tab. The installed package must
include the UI dependencies.

## `clay daemon`

Manage the `clayd` process and its workflows.

### Lifecycle and status

```text
clay daemon start
clay daemon stop
clay daemon status
clay daemon list
```

- `start` starts the daemon if necessary.
- `stop` requests daemon shutdown.
- `status` reports daemon and installed-service status.
- `list` reports managed workflow IDs, names, states, runtimes, iterations, and
  event counts.

### Run a workflow

```text
clay daemon run [SEGMENT ...]
clay daemon run -f PATH
```

| Option | Purpose |
|---|---|
| `-f PATH`, `--file PATH` | Run an exact workflow file or directory. |
| `--auto` | Use model-generated human decisions. |
| `--daemon-mode` | Run fully unattended with no interactive prompts. |
| `--project-dir PATH` | Set the project directory passed to the daemon workflow. |

### Control a managed workflow

```text
clay daemon kill WORKFLOW_ID
clay daemon tail WORKFLOW_ID [-n LINES]
clay daemon attach WORKFLOW_ID
```

- `kill` stops one workflow.
- `tail` prints recent workflow output. `-n` or `--lines` defaults to `50`.
- `attach` streams events and relays interactive input. Press Ctrl+C to detach.

### Install the daemon service

```text
clay daemon install [--dry-run]
clay daemon uninstall
```

`install --dry-run` prints the service configuration without installing it.
`uninstall` removes the launchd or systemd service.

## `clay dirs`

Manage approved project directories.

```text
clay dirs list
clay dirs add PATH
clay dirs forget PATH
```

- `list` shows approved directories and their approval gates.
- `add` approves a directory and its descendants.
- `forget` removes the exact directory grant.

## `clay memory`

Delete persisted entries from one memory namespace.

```text
clay memory purge NAMESPACE
```

This command removes every JSON memory entry in the named namespace.

## `clay build`

Regenerate developer artifacts or upgrade seeded template workflows.

```text
clay build
clay build --upgrade
```

- `clay build` rebuilds `~/.clay/schema.json` and the committed system registry
  workflow tree. It must run from a writable source checkout.
- `clay build --upgrade` compares installed seeded templates with the shipped
  versions, shows changes, asks before replacing modified workflows, creates
  backups, and rebuilds the schema.

## `clay configure` and `clay config`

Interactively configure the model provider, model profiles, and default model
response limit in `~/.clay/config.json`.

```text
clay configure
clay config
```

`clay config` is an alias for `clay configure`. The command asks for:

- the OpenAI-compatible provider URL;
- the default model;
- the default `maxTokens` value;
- optional named model profiles.

## `clay lint`

Validate workflow and data JSON files.

```text
clay lint
clay lint SEGMENT [SEGMENT ...]
clay lint PATH
```

With no argument, Clay lints the user workflow folder. An existing filesystem
path wins over workflow-name lookup. A directory causes every JSON file beneath
it to be checked.

## `clay check context`

Inspect `scramda2` prompt sizes without running the workflow or contacting the
model server.

```text
clay check context SEGMENT [SEGMENT ...]
clay check context -f PATH
clay check context SEGMENT [SEGMENT ...] --context FILE
```

| Option | Purpose |
|---|---|
| `-f PATH`, `--file PATH` | Inspect an exact workflow file or directory. |
| `--context FILE` | Load a JSON object containing representative runtime values. |

The command recursively inspects child `workflow` and `loop` files. It resolves
defaults, included static context, and values supplied by `--context`, then
prints the character count of the prompt that `scramda2` would pass to Gopher.
Runtime action outputs absent from the context file remain visible as unresolved
placeholder names.

Example:

```bash
clay check context workflows system editor3
```

```text
✓ iteration.json  design_contract: 1,248 characters  unresolved: user_request, workspace_files
✓ file-iteration.json  file_plan: 1,156 characters  unresolved: design_contract, workspace_files
```

The command reports characters, not estimated tokens. Tokenization belongs to
the selected model server.
