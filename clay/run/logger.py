import json
import os
import sys
import time
from datetime import datetime

from . import events

_active = None
_listeners = []


class RunLogger:
    def __init__(self, root_file):
        self.start = time.time()
        self.depth = 0
        os.makedirs('logs', exist_ok=True)
        ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        name = os.path.splitext(os.path.basename(root_file))[0]
        self.path = f'logs/{ts}_{name}.log'
        self._fh = open(self.path, 'w', buffering=1)

    def _elapsed(self):
        return f'+{time.time() - self.start:.3f}s'

    def _pad(self):
        return '  ' * self.depth

    def log(self, line):
        self._fh.write(f'[{self._elapsed()}] {self._pad()}{line}\n')

    def log_event(self, event: dict):
        self._fh.write(f'[{self._elapsed()}] EVENT  {json.dumps(event, default=str)}\n')

    def close(self):
        self._fh.close()


def start(root_file):
    global _active
    _active = RunLogger(root_file)
    return _active


def get():
    return _active


def stop():
    global _active
    if _active:
        _active.close()
        _active = None


def _notify(event: dict) -> None:
    """Fan an event out to every listener.

    A listener that raises must not stop the others or kill the run — one
    broken renderer is not a reason to lose a workflow. The failure goes
    straight to stderr rather than through logger.error(), which would route
    back into this function and recurse.
    """
    for fn in list(_listeners):
        try:
            fn(event)
        except Exception as exc:
            print(f'  !! event listener {getattr(fn, "__name__", fn)!r} '
                  f'failed: {exc}', file=sys.stderr)


def _emit(level: str, msg: str, show: bool):
    """Record a log line. `show` marks it user-facing rather than internal."""
    if _active:
        _active.log(f'{level}  {msg}')
    if show:
        _notify({'type': events.LOG, 'ts': time.time(),
                 'level': level.strip(), 'message': msg})


def trace(msg: str):
    """Detailed internal trace — log file only."""
    _emit('TRACE', msg, False)


def debug(msg: str):
    """Debug detail — log file only."""
    _emit('DEBUG', msg, False)


def info(msg: str):
    """Informational event — log file + stdout."""
    _emit('INFO ', msg, True)


def warn(msg: str):
    """Warning — log file + stdout."""
    _emit('WARN ', msg, True)


def error(msg: str):
    """Error — log file + stdout."""
    _emit('ERROR', msg, True)


def emit(event_type: str, *, show: bool = True, **kwargs):
    """Emit a structured event to the log file and, when shown, to listeners.

    `show=False` is the "visible": false path. The log file still gets the
    event: hiding an action is a decision about a screen, not a licence to
    lose the evidence, and a run debugged after the fact needs the whole
    record. Mirrors `_emit(level, msg, show)` for log lines.
    """
    event = {"type": event_type, "ts": time.time(), **kwargs}
    if _active:
        _active.log_event(event)
    if show:
        _notify(event)


# Cap on the body of an action.output, in characters. 0 means uncapped.
# One cap for every payload on the bus rather than a copy per action module —
# file_ops and shell_actions each had their own, and a fourth was about to be
# added for memory and skills.
OUTPUT_MAX_CHARS = 0


def output(action: dict, kind: str, label: str, text: str = ''):
    """Emit a payload an action has to show a person.

    Distinct from info(): a log line is a level and a string, and a front-end
    receiving one cannot tell which action produced it. This carries the id and
    type of the emitting action, so "show file writes but not file reads" is a
    filter on data rather than a match on message text.

    Takes the action dict rather than an id for two reasons: a call site cannot
    emit an unattributed payload, and the action's own "visible" flag is read
    here, so no handler can leak a payload the workflow asked to hide.
    """
    body = str(text or '')
    if 0 < OUTPUT_MAX_CHARS < len(body):
        body = body[:OUTPUT_MAX_CHARS] + '\n… (truncated — see OUTPUT_MAX_CHARS)'
    emit(events.ACTION_OUTPUT, id=action.get('id', ''),
         action_type=action.get('type', ''), kind=kind,
         label=label, text=body, show=visible(action))

    # Relabel the busy indicator now that the text exists. It has to happen
    # here and cannot happen in the dispatcher: a prompt is resolved inside its
    # handler (scramda2_actions.py), so action['prompt'] before the handler
    # runs is still the template with {workspace_files} literal — the exact
    # thing action.start stopped carrying. Emitted after action.output so a
    # renderer that stops its spinner to print the prompt box gets it back.
    if kind == 'prompt':
        busy(True, action.get('type', ''), body)


