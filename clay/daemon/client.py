"""Synchronous clayd commands and a separate event subscriber."""

import json
import os
import socket
import subprocess
import sys
import threading
import time

from . import protocol
from .protocol import encode, decode_line

from ..lib import config

SOCKET_PATH = config.user_path('run', 'clayd.sock')


class DaemonPermissionDenied(Exception):
    """The target workspace lacks advance unattended-run authority."""


def authorize_daemon_workspace(project_dir, confirm, required=None):
    """Prompt, save, and verify daemon permissions before startup."""
    from ..run import workspaces

    check = workspaces.daemon_access(project_dir, required)
    if check.allowed:
        return check
    if not confirm(check):
        raise DaemonPermissionDenied(
            f'{check.path} was not granted daemon workspace permissions')

    workspaces.grant_daemon_access(check.path, check.missing)
    verified = workspaces.daemon_access(check.path, check.required)
    if not verified.allowed:
        missing = ', '.join(sorted(verified.missing))
        raise DaemonPermissionDenied(
            f'{verified.path} still lacks daemon permissions: {missing}')
    return verified


def require_daemon_workspace(project_dir, required=None):
    """Fail closed when an already-running clayd receives an unsafe launch."""
    from ..run import workspaces

    check = workspaces.daemon_access(project_dir, required)
    if not check.allowed:
        missing = ', '.join(sorted(check.missing))
        raise DaemonPermissionDenied(
            f'{check.path} lacks advance daemon permissions: {missing}')
    return check


def _caller_project_dir():
    """Return the project directory that clayd must pass to the workflow."""
    from ..lib import paths
    return paths.project_dir()


def daemon_running(socket_path=None):
    """True when a clayd instance answers on the socket."""
    try:
        with DaemonClient(socket_path) as client:
            return bool(client.ping().get('ok'))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return False


def ensure_daemon(socket_path=None, timeout=3.0):
    """Start clayd if needed and return whether it responds before timeout."""
    if daemon_running(socket_path):
        return True

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    python = os.path.join(here, '.venv', 'bin', 'python')
    if not os.path.exists(python):
        python = sys.executable

    subprocess.Popen(
        [python, '-m', 'clay.daemon.server', '--fork'],
        cwd=here,
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.1)
        if daemon_running(socket_path):
            return True

    print('warning: clayd did not start in time', file=sys.stderr)
    return False


