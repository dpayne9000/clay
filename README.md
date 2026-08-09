# Clay

**Write your automation as JSON. Run it from a terminal, a background service,
a desktop app, or your phone.**

[Install](#installation) · [Write a workflow](#the-json-workflow-language) ·
[Connect a model](#model-server) · [Run workflows](#workflows) ·
[Control it from Telegram](#remote-control-from-telegram) ·
[Directory safety](#safety-and-directory-access) ·
[Documentation](#documentation)

---

Clay runs workflows you write in JSON. You list the steps, Clay runs them in
order. A step can ask a person a question, send a prompt to a model, run a
shell command, read or write a file, or call an API. Every step's output gets
a name, and later steps use it by that name.

Two ways to use it:

- **Rigid automation.** Fixed steps, same order every time.
- **Agents you control.** Loop a step until the model says it is done, branch
  on what the model answered, let it read and write files — inside a harness
  you wrote, with the gates you set.

Either way, you own the logic. The model writes text and answers questions.
Your JSON decides what happens next.

You can drive any of it from your phone. Clay ships a Telegram control
channel: pick a workflow from a menu in a chat, answer its prompts as chat
messages, and watch the output arrive as it runs. See
[Remote control from Telegram](#remote-control-from-telegram).

You stay in control of the risky parts. Three approval gates — file writes,
file reads, and shell commands — switch on independently, and each one asks
you first, naming the exact files or commands before anything happens. There
is no telemetry, no account, and no vendor service in the middle. Point Clay
at your own model server and your prompts and your files never leave your
machine.

Clay is distributed directly from the Clay HTTPS release site. It is not
published to PyPI or another public Python package registry.

Clay is source-available for private, internal, non-commercial use. Commercial
use requires a separate written license. See [LICENSE](LICENSE); this is not an
open-source license.

## The JSON workflow language

A workflow is one JSON file. `workflow.steps` lists the steps in order.
`actionSets` holds the actions inside each step.

```json
{
  "workflow": {
    "steps": ["ask", "draft", "save"]
  },
  "actionSets": {
    "ask": [
      {
        "id": "topic",
        "type": "humanDecision",
        "prompt": "What should I write about?"
      }
    ],
    "draft": [
      {
        "id": "article",
        "type": "scramda2",
        "prompt": "Write three paragraphs about {topic}.",
        "includedData": ["topic"]
      }
    ],
    "save": [
      {
        "id": "saved",
        "type": "writeFile",
        "file": "draft.md",
        "content": "article"
      }
    ]
  }
}
```

Four rules cover most of it:

- **`id` names the output.** `"id": "topic"` stores that action's result under
  the name `topic`.
- **`includedData` asks for earlier outputs.** List the names this action needs.
- **`{name}` drops a value into text.** `{topic}` becomes whatever the person
  typed.
- **`when` and `whenNot` gate an action.** Point one at an earlier output and
  the action runs only if that answer means yes (or no). `false`, `done`, `0`,
  `no`, `stop` and empty mean no; anything else means yes — so a model
  answering `YES` or `NO` branches your workflow directly.

To build an agent, use the `loop` action. It runs a sub-workflow file over and
over, and `continueKey` names the output that tells it to stop. A loop, a gate,
and outputs you named yourself — that is the whole harness.

Check a workflow before you run it:

```bash
clay lint ./workflow.json
clay dryrun ./workflow.json
```

Every action type and every field is documented in
[WORKFLOWS.md](WORKFLOWS.md) and the
[action reference](docs/actions/).

## Installation

### HTTPS installer

Install the core CLI and daemon on macOS or Linux:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | sh
```

Install the Qt desktop edition:

```bash
curl --proto '=https' --proto-redir '=https' -fsSL \
  https://get.clay.dev/install.sh | sh -s -- --ui
```

The installer selects the correct macOS/Linux ARM64 or x86-64 release, verifies
its SHA-256 value, and installs Clay with its bundled CPython runtime and
offline dependency wheelhouse. WSL2 is supported as a Linux environment on a
best-effort basis.

### Downloaded release archive

If you download a target archive from the release page instead, extract both
the release and its bundled Python runtime, then run the archive-local
installer. Replace the example filename with the core or UI archive you
downloaded:

```bash
tar -xzf clay-0.1.2-macos-arm64-core.tar.gz
cd clay-0.1.2-macos-arm64-core
tar -xzf runtime/python.tar.gz
python/bin/python3 install.py
./clay --version
```

This manual method creates the virtual environment and `clay` launcher inside
the extracted `clay-0.1.2-macos-arm64-core` directory. Keep that directory and
invoke its `./clay` launcher. It does not add `clay` to `PATH`. Use the HTTPS
installer above when you want the standard `~/.local/share/clay` installation
and `~/.local/bin/clay` launcher.

### Command path

Make the installed launcher available in the current shell and verify it:

```bash
export PATH="$HOME/.local/bin:$PATH"
clay --version
```

Clay can then be run from any directory. To preserve that `PATH` setting in
new terminals, follow the shell-specific instructions in
[docs/INSTALL.md](docs/INSTALL.md#make-the-clay-command-available).

Source contributors should use [DEVELOPMENT.md](DEVELOPMENT.md), including the
separate editable-install commands for core and Qt development.

## Model server

Clay sends AI actions to an OpenAI-compatible model server. The default endpoint
is:

```text
http://127.0.0.1:8080
```

Override it when necessary:

```bash
export GOPHER_URL=http://127.0.0.1:8080
```

Model profiles live in `$CLAY_HOME/config.json`, normally
`~/.clay/config.json`. An action can select a configured profile:

```json
{
  "type": "scramda2",
  "id": "draft",
  "modelProfile": "code",
  "prompt": "Write a concise implementation plan for {goal}"
}
```

## Workflows

### Find and run

List the available workflows and their accepted references:

```bash
clay workflows
clay workflows coding
clay workflows --paths
```

Run a workflow by its listed segments:

```bash
clay run templates content quick-explainer
```

Run an exact workflow file:

```bash
clay run -f ./workflow.json
```

The current directory is the workflow's project directory—the place file
actions operate after approval. It is not searched for installed workflows.
Use an explicit project directory when needed:

```bash
clay --project-dir /path/to/project run dev workAgent
```

### Validate, inspect, and create

```bash
clay lint templates content quick-explainer
clay lint ./workflow.json
clay dryrun templates content quick-explainer
clay dryrun -f ./workflow.json
```

Create a workflow interactively:

```bash
clay create my-workflow
```

Upgrade seeded template workflows while reviewing a diff and approving each
workflow separately:

```bash
clay build --upgrade
```

## Safety and directory access

Workflow files are executable automation definitions, not passive documents.
They can contain actions that run Python, shell commands, and generated code.
Only run workflows from sources you trust, especially in automatic or daemon
mode.

Clay's workspace file-reading and file-writing actions use approved
directories. Manage those approvals explicitly with:

```bash
clay dirs list
clay dirs add /path/to/project
clay dirs forget /path/to/project
```

An interactive run can also ask whether to approve and remember a directory,
allow it once, or refuse it.

## Background workflows with `clayd`

Start and inspect `clayd`:

```bash
clay daemon start
clay daemon status
clay daemon list
```

Run a workflow under the daemon:

```bash
clay daemon run dev workAgent
clay daemon run -f ./workflow.json
```

Inspect or attach to a running workflow:

```bash
clay daemon tail wf-0001
clay daemon attach wf-0001
clay daemon kill wf-0001
```

Register the daemon to start with the user session:

```bash
clay daemon install
clay daemon status
```

Remove that service registration with `clay daemon uninstall`.

## Remote control from Telegram

Clay can run a Telegram bot as your remote control. You get a menu of your
workflows in a chat. Tap one and it starts. When it needs an answer, the
question arrives as a message — you reply, and your reply goes back in as the
answer. Output arrives as it happens.

The bot is a front-end, exactly like the desktop app. It never runs a workflow
itself; it asks `clayd` to run it, so the work happens on your machine whether
or not your phone stays awake. One workflow runs at a time per bot.

Set the two environment variables, then start it:

```bash
export TELEGRAM_BOT_TOKEN='123456:your-token-from-@BotFather'
export TELEGRAM_ALLOWED_USERS='123456789'
clay run system messaging telegram
```

The bot refuses to start without a token and at least one numeric user or chat
allowlist. There is no open mode. Messages from anyone not on the list are
ignored.

Choose which workflows appear in the menu with the `workflows` field on the
action:

```json
{
  "id": "bot",
  "type": "telegram",
  "workflows": [
    {"label": "Coding", "path": "workflows/system/coding4/main.json"},
    {"label": "Research", "path": "workflows/templates/research/main.json"}
  ]
}
```

The approval gates work from the chat too. Send `/manual` to switch gates on or
off, and approve file writes, file reads, and commands from your phone before
they run.

Full setup, including how to find your numeric user ID, is in
[clay/data/workflows/system/messaging/telegram.json](clay/data/workflows/system/messaging/telegram.json).

## Qt desktop application

The UI starts `clayd` when necessary and sends all workflow execution through
the daemon:

```bash
clay ui
clay ui dev workAgent
```

The UI provides workflow editing, live run output, daemon process management,
and explicit directory-approval controls.

## User data and installed content

Clay keeps user configuration, workflows, memory, logs, and directory approvals
under `$CLAY_HOME`, normally `~/.clay`. Packaged system workflows and defaults
remain inside the installed release. Ordinary seeding creates missing user files
without overwriting existing ones.

## Documentation

Start with the [documentation map](docs/README.md), or open a specific guide:

- [Installation and command-path details](docs/INSTALL.md)
- [Workflow examples](docs/EXAMPLES.md)
- [Quick command reference](QUICKSTART.md)
- [Workflow linting](LINT.md)
- [Workflow authoring](WORKFLOWS.md)
- [Release build instructions](docs/BUILD-INSTRUCTIONS.md)
- [Contributor setup](DEVELOPMENT.md)
