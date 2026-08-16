import os
import re
import shlex
import subprocess
from ...run import approval, logger
from ..registry import action, req, opt, handler_for


@action('shell', skeleton=False)
class Shell:
    id:      str = req("Output key for stdout")
    command: str = req("Shell command. Supports {placeholder} interpolation")
    timeout: int = opt("Seconds before the process is killed", 30)


# Workflows cannot extend this code-owned allowlist.
ALLOWED_COMMANDS = frozenset({
    # Network inspection
    'ifconfig', 'netstat', 'arp', 'ping', 'ping6', 'traceroute', 'traceroute6',
    'dig', 'nslookup', 'host', 'nmap', 'nc', 'curl', 'wget', 'lsof', 'ss',
    # macOS network tools
    'networksetup', 'system_profiler',
    # System info (read-only)
    'hostname', 'uname', 'uptime', 'whoami', 'id', 'ps', 'df', 'du',
    'ls', 'cat', 'head', 'tail', 'echo', 'date', 'env', 'printenv',
    'find',
    # DNS / discovery
    'avahi-browse',
    # Development tools can execute or modify code. Workspace cwd limits their
    # starting directory; it does not sandbox them.
    'python3', 'python', 'node', 'pytest', 'npm', 'make', 'git',
})

# Dangerous flags on otherwise allowed commands.
BLOCKED_ARGUMENTS = frozenset({
    '-exec', '-execdir', '-ok', '-okdir',        # run a command
    '-delete',                                    # destructive
    '-fprint', '-fprint0', '-fprintf', '-fls',    # write to a file
})

_PLACEHOLDER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _interpolate(template: str, ctx: dict, quote: bool = True) -> str:
    """Replace named placeholders. Quote values used in command strings."""
    def replace(match):
        key = match.group(1)
        if key not in ctx:
            return match.group(0)
        value = str(ctx[key])
        return shlex.quote(value) if quote else value

    return _PLACEHOLDER.sub(replace, template)