class DaemonClient:
    """Synchronous client for the clayd daemon.

    Usage:
        with DaemonClient() as c:
            c.start_workflow('path/to/wf.json', auto=True)
            workflows = c.list_workflows()
    """

    def __init__(self, socket_path=None):
        self._path = socket_path or SOCKET_PATH
        self._sock = None
        self._buf = ''

    def connect(self):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._path)
        return self

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def _send(self, msg):
        self._sock.sendall(encode(msg))

    def _recv(self):
        """Read one JSON-line response."""
        while '\n' not in self._buf:
            chunk = self._sock.recv(8192)
            if not chunk:
                raise ConnectionError('daemon disconnected')
            self._buf += chunk.decode('utf-8', errors='replace')
            if len(self._buf.encode('utf-8')) > protocol.MAX_FRAME_BYTES:
                raise ConnectionError('daemon response frame too large')
        line, self._buf = self._buf.split('\n', 1)
        return decode_line(line)

    def _request(self, msg):
        """Send a command and return the response."""
        self._send(msg)
        return self._recv()

    # ── Commands ─────────────────────────────────────────────────────────

    def ping(self):
        return self._request({'cmd': 'ping'})

    def list_workflows(self):
        resp = self._request({'cmd': 'list'})
        return resp.get('workflows', []) if resp.get('ok') else []

    def info(self, wf_id):
        return self._request({'cmd': 'info', 'id': wf_id})

    def start_workflow(self, filename, auto=False, daemon_mode=False):
        """Start a workflow through clayd.

        Authorizing the working directory happens here, in the client, before
        the request ever reaches clayd: this process is the one with a human
        attached, and the spawned subprocess may not be — daemon_mode makes it
        outright unattended, where workspaces.authorize() refuses rather than
        prompts (see its own docstring). Asking now, while someone is still
        here to answer, is the only point in this flow where that is possible.
        """
        project_dir = _caller_project_dir()
        if auto or daemon_mode:
            require_daemon_workspace(project_dir)
        return self._request({
            'cmd': 'start', 'workflow': filename,
            'auto': auto, 'daemon': daemon_mode,
            'project_dir': project_dir,
        })

    def start_workflow_json(self, data, label=None, auto=True, daemon_mode=False):
        project_dir = _caller_project_dir()
        if auto or daemon_mode:
            require_daemon_workspace(project_dir)
        return self._request({
            'cmd': 'start-json', 'data': data,
            'label': label, 'auto': auto, 'daemon': daemon_mode,
            'project_dir': project_dir,
        })

    def stop_workflow(self, wf_id):
        return self._request({'cmd': 'stop', 'id': wf_id})

    def kill_workflow(self, wf_id):
        return self._request({'cmd': 'kill', 'id': wf_id})

    def send_input(self, wf_id, text):
        return self._request({'cmd': 'input', 'id': wf_id, 'text': text})

    def set_option(self, wf_id, key, value):
        """Change a setting on a running workflow. See Daemon.set_option."""
        return self._request({'cmd': 'option', 'id': wf_id,
                              'key': key, 'value': value})

    def tail(self, wf_id, lines=50):
        resp = self._request({'cmd': 'tail', 'id': wf_id, 'lines': lines})
        return resp.get('lines', []) if resp.get('ok') else []

    def shutdown(self):
        return self._request({'cmd': 'shutdown'})

    # ── Subscriptions (streaming — blocks the connection) ────────────────

    def subscribe(self, wf_id=None):
        """Subscribe to events. Returns a generator that yields event dicts.
        This blocks the connection — no more request/response after this."""
        if wf_id:
            self._send({'cmd': 'subscribe', 'id': wf_id})
        else:
            self._send({'cmd': 'subscribe-all'})
        self._recv()  # ack
        return self._event_stream()

    def _event_stream(self):
        """Generator yielding events until connection closes."""
        while True:
            try:
                msg = self._recv()
                if msg:
                    yield msg
            except (ConnectionError, OSError):
                return


class EventSubscriber:
    """Dedicated event subscription connection with callback dispatch.

    Opens its own connection to clayd, subscribes, and reads events
    in a background thread. Callbacks are invoked from the reader thread.

    Usage (Qt UI):
        sub = EventSubscriber()
        sub.on_event(my_callback)
        sub.start()          # connects, subscribes, starts reader thread
        ...
        sub.stop()
    """

    def __init__(self, socket_path=None):
        self._path = socket_path or SOCKET_PATH
        self._sock = None
        self._buf = ''
        self._callbacks = []
        self._thread = None
        self._running = False

    def on_event(self, callback):
        """Register a callback(event_dict)."""
        self._callbacks.append(callback)

    @property
    def connected(self):
        return self._running

    def start(self, wf_id=None):
        """Connect, subscribe, and start the reader thread."""
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._path)
        self._running = True

        # Subscribe
        if wf_id:
            self._sock.sendall(encode({'cmd': 'subscribe', 'id': wf_id}))
        else:
            self._sock.sendall(encode({'cmd': 'subscribe-all'}))
        # Read ack
        self._recv_one()

        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def _recv_one(self):
        while '\n' not in self._buf:
            chunk = self._sock.recv(8192)
            if not chunk:
                raise ConnectionError('daemon disconnected')
            self._buf += chunk.decode('utf-8', errors='replace')
        line, self._buf = self._buf.split('\n', 1)
        return decode_line(line)

    def _read_loop(self):
        while self._running:
            try:
                msg = self._recv_one()
                if msg:
                    for cb in self._callbacks:
                        try:
                            cb(msg)
                        except Exception:
                            pass
            except (ConnectionError, OSError):
                self._running = False
                break
