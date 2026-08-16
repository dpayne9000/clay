# humanShell

Proposes a shell command to the human for approval before running it. Always pauses for human review — even in `--auto` mode. Uses a broader developer-oriented whitelist than `shell`.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the command output under |
| `command` | yes | string | Command template. Supports `{placeholder}` interpolation |
| `timeout` | no | number | Seconds before the command is killed. Defaults to `60` |
| `skipValue` | no | string | If the resolved command equals this value, skip without prompting |

## How it works

1. The `command` template is resolved via `{placeholder}` interpolation (backticks and `$()` stripped from variable values).
2. If `skipValue` is set and the resolved command matches it, the action returns `[skipped]` without prompting.
3. Every executable in the resolved command is checked against `DEVELOPER_COMMANDS`. Blocked commands are rejected before the human sees them.
4. The human is shown a formatted approval box and asked to:
   - Press Enter or type `y` / `yes` to approve
   - Type `n` / `no` / `reject` / `skip` to reject
   - Type a different command to substitute (whitelist-checked again)
5. The approved command runs and stdout is returned.

The human gate fires in `--auto` mode. An unattended daemon run refuses the
action because no human is available.

### Developer whitelist

Package managers: `npm`, `npx`, `pip`, `pip3`, `pipenv`, `poetry`, `yarn`, `pnpm`
Runtimes: `node`, `python`, `python3`
VCS: `git`
Build/test: `make`, `jest`, `pytest`, `vitest`, `mocha`, `cargo`
Files (no delete): `ls`, `cat`, `head`, `tail`, `echo`, `touch`, `mkdir`, `cp`, `mv`, `find`, `grep`, `chmod`, `pwd`, `which`, `cd`
Network (read-only): `curl`, `wget`
Docker: `docker`, `docker-compose`
Environment: `env`, `printenv`, `whoami`, `uname`, `date`

## Examples

### Install a dependency with approval
```json
{ "id": "package", "type": "humanDecision", "prompt": "Package to install:" },
{ "id": "install_result", "type": "humanShell", "command": "npm install {package}" }
```

### Run tests after generating code
```json
{ "id": "test_result", "type": "humanShell", "command": "pytest tests/" }
```

### AI-generated command with skip escape
```json
{ "id": "cmd", "type": "scramda2", "prompt": "Write the git command to stage changes, or NONE:" },
{ "id": "git_result", "type": "humanShell", "command": "{cmd}", "skipValue": "NONE" }
```

If the AI returns `"NONE"`, the step is skipped. Otherwise the command is shown to the human for approval.

### Human edits the command at runtime
When the approval prompt appears, the human can type a corrected version of the command instead of just approving or rejecting. The edited command is whitelist-checked before running.

## Output

- `stdout` from the approved command
- Non-zero exit code appends `\n[exit code: N]`
- Timeout produces `[timeout after Ns]`
- Rejected commands return `[rejected by user]`
- Blocked commands return `[blocked — 'cmd' not in developer whitelist]`
- Skipped commands return `[skipped]`
- Unattended runs return `[refused: no human available]`

## Notes

- Destructive commands (`rm`, `rmdir`, `pkill`, `kill`, `dd`) are intentionally absent — the whitelist is not a substitute for careful review of dangerous operations
- For fully automated read-only system probes, use `shell` instead
- `skipValue` is useful when an upstream AI step might determine no command is needed
