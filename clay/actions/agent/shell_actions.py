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


# ---------------------------------------------------------------------------
# Hardcoded whitelist — immutable, not readable from workflow JSON or AI data.
# Add entries here (in code) to allow additional commands.
# ---------------------------------------------------------------------------
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
    # ---------------------------------------------------------------------
    # Development toolchain.
    #
    # These are not read-only and no argument guard can make them so: an
    # interpreter runs whatever it is handed, and `python3 -c '...'` is
    # arbitrary code execution by construction. They are here because a coding
    # workflow that cannot run the code it just wrote is not a coding
    # workflow — an explicit decision, not an oversight. `runReplyCommands`
    # pins cwd to the workspace, which bounds where they run but not what
    # they can do.
    # ---------------------------------------------------------------------
    'python3', 'python', 'node', 'pytest', 'npm', 'make', 'git',
})

# ---------------------------------------------------------------------------
# Arguments that make an allowed command run *another* command, or write.
#
# The whitelist above checks only the first token of each segment, so a flag
# that takes a command as its argument would smuggle an unlisted executable
# past it: `find . -exec rm -rf {} ;` presents `find` in first position and
# never shows `rm` there. These flags are refused wherever they appear.
# ---------------------------------------------------------------------------
BLOCKED_ARGUMENTS = frozenset({
    '-exec', '-execdir', '-ok', '-okdir',        # run a command
    '-delete',                                    # destructive
    '-fprint', '-fprint0', '-fprintf', '-fls',    # write to a file
})

_PLACEHOLDER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


def _interpolate(template: str, ctx: dict, quote: bool = True) -> str:
    """Substitute {vars} from previous_data into a command template.

    Only named placeholders are substituted. str.format_map cannot be used
    here: shell syntax is full of braces that are not placeholders — `{}` in
    `find -exec`, `${VAR}` in a shell expansion, `{1..3}` in a brace
    expansion — and format_map raises ValueError on the first of those,
    killing the run instead of refusing the command. A regex that matches only
    identifiers leaves every one of them untouched.

    With `quote`, values go through shlex.quote() so they become a single
    shell word regardless of content, making injection via substitution
    structurally impossible rather than a matter of stripping characters.
    Without it the value is passed through raw — for arguments handed to
    subprocess directly, such as cwd, where quotes would become part of the
    path. An unknown key is left as written, not blanked.
    """
    def replace(match):
        key = match.group(1)
        if key not in ctx:
            return match.group(0)
        value = str(ctx[key])
        return shlex.quote(value) if quote else value

    return _PLACEHOLDER.sub(replace, template)


def _blocked_arguments_in(command: str) -> list[str]:
    """Return any BLOCKED_ARGUMENTS token appearing anywhere in the command.

    Checked against the resolved command, so a flag arriving through
    {placeholder} interpolation is caught too — interpolation quotes values
    into a single word, but a quoted `-exec` is still `-exec` to find.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    return [t for t in tokens if t in BLOCKED_ARGUMENTS]


def _executables_in(command: str) -> list[str]:
    """
    Return the basename of every executable in a compound shell command.
    Splits on &&, ||, ; and | then takes the first token of each segment.
    """
    parts = re.split(r'&&|\|\||[;|]', command)
    names = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        try:
            tokens = shlex.split(part)
        except ValueError:
            tokens = part.split()
        if tokens:
            names.append(os.path.basename(tokens[0]))
    return names


def refusal_for(command: str):
    """Return why this command may not run, or None if it may.

    The single gate every execution path goes through — the `shell` action
    and any action that runs commands a model wrote. A second, weaker copy of
    these checks is how a whitelist stops meaning anything.
    """
    if any(token in command for token in ('\n', '\r', '&&', '||', ';', '|',
                                           '>', '<', '$(', '`')):
        return 'shell operators, redirection and substitution are not allowed'

    executables = _executables_in(command)
    if not executables:
        return "could not parse any executable from command"

    blocked = [e for e in executables if e not in ALLOWED_COMMANDS]
    if blocked:
        return f"'{', '.join(blocked)}' not in whitelist"

    blocked_args = _blocked_arguments_in(command)
    if blocked_args:
        return f"argument '{', '.join(blocked_args)}' can run or write"

    return None


def execute(command: str, timeout: int = 30, cwd: str = None,
            include_stderr: bool = False) -> str:
    """Run an already-validated command and return its output.

    Callers must have cleared `refusal_for` first. A non-zero exit is not an
    exception: the output carries an [exit code: N] marker. `include_stderr`
    folds the error stream into the returned text — a model that ran a failing
    command needs to see the traceback, whereas the plain `shell` action logs
    it and keeps stdout clean for the next action to consume.
    """
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

    # Substitute variables — values are shell-quoted
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

# Every line a command prints is echoed onto the event bus, so the CLI and the
# chat both show what ran and what came back. The cap on that body is
# logger.OUTPUT_MAX_CHARS, shared with every other payload.


def parse_commands(text) -> list:
    """Command lines from every ```bash fence in the text, in order.

    One command per line. Comments and blank lines are dropped; a trailing
    backslash continuation is joined onto the next line so a wrapped command
    is validated and run as the single command it is.
    """
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
        # Quoting is for values embedded *inside* a command string; a cwd is
        # passed to subprocess directly, so it must not be quoted.
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
            # In the transcript rather than dropped, because the transcript is
            # what the next pass reads: a command that quietly vanished would
            # have it conclude the check passed.
            transcript.append(f'$ {command}\n[skipped: not approved]')
            continue
        refusal = refusal_for(command)
        if refusal:
            logger.warn(f"runReplyCommands: blocked '{command}' — {refusal}")
            transcript.append(f'$ {command}\n[refused: {refusal}]')
            continue
        output = execute(command, timeout, cwd=cwd, include_stderr=True).strip()
        # The command and every line it printed go out as one event, together,
        # so a front-end cannot show the command without its output or
        # interleave two commands' output when they run back to back.
        logger.output(action, 'command', f'$ {command}', output)
        transcript.append(f'$ {command}\n{output}')

    return {"id": action.get("id"), "data": '\n\n'.join(transcript)}


def _approved_commands(action, commands, cwd) -> set:
    """Indices of the commands a human allowed. Every index when the gate is off.

    A command already blocked by refusal_for() is shown as blocked in the
    prompt rather than hidden, so nobody is asked to think about something that
    was never going to run — and so the block itself is visible at the one
    moment somebody is reading the list.
    """
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
