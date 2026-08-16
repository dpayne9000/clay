# shell

Runs one approved command and stores its standard output.

## Fields

| Field | Required | Type | Description |
|---|---:|---|---|
| `id` | yes | string | Result key |
| `command` | yes | string | Command argv with optional `{placeholder}` values |
| `timeout` | no | integer | Timeout in seconds; default `30` |

## Command rules

- The command runs with `shell=False` as one argv.
- The executable must be in the code-owned `ALLOWED_COMMANDS` set.
- Workflows cannot extend that set.
- Unquoted shell operators and redirection are refused, including `&&`, `||`,
  `;`, `|`, `&`, `>`, and `<`.
- Newlines, command substitution, and backticks are refused.
- Dangerous `find` flags such as `-exec`, `-delete`, and file-output flags are
  refused.
- Placeholder values use `shlex.quote`, so each value remains one argument.
- The command still requires approval through the `shellCommands` gate.

The allowlist includes inspection commands and selected development tools.
Development tools such as Python, Node, npm, make, git, and pytest can execute
or modify code. This action is not a security sandbox.

## Examples

```json
{ "id": "interfaces", "type": "shell", "command": "ifconfig" }
```

```json
{ "id": "dns", "type": "shell", "command": "dig {target_host}" }
```

Compound commands are not supported. Use separate actions when commands must
run in sequence.

## Results

- Standard output is stored under `id`.
- A non-zero exit appends `[exit code: N]`.
- A timeout returns `[timeout after Ns]`.
- A refused command does not run.
- A command rejected at the approval prompt returns an error result.
