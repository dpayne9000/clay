import os
import re
import shlex
import subprocess
from ...run import io, logger
from ..registry import action, req, opt, handler_for


@action('humanShell', skeleton=False)
class HumanShell:
    id:        str = req("Output key for stdout")
    command:   str = req("Command template. Supports {placeholder} interpolation")
    timeout:   int = opt("Seconds before the process is killed", 60)
    skipValue: str = opt("If the resolved command equals this value, skip without prompting", "")


# ---------------------------------------------------------------------------
# Developer command whitelist — broader than shell_actions.py because a human
# is reviewing every command before it runs. Still no destructive tools (rm,
# rmdir, pkill, kill, dd, etc.) — the human gate is not a substitute for that.
# ---------------------------------------------------------------------------
DEVELOPER_COMMANDS = frozenset({
    # Package managers
    'npm', 'npx', 'pip', 'pip3', 'pipenv', 'poetry', 'yarn', 'pnpm',
    # Runtimes
    'node', 'python', 'python3',
    # VCS
    'git',
    # Build / test runners
    'make', 'jest', 'pytest', 'vitest', 'mocha', 'cargo',
    # File / directory operations (no delete)
    'ls', 'cat', 'head', 'tail', 'echo', 'touch', 'mkdir', 'cp', 'mv',
    'find', 'grep', 'chmod', 'pwd', 'which', 'cd',
    # Network (read-only)
    'curl', 'wget',
    # Docker
    'docker', 'docker-compose',
    # Environment
    'env', 'printenv',
    # Misc
    'whoami', 'uname', 'date',
})

# Strip subshell-injection characters from substituted variable values.
# Allows ; and && so compound dev commands work, but blocks backticks, $() etc.
_INJECTION_RE = re.compile(r'[`\n\r\t]|\$\(')


class _SafeMap(dict):
    def __missing__(self, key):
        return f'{{{key}}}'

    def __getitem__(self, key):
        raw = super().__getitem__(key)
        return _INJECTION_RE.sub('', str(raw))


def _executables_in(command):
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


@handler_for('humanShell')
def handler(action, ctx, auto=False, daemon=False):
    command_template = action.get('command') or ''
    skip_value = action.get('skipValue', '')
    command = command_template.format_map(_SafeMap(ctx)).strip()

    # AI decided this step should be skipped
    if skip_value and command == skip_value.strip():
        logger.debug(f"humanShell: skipped ({skip_value})")
        return {"id": action.get("id"), "data": "[skipped]"}

    if not command:
        return {"id": action.get("id"), "data": "[skipped]"}

    # Whitelist check — catches AI-generated unsafe commands before the human sees them
    executables = _executables_in(command)
    blocked = [e for e in executables if e not in DEVELOPER_COMMANDS]
    if blocked:
        msg = f"blocked — '{', '.join(blocked)}' not in developer whitelist"
        logger.warn(f"humanShell: {msg} — proposed: {command}")
        return {"id": action.get("id"), "data": f"[{msg}]"}

    # An unattended run cannot manufacture human consent.
    if daemon:
        logger.warn(f"humanShell: refused in unattended mode: {command}")
        return {"id": action.get("id"), "data": "[refused: no human available]"}
    else:
        # ── Human gate ───────────────────────────────────────────────────────
        # This prompt is ALWAYS shown, even in --auto mode.  The human is the
        # final authority on what runs.  The command travels inside the prompt
        # text so remote approvers see what they are approving.
        response = io.get().prompt(
            action.get("id", ""),
            "Command requires approval:\n"
            f"    {command}\n"
            "[Y]approve / [n]reject / or type an edited command",
        ).strip()

        if response.lower() in ('n', 'no', 'reject', 'skip'):
            logger.info("humanShell: rejected by user")
            return {"id": action.get("id"), "data": "[rejected by user]"}

        if response and response.lower() not in ('y', 'yes', ''):
            # User supplied an edited command — re-check whitelist
            edited_executables = _executables_in(response)
            blocked_edit = [e for e in edited_executables if e not in DEVELOPER_COMMANDS]
            if blocked_edit:
                msg = f"blocked after edit — '{', '.join(blocked_edit)}' not in developer whitelist"
                logger.warn(f"humanShell: {msg}")
                return {"id": action.get("id"), "data": f"[{msg}]"}
            command = response

    # ── Execute ─────────────────────────────────────────────────────────────
    timeout = action.get('timeout', 60)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout
        if result.returncode != 0:
            if result.stderr:
                logger.warn(f"humanShell warning: {result.stderr.strip()[:200]}")
            output = output + f"\n[exit code: {result.returncode}]"
    except subprocess.TimeoutExpired:
        logger.warn(f"humanShell: timeout after {timeout}s")
        output = f"[timeout after {timeout}s]"

    return {"id": action.get("id"), "data": output}
