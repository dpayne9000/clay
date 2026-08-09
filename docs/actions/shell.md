# shell

Runs a shell command from a hardcoded whitelist and captures stdout. Intended for safe, read-only system inspection in automated workflows.

## Fields

| Field | Required | Type | Description |
|---|---|---|---|
| `id` | yes | string | Key to store the command output under |
| `command` | yes | string | Shell command to run. Supports `{placeholder}` interpolation |
| `timeout` | no | number | Seconds before the command is killed. Defaults to `30` |

## Security model

Two layers prevent injection:

1. **Whitelist** — every executable in the resolved command must be in `ALLOWED_COMMANDS`. Compound commands (`&&`, `||`, `;`, `|`) have all segments checked. Unlisted executables are blocked before execution.

2. **Injection stripping** — `{placeholder}` substitution strips the characters `` ; & | ` $ < > ( ) \ `` newline and tab from variable values before they reach the shell.

The whitelist is hardcoded in `shell_actions.py` and cannot be expanded from workflow JSON.

### Allowed commands

Network inspection: `ifconfig`, `netstat`, `arp`, `ping`, `ping6`, `traceroute`, `traceroute6`, `dig`, `nslookup`, `host`, `nmap`, `nc`, `curl`, `wget`, `lsof`, `ss`, `networksetup`, `system_profiler`

System info (read-only): `hostname`, `uname`, `uptime`, `whoami`, `id`, `ps`, `df`, `du`, `ls`, `cat`, `head`, `tail`, `echo`, `date`, `env`, `printenv`

DNS/discovery: `avahi-browse`

## Examples

### Run a fixed command
```json
{ "id": "interfaces", "type": "shell", "command": "ifconfig" }
```

### Use previous output in the command
```json
{ "id": "target_host", "type": "humanDecision", "prompt": "Enter a hostname to probe:" },
{ "id": "dns_result", "type": "shell", "command": "dig {target_host}" }
```

The `{target_host}` value has injection characters stripped before substitution.

### Chain commands
```json
{ "id": "open_ports", "type": "shell", "command": "nmap -sn {network_range} | grep report" }
```

Both `nmap` and `grep` are checked against the whitelist.

### Set a longer timeout for slow commands
```json
{ "id": "scan", "type": "shell", "command": "nmap -sV {target_host}", "timeout": 120 }
```

## Output

- `stdout` is stored under `id`
- Non-zero exit code appends `\n[exit code: N]` to the output
- Timeout produces `[timeout after Ns]`

## Notes

- For developer tasks (git, npm, python, etc.), use `humanShell` — it has a broader whitelist and a human approval gate
- `shell` is designed for fully automated network/system probes where human approval at each step is not needed
- Destructive commands (`rm`, `kill`, `dd`) are intentionally absent from the whitelist
