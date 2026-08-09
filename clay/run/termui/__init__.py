"""clay terminal UI — aurora-themed output with swappable themes.

Imported once in cli.py:
  • Scans sys.argv for --ci / --plainStdout and sets PLAIN accordingly
  • intro() fires the non-blocking intro animation; cli calls it at run
    startup. Importing this module never draws to the terminal.

All callers import from here:
    from ..run import termui
    termui.step_header('recall')
    termui.error('missing field')
"""
import sys
import threading
from . import engine, loader
from .spinner import Spinner as _Spinner

# Detect plain mode from argv before argparse runs
PLAIN: bool = '--ci' in sys.argv or '--plainStdout' in sys.argv
IS_TTY: bool = sys.stdout.isatty()

def set_plain(val: bool):
    global PLAIN
    PLAIN = bool(val)


def _rich() -> bool:
    return IS_TTY and not PLAIN


def _t() -> dict:
    return loader.active_theme()


# ── Public API ────────────────────────────────────────────────────────────────

def intro():
    """Fire the non-blocking intro animation. No-op when plain or not a TTY."""
    if _rich():
        threading.Thread(
            target=engine.intro_effects,
            args=(loader.active_theme(),),
            daemon=True,
        ).start()


def startup_banner(label: str, auto: bool, log_path: str):
    engine.startup_banner(label, auto, log_path, _t(), _rich())


def step_header(name: str):
    engine.step_header(name, _t(), _rich())


def action_line(action_type: str, action_id: str, detail: str = ''):
    engine.action_line(action_type, action_id, detail, _t(), _rich())


def scramda_input(prompt_text: str, model: str = ''):
    engine.scramda_input(prompt_text, _t(), _rich(), model=model)


def scramda_output(text: str):
    engine.scramda_output(text, _t(), _rich())


def error(msg: str):
    engine.error(msg, _t(), _rich())


def warn(msg: str):
    engine.warn(msg, _t(), _rich())


def command_echo(command: str, outcome: str):
    engine.command_echo(command, outcome, _t(), _rich())


def file_write(label: str, diff: str = ''):
    engine.file_write(label, diff, _t(), _rich())


def file_read(label: str):
    engine.file_read(label, _t(), _rich())


def shell_run(command: str, output: str = ''):
    engine.shell_run(command, output, _t(), _rich())


def completion_banner(log_path: str):
    engine.completion_banner(log_path, _t(), _rich())


def Spinner():
    """Return a ready-to-use Spinner instance."""
    return _Spinner(_t(), _rich())