#: How much of a resolved prompt reaches a busy indicator, in characters.
#: A one-line label on a terminal, a chat status and a Qt row, so it is short
#: on purpose — the full prompt travels on action.output and is in the log.
BUSY_PREVIEW_MAX_CHARS = 100


def busy(active: bool, action_type: str = '', preview: str = '') -> None:
    """Raise or drop every front-end's "still working" indicator.

    Not routed through emit(), for two reasons.

    It never reaches the log file. The log is the record of what happened and
    a spinner is not a thing that happened; a pair of these per action would
    double the file and say nothing a timestamp does not already.

    It is never gated by "visible". That flag hides what an action *did*, and
    a hidden action emitting nothing at all between start and finish is the
    reason this event exists — every front-end simply went quiet for however
    long it took. `preview` therefore does expose the first
    BUSY_PREVIEW_MAX_CHARS of a hidden action's prompt: one truncated line
    saying what the wait is for, while the prompt itself stays hidden.

    `active` is a level, not a counter. Two active=True in a row is a relabel,
    which is exactly what output() does once a prompt resolves, and a listener
    holding a level needs no nesting arithmetic to survive it.
    """
    text = ' '.join(str(preview or '').split())[:BUSY_PREVIEW_MAX_CHARS]
    _notify({'type': events.BUSY, 'ts': time.time(), 'active': bool(active),
             'action_type': str(action_type or ''), 'preview': text})


def visible(action: dict) -> bool:
    """Whether this action's events reach a front-end. `"visible": false` hides.

    Absent means visible — a workflow that says nothing about it gets the
    behaviour it has always had.

    Strings are parsed rather than passed to bool(): workflows are hand-written
    json and `"visible": "false"` is a plausible slip, but a non-empty string
    is truthy, so a bare bool() would silently ignore exactly the value the
    author meant most.
    """
    flag = action.get('visible', True)
    if isinstance(flag, str):
        return flag.strip().lower() not in ('false', 'no', 'off', '0', '')
    return bool(flag)


def add_listener(fn):
    """Register a callable invoked with every emitted event dict."""
    _listeners.append(fn)


def remove_listener(fn):
    """Remove a previously registered listener."""
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


# ── Unix-socket event bridge ─────────────────────────────────────────────────

_socket_conn = None
_socket_listener = None


def start_socket_bridge(socket_path: str):
    """Connect to a unix domain socket, register a listener that writes
    JSON-line events to it, and route human prompts over the same socket.
    Called by CLI when --events-socket is passed."""
    import socket as _socket
    import threading

    from . import io as _io

    global _socket_conn, _socket_listener
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.connect(socket_path)
    _socket_conn = sock

    # Events and input.request lines share one stream; serialise every write
    # so two threads cannot interleave halves of a JSON line.
    send_lock = threading.Lock()

    def _write(event):
        try:
            line = json.dumps(event, default=str) + '\n'
            with send_lock:
                sock.sendall(line.encode('utf-8'))
        except Exception:
            pass

    _socket_listener = _write
    add_listener(_write)
    _io.attach_socket(sock, send_lock)


def stop_socket_bridge():
    """Close the socket connection and return prompts to the terminal."""
    from . import io as _io

    global _socket_conn, _socket_listener
    _io.detach()
    if _socket_listener:
        remove_listener(_socket_listener)
        _socket_listener = None
    if _socket_conn:
        try:
            _socket_conn.close()
        except Exception:
            pass
        _socket_conn = None