def _blocked_arguments_in(command: str) -> list[str]:
    """Return blocked argument tokens from a valid command."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        # refusal_for() rejects malformed commands.
        return []
    return [t for t in tokens if t in BLOCKED_ARGUMENTS]


def _command_tokens(command: str) -> list[str]:
    """Tokenize the argv exactly as execute() will."""
    return shlex.split(command)


def _has_unquoted_shell_operator(command: str) -> bool:
    """Detect shell punctuation while respecting quotes and backslash escapes."""
    quote = None
    escaped = False
    for char in command:
        if escaped:
            escaped = False
            continue
        if char == '\\' and quote != "'":
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in ';&|<>':
            return True
    return False


def _executables_in(command: str) -> list[str]:
    """Return the executable for a valid single command, otherwise none."""
    try:
        tokens = _command_tokens(command)
    except ValueError:
        return []
    if not tokens or _has_unquoted_shell_operator(command):
        return []
    return [os.path.basename(tokens[0])]


def refusal_for(command: str):
    """Return the refusal reason, or None when the command is allowed."""
    if any(token in command for token in ('\n', '\r', '$(', '`')):
        return 'shell newlines and substitution are not allowed'

    try:
        tokens = _command_tokens(command)
    except ValueError:
        return 'could not parse command'
    blocked_args = _blocked_arguments_in(command)
    if blocked_args:
        return f"argument '{', '.join(blocked_args)}' can run or write"

    if _has_unquoted_shell_operator(command):
        return 'shell operators and redirection are not allowed'

    if not tokens:
        return "could not parse any executable from command"

    executable = os.path.basename(tokens[0])
    if executable not in ALLOWED_COMMANDS:
        return f"'{executable}' not in whitelist"

    return None


def execute(command: str, timeout: int = 30, cwd: str = None,
            include_stderr: bool = False) -> str:
    """Run a validated command. Mark non-zero exits in the returned output."""
    try:
        result = subprocess.run(
            shlex.split(command),
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd or None,
        )
        output = result.stdout
        if result.returncode != 0:
            if result.stderr:
                if include_stderr:
                    output += result.stderr
                else:
                    logger.warn(f"shell warning: {result.stderr.strip()[:200]}")
            logger.debug(f"shell exit code: {result.returncode}")
            output = output + f"\n[exit code: {result.returncode}]"
        return output
    except subprocess.TimeoutExpired:
        logger.warn(f"shell: timeout after {timeout}s: {command[:60]}")
        return f"[timeout after {timeout}s]"


@handler_for('shell')
def handler(action, ctx):
    command_template = action.get('command') or ''
    if not command_template:
        logger.error("shell: missing 'command' field")
        return None

    command = _interpolate(command_template, ctx)

    refusal = refusal_for(command)
    if refusal:
        logger.warn(f"shell: blocked — {refusal}")
        return None

    approved = approval.confirm(
        'shellCommands', 'shell wants to run this command:',
        [(command, '')], prompt_id=f'{action.get("id", "")}.approve',
        required=True)
    if not approved:
        return {"id": action.get("id"), "data": None,
                "error": "shell: command was not approved"}

    output = execute(command, action.get('timeout', 30))
    return {"id": action.get("id"), "data": output}


@action('runReplyCommands', skeleton=False)
class RunReplyCommands:
    id:          str = req("Output key for the transcript of commands and their output")
    reply:       str = req("Context key holding the model reply to scan for ```bash blocks")
    cwd:         str = opt("Directory to run in. Supports {placeholder} interpolation", None)
    maxCommands: int = opt("Refuse to run more commands than this from one reply", 5)
    timeout:     int = opt("Seconds before a command is killed", 30)


_FENCE = re.compile(r'```(?:bash|sh|shell|zsh|console)\s*\n(.*?)```', re.DOTALL)

# Send command output to front-ends through the event bus.


def parse_commands(text) -> list:
    """Read one command per line from shell fences; join continuations."""
    commands = []
    for block in _FENCE.findall(str(text or '')):
        pending = ''
        for raw in block.splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.endswith('\\'):
                pending += line[:-1].rstrip() + ' '
                continue
            commands.append((pending + line).strip())
            pending = ''
        if pending.strip():
            commands.append(pending.strip())
    return commands


@handler_for('runReplyCommands')
def run_reply_commands_handler(action, ctx):
    reply = ctx.get(action.get('reply') or '')
    commands = parse_commands(reply)
    if not commands:
        return {"id": action.get("id"), "data": ""}

    try:
        max_commands = int(action.get('maxCommands', 5) or 5)
    except (TypeError, ValueError):
        max_commands = 5

    if len(commands) > max_commands:
        msg = (f"runReplyCommands: reply contains {len(commands)} commands; "
               f"the limit is {max_commands}")
        logger.warn(msg)
        return {"id": action.get("id"), "data": msg}

    cwd = action.get('cwd')
    if cwd:
        # cwd is passed directly to subprocess, not through a shell.
        cwd = _interpolate(str(cwd), ctx, quote=False)
        if not os.path.isdir(cwd):
            msg = f"runReplyCommands: cwd '{cwd}' does not exist"
            logger.warn(msg)
            return {"id": action.get("id"), "data": msg}

    timeout = action.get('timeout', 30)

    approved = _approved_commands(action, commands, cwd)

    transcript = []
    for index, command in enumerate(commands):
        if index not in approved:
            # Keep skipped commands visible to the next workflow step.
            transcript.append(f'$ {command}\n[skipped: not approved]')
            continue
        refusal = refusal_for(command)
        if refusal:
            logger.warn(f"runReplyCommands: blocked '{command}' — {refusal}")
            transcript.append(f'$ {command}\n[refused: {refusal}]')
            continue
        output = execute(command, timeout, cwd=cwd, include_stderr=True).strip()
        # Keep each command and its output in one event.
        logger.output(action, 'command', f'$ {command}', output)
        transcript.append(f'$ {command}\n{output}')

    return {"id": action.get("id"), "data": '\n\n'.join(transcript)}


def _approved_commands(action, commands, cwd) -> set:
    """Return approved command indices. Label commands that are already blocked."""
    items = []
    for command in commands:
        refusal = refusal_for(command)
        items.append((command, f'blocked anyway: {refusal}' if refusal else ''))

    where = f' in {cwd}' if cwd else ''
    decision = approval.confirm(
        'commands', f'runReplyCommands wants to run {len(commands)} '
                    f'command(s){where}:',
        items, prompt_id=f'{action.get("id", "")}.approve', required=True)

    if not decision.all_approved:
        logger.warn(f'runReplyCommands: not run at your request — '
                    f'{", ".join(decision.rejected_labels())}')
    return set(decision.approved)
