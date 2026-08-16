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
    """Send an event to every listener.

    A failing listener must not stop other listeners or the workflow. Report
    listener failures directly to stderr to avoid recursion through error().
    """
    for fn in list(_listeners):
        try:
            fn(event)
        except Exception as exc:
            print(f'  !! event listener {getattr(fn, "__name__", fn)!r} '
                  f'failed: {exc}', file=sys.stderr)


def _emit(level: str, msg: str, show: bool):
    """Record a log line and notify listeners when `show` is true."""
    if _active:
        _active.log(f'{level}  {msg}')
    if show:
        _notify({'type': events.LOG, 'ts': time.time(),
                 'level': level.strip(), 'message': msg})


def trace(msg: str):
    """Write a detailed internal trace to the log file."""
    _emit('TRACE', msg, False)


def debug(msg: str):
    """Write debugging detail to the log file."""
    _emit('DEBUG', msg, False)


def info(msg: str):
    """Emit a user-facing informational event."""
    _emit('INFO ', msg, True)


def warn(msg: str):
    """Emit a user-facing warning."""
    _emit('WARN ', msg, True)


def error(msg: str):
    """Emit a user-facing error."""
    _emit('ERROR', msg, True)


def emit(event_type: str, *, show: bool = True, **kwargs):
    """Emit a structured event to the log file and, when shown, to listeners.

    `show=False` implements `"visible": false`. Hidden events remain in the log
    so later debugging has a complete record. This mirrors _emit() for log lines.
    """
    event = {"type": event_type, "ts": time.time(), **kwargs}
    if _active:
        _active.log_event(event)
    if show:
        _notify(event)


# This shared limit caps every action.output body; zero disables truncation.
OUTPUT_MAX_CHARS = 0


def output(action: dict, kind: str, label: str, text: str = ''):
    """Emit a user-facing action payload.

    Unlike info(), this event includes the action ID and type. Front-ends can
    therefore filter payloads by structured fields instead of message text.

    Accepting the action dictionary guarantees attribution and applies its
    visibility setting before any payload reaches a front-end.
    """
    body = str(text or '')
    if 0 < OUTPUT_MAX_CHARS < len(body):
        body = body[:OUTPUT_MAX_CHARS] + '\n… (truncated — see OUTPUT_MAX_CHARS)'
    emit(events.ACTION_OUTPUT, id=action.get('id', ''),
         action_type=action.get('type', ''), kind=kind,
         label=label, text=body, show=visible(action))

    # Relabel the busy indicator after the handler resolves the prompt. Emit the
    # payload first because a renderer may clear its indicator while drawing it.
    if kind == 'prompt':
        busy(True, action.get('type', ''), body)


#: Maximum resolved-prompt length in a one-line busy indicator. The complete
#: prompt remains available through action.output and in the log.
BUSY_PREVIEW_MAX_CHARS = 100


def busy(active: bool, action_type: str = '', preview: str = '') -> None:
    """Set every front-end's working indicator.

    Not routed through emit(), for two reasons.

    Busy events do not reach the log because they represent transient display
    state rather than workflow activity.

    Visibility does not suppress busy events because a hidden action can still
    leave the interface waiting. The preview may therefore expose a truncated
    portion of a hidden prompt while the full payload remains hidden.

    `active` is state rather than a counter. Repeating active=True relabels the
    current operation without requiring listeners to track nesting.
    """
    text = ' '.join(str(preview or '').split())[:BUSY_PREVIEW_MAX_CHARS]
    _notify({'type': events.BUSY, 'ts': time.time(), 'active': bool(active),
             'action_type': str(action_type or ''), 'preview': text})


def visible(action: dict) -> bool:
    """Return whether an action's events should reach front-ends.

    Actions are visible by default.

    Parse strings explicitly because hand-written JSON may contain
    `"visible": "false"`, which bool() would incorrectly treat as true.
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
    """Route JSON-line events and human prompts over a Unix domain socket."""
    import socket as _socket
    import threading

    from . import io as _io

    global _socket_conn, _socket_listener
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.connect(socket_path)
    _socket_conn = sock

    # Serialize writes because events and input requests share one stream.
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
