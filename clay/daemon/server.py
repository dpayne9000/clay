"""clayd — system-level daemon that manages workflow subprocesses.

Usage:
    python -m clay.daemon.server          # foreground
    python -m clay.daemon.server --fork   # daemonize

Listens on ~/.clay/clayd.sock for JSON-line commands.
Each workflow runs as a real subprocess with its own event socket.
"""

import json
import os
import select
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field

from . import protocol
from ..lib import config
from ..run import events as run_events

RUNTIME_DIR = config.user_path('run')
SOCKET_PATH = os.path.join(RUNTIME_DIR, 'clayd.sock')
PID_FILE = os.path.join(RUNTIME_DIR, 'clayd.pid')


def _private_runtime_dir(path=RUNTIME_DIR):
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _same_uid(conn) -> bool:
    """Reject cross-user Unix-socket peers where the OS exposes credentials."""
    if hasattr(conn, 'getpeereid'):
        uid, _gid = conn.getpeereid()
        return uid == os.getuid()
    if hasattr(socket, 'SO_PEERCRED'):
        import struct
        _pid, uid, _gid = struct.unpack(
            '3i', conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return uid == os.getuid()
    return True


# ── Workflow process wrapper ─────────────────────────────────────────────────

@dataclass
class WorkflowProc:
    wf_id: str
    name: str
    filename: str
    auto: bool = False
    daemon_mode: bool = False
    pid: int = 0
    status: str = 'starting'       # starting | running | done | error | stopped
    started_at: float = 0.0
    exit_code: int = -1
    error_msg: str = ''
    iterations: int = 0
    current_step: str = ''
    current_action: str = ''
    events_received: int = 0
    pending_prompt: str = ''
    pending_prompt_id: str = ''

    # runtime (not serialized)
    proc: subprocess.Popen = field(default=None, repr=False)
    sock_path: str = ''
    server_sock: socket.socket = field(default=None, repr=False)
    stdout_lines: deque = field(default_factory=lambda: deque(maxlen=2000), repr=False)
    # Accepted event connection — carries engine events out and input
    # responses back in.
    event_conn: socket.socket = field(default=None, repr=False)
    event_conn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self):
        return {
            'id': self.wf_id, 'name': self.name, 'filename': self.filename,
            'pid': self.pid, 'status': self.status,
            'started_at': self.started_at, 'exit_code': self.exit_code,
            'error_msg': self.error_msg, 'iterations': self.iterations,
            'current_step': self.current_step, 'current_action': self.current_action,
            'events_received': self.events_received,
            'pending_prompt': self.pending_prompt,
            'pending_prompt_id': self.pending_prompt_id,
            'runtime': int(time.time() - self.started_at) if self.started_at else 0,
        }


# ── Daemon server ────────────────────────────────────────────────────────────

class ClayDaemon:
    """The system daemon process. Manages workflow subprocesses and serves
    clients over a unix socket."""

    def __init__(self):
        self._workflows = {}       # wf_id → WorkflowProc
        self._counter = 0
        self._running = False
        self._server_sock = None
        self._clients = []         # list of ClientHandler
        self._lock = threading.Lock()

    # ── Subprocess management ────────────────────────────────────────────

    def start_workflow(self, filename, auto=False, daemon_mode=False,
                       from_data=None, label=None, project_dir=None):
        """Start a new workflow subprocess. Returns the WorkflowProc.

        `project_dir` is the directory the workflow works in, sent by the
        client because this process cannot know it. It is passed to the child
        as --project-dir *and* used as the child's cwd, so that the two agree:
        an action that resolves a relative path through clay and a shell
        command that resolves one itself must land in the same place.
        """
        self._counter += 1
        wf_id = f'wf-{self._counter:04d}'

        name = label or os.path.splitext(os.path.basename(filename or 'api-run'))[0]
        wf = WorkflowProc(
            wf_id=wf_id, name=name, filename=filename or '',
            auto=auto, daemon_mode=daemon_mode,
            started_at=time.time(),
        )

        # Create event socket
        _private_runtime_dir()
        wf.sock_path = os.path.join(
            RUNTIME_DIR, f'{wf_id}-{secrets.token_hex(16)}.sock')
        if os.path.exists(wf.sock_path):
            os.unlink(wf.sock_path)
        wf.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        wf.server_sock.bind(wf.sock_path)
        os.chmod(wf.sock_path, 0o600)
        wf.server_sock.listen(1)
        wf.server_sock.settimeout(30)

        # Use the console script installed into the same environment as clayd.
        # A wheel contains the ``clay`` package and this generated command; it
        # does not contain the repository's top-level clay.py file.
        clay_command = str(Path(sys.executable).with_name('clay'))

        # Build command — global flags (--ci, --daemon) go before the subcommand
        if from_data:
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', prefix='clay-wf-', delete=False)
            json.dump(from_data, tmp)
            tmp.close()
            args = [clay_command, '--ci', '--project-dir', project_dir]
            if daemon_mode:
                args.append('--daemon')
            args += ['run-json', '--file', tmp.name,
                     '--events-socket', wf.sock_path]
            if not auto:
                args.append('--no-auto')
        else:
            args = [clay_command, '--ci', '--project-dir', project_dir]
            if daemon_mode:
                args.append('--daemon')
            args += ['run', filename, '--events-socket', wf.sock_path]
            if auto or daemon_mode:
                args.append('--auto')

        _log(f'[{wf_id}] spawning: {" ".join(args)}')

        try:
            wf.proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                # The caller's directory, not `here`. `here` is clay's own
                # install, and running the child there meant anything that read
                # cwd — a shell action without an explicit `cwd`, a relative
                # `root` — operated on the program instead of the user's work.
                cwd=project_dir,
                bufsize=0,
            )
            wf.pid = wf.proc.pid
            wf.status = 'running'
            _log(f'[{wf_id}] pid={wf.pid}')
        except Exception as e:
            wf.status = 'error'
            wf.error_msg = str(e)
            _log(f'[{wf_id}] spawn failed: {e}')
            self._cleanup_wf_socket(wf)

        with self._lock:
            self._workflows[wf_id] = wf

        if wf.status == 'running':
            # Start readers in background threads
            threading.Thread(target=self._read_stdout, args=(wf,), daemon=True).start()
            threading.Thread(target=self._read_stderr, args=(wf,), daemon=True).start()
            threading.Thread(target=self._read_events, args=(wf,), daemon=True).start()
            threading.Thread(target=self._wait_proc, args=(wf,), daemon=True).start()

        self._broadcast_event({
            'event': 'started', 'id': wf_id, 'pid': wf.pid,
            'name': wf.name, 'status': wf.status,
        })
        return wf

    def stop_workflow(self, wf_id):
        """Gracefully stop a workflow (SIGTERM, then SIGKILL after 3s)."""
        wf = self._workflows.get(wf_id)
        if not wf or not wf.proc:
            return False
        # Allow stopping even if already dead (to update status)
        if wf.proc.poll() is not None:
            # Already exited — just ensure status is updated
            if wf.status == 'running':
                wf.status = 'stopped'
                self._broadcast_event({
                    'event': 'finished', 'id': wf_id,
                    'exit_code': wf.proc.returncode, 'status': wf.status,
                })
            return True
        wf.status = 'stopped'
        try:
            wf.proc.terminate()
        except OSError:
            pass
        threading.Thread(target=self._force_kill, args=(wf,), daemon=True).start()
        return True

    def kill_workflow(self, wf_id):
        """Immediately kill a workflow (SIGKILL)."""
        wf = self._workflows.get(wf_id)
        if not wf or not wf.proc:
            return False
        if wf.proc.poll() is not None:
            if wf.status == 'running':
                wf.status = 'stopped'
            return True
        wf.status = 'stopped'
        try:
            wf.proc.kill()
        except OSError:
            pass
        return True

    def send_input(self, wf_id, text):
        """Answer a workflow's pending prompt over its event socket."""
        wf = self._workflows.get(wf_id)
        if not wf or not wf.proc or wf.proc.poll() is not None:
            return False
        if wf.event_conn is None:
            _log(f'[{wf_id}] input rejected: no event connection')
            return False

        line = json.dumps({
            'type': run_events.INPUT_RESPONSE,
            'id': wf.pending_prompt_id,
            'text': text,
        }) + '\n'

        try:
            with wf.event_conn_lock:
                wf.event_conn.sendall(line.encode('utf-8'))
        except OSError as e:
            _log(f'[{wf_id}] input send failed: {e}')
            return False

        wf.pending_prompt = ''
        wf.pending_prompt_id = ''
        return True

    def set_option(self, wf_id, key, value):
        """Change a setting on a running workflow over its event socket.

        The counterpart to send_input for things that are not answers: a
        front-end saying "/manual on" is not replying to a question, and there
        may be no question outstanding. Same socket, same lock, so an option
        line cannot interleave with an event mid-message.
        """
        wf = self._workflows.get(wf_id)
        if not wf or not wf.proc or wf.proc.poll() is not None:
            return False
        if wf.event_conn is None:
            _log(f'[{wf_id}] option rejected: no event connection')
            return False

        line = json.dumps({
            'type': run_events.OPTION_SET,
            'key': key,
            'value': value,
        }) + '\n'

        try:
            with wf.event_conn_lock:
                wf.event_conn.sendall(line.encode('utf-8'))
        except OSError as e:
            _log(f'[{wf_id}] option send failed: {e}')
            return False

        _log(f'[{wf_id}] option {key}={value}')
        return True

    def list_workflows(self):
        """Return info dicts for all workflows."""
        with self._lock:
            return [wf.to_dict() for wf in self._workflows.values()]

    def get_workflow(self, wf_id):
        wf = self._workflows.get(wf_id)
        return wf.to_dict() if wf else None

    def get_tail(self, wf_id, lines=50):
        wf = self._workflows.get(wf_id)
        if not wf:
            return []
        return list(wf.stdout_lines)[-lines:]

    # ── Subprocess I/O threads ───────────────────────────────────────────

    def _read_stdout(self, wf):
        """Read stdout line by line, parse __WEB_INPUT__ markers."""
        try:
            for raw in wf.proc.stdout:
                line = raw.decode('utf-8', errors='replace').rstrip('\n\r')
                self._process_stdout_line(wf, line)
        except Exception as e:
            _log(f'[{wf.wf_id}] stdout reader error: {e}')

    def _process_stdout_line(self, wf, line):
        wf.stdout_lines.append(line)
        self._broadcast_event({
            'event': 'stdout', 'id': wf.wf_id, 'line': line,
        })

    def _read_stderr(self, wf):
        try:
            for raw in wf.proc.stderr:
                line = raw.decode('utf-8', errors='replace').rstrip('\n\r')
                if line.strip():
                    wf.stdout_lines.append(f'[stderr] {line}')
                    self._broadcast_event({
                        'event': 'stderr', 'id': wf.wf_id, 'line': line,
                    })
        except Exception as e:
            _log(f'[{wf.wf_id}] stderr reader error: {e}')

    def _read_events(self, wf):
        """Accept one connection on the event socket, read JSON-line events."""
        try:
            conn, _ = wf.server_sock.accept()
        except (socket.timeout, OSError):
            _log(f'[{wf.wf_id}] event socket: no connection (timeout or closed)')
            return

        wf.event_conn = conn
        if not _same_uid(conn):
            _log(f'[{wf.wf_id}] rejected event connection from another user')
            conn.close()
            wf.event_conn = None
            return
        buf = ''
        try:
            while True:
                chunk = conn.recv(8192)
                if not chunk:
                    break
                buf += chunk.decode('utf-8', errors='replace')
                if len(buf.encode('utf-8')) > protocol.MAX_FRAME_BYTES:
                    _log(f'[{wf.wf_id}] event frame exceeded size limit')
                    break
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        self._handle_engine_event(wf, event)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
        finally:
            wf.event_conn = None
            try:
                conn.close()
            except Exception:
                pass

    def _handle_engine_event(self, wf, event):
        wf.events_received += 1
        t = event.get('type', '')
        if t == run_events.INPUT_REQUEST:
            # A workflow is waiting on a human. Surface it to subscribed
            # front-ends (clay ui, telegram, ...) — they answer with
            # {'cmd': 'input'}, which send_input() routes back.
            wf.pending_prompt = event.get('prompt', '')
            wf.pending_prompt_id = event.get('id', '')
            self._broadcast_event({
                'event': 'prompt', 'id': wf.wf_id,
                'prompt_id': wf.pending_prompt_id, 'text': wf.pending_prompt,
            })
            return
        if t == 'step.start':
            wf.current_step = event.get('step', '')
            wf.status = 'running'
        elif t == 'action.start':
            wf.current_action = f"{event.get('action_type', '')}:{event.get('id', '')}"
        elif t == 'action.complete':
            wf.current_action = ''
        elif t == 'loop.iteration':
            wf.iterations += 1

        self._broadcast_event({
            'event': 'workflow', 'id': wf.wf_id, 'data': event,
        })

    def _wait_proc(self, wf):
        """Wait for subprocess to exit, update status, reap zombie."""
        exit_code = wf.proc.wait()  # this reaps the child
        wf.exit_code = exit_code
        if wf.status not in ('stopped',):
            wf.status = 'done' if exit_code == 0 else 'error'
        if exit_code != 0 and not wf.error_msg:
            wf.error_msg = f'exit code {exit_code}'
        _log(f'[{wf.wf_id}] exited with code {exit_code}, status={wf.status}')
        self._cleanup_wf_socket(wf)
        self._broadcast_event({
            'event': 'finished', 'id': wf.wf_id,
            'exit_code': exit_code, 'status': wf.status,
        })

    def _force_kill(self, wf):
        """Give process 3s after SIGTERM, then SIGKILL."""
        try:
            wf.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                wf.proc.kill()
            except OSError:
                pass

    def _cleanup_wf_socket(self, wf):
        if wf.server_sock:
            try:
                wf.server_sock.close()
            except Exception:
                pass
            wf.server_sock = None
        if wf.sock_path and os.path.exists(wf.sock_path):
            try:
                os.unlink(wf.sock_path)
            except Exception:
                pass

    # ── Client event broadcasting ────────────────────────────────────────

    def _broadcast_event(self, event, subscriber_filter=None):
        """Send an event to all subscribed clients."""
        wf_id = event.get('id')
        with self._lock:
            for client in list(self._clients):
                if not client.subscribed:
                    continue
                if client.subscribe_id and client.subscribe_id != wf_id:
                    continue
                client.send(event)

    # ── Socket server ────────────────────────────────────────────────────

    def run(self):
        """Main loop — listen for client connections."""
        _private_runtime_dir(os.path.dirname(SOCKET_PATH))
        if os.path.exists(SOCKET_PATH):
            try:
                test = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                test.connect(SOCKET_PATH)
                test.close()
                print(f'clayd: another instance is already running on {SOCKET_PATH}',
                      file=sys.stderr)
                sys.exit(1)
            except ConnectionRefusedError:
                os.unlink(SOCKET_PATH)

        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(SOCKET_PATH)
        os.chmod(SOCKET_PATH, 0o600)
        self._server_sock.listen(8)
        self._running = True

        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

        # Signal handlers only work in the main thread
        import threading as _th
        if _th.current_thread() is _th.main_thread():
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)

        _log(f'clayd: listening on {SOCKET_PATH} (pid {os.getpid()})')

        try:
            while self._running:
                try:
                    readable, _, _ = select.select([self._server_sock], [], [], 1.0)
                except (ValueError, OSError):
                    break
                if readable:
                    try:
                        conn, _ = self._server_sock.accept()
                        if not _same_uid(conn):
                            _log('clayd: rejected connection from another user')
                            conn.close()
                            continue
                        client = ClientHandler(conn, self)
                        with self._lock:
                            self._clients.append(client)
                        client.start()
                    except OSError:
                        break
        finally:
            self._shutdown()

    def _handle_signal(self, sig, frame):
        self._running = False

    def _shutdown(self):
        """Clean shutdown — stop all workflows, close sockets."""
        _log('clayd: shutting down...')
        self._broadcast_event({'event': 'daemon-stopping'})

        for wf_id in list(self._workflows):
            self.stop_workflow(wf_id)

        # Wait briefly for processes to exit
        deadline = time.time() + 5
        for wf in self._workflows.values():
            if wf.proc and wf.proc.poll() is None:
                remaining = max(0, deadline - time.time())
                try:
                    wf.proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    try:
                        wf.proc.kill()
                        wf.proc.wait(timeout=1)
                    except Exception:
                        pass

        with self._lock:
            for client in self._clients:
                client.close()
            self._clients.clear()

        if self._server_sock:
            self._server_sock.close()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)
        _log('clayd: stopped')

    def remove_client(self, client):
        with self._lock:
            try:
                self._clients.remove(client)
            except ValueError:
                pass


# ── Client connection handler ────────────────────────────────────────────────

class ClientHandler:
    """Handles a single client connection in its own thread."""

    def __init__(self, conn, daemon):
        self.conn = conn
        self.daemon = daemon
        self.subscribed = False
        self.subscribe_id = None
        self._thread = None
        self._alive = True
        self._write_lock = threading.Lock()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send(self, msg):
        if not self._alive:
            return
        with self._write_lock:
            try:
                self.conn.sendall(protocol.encode(msg))
            except Exception:
                self._alive = False

    def close(self):
        self._alive = False
        try:
            self.conn.close()
        except Exception:
            pass

    def _run(self):
        buf = ''
        try:
            while self._alive:
                try:
                    data = self.conn.recv(8192)
                except OSError:
                    break
                if not data:
                    break
                buf += data.decode('utf-8', errors='replace')
                if len(buf.encode('utf-8')) > protocol.MAX_FRAME_BYTES:
                    self.send({'ok': False, 'error': 'command frame too large'})
                    break
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    msg = protocol.decode_line(line)
                    if msg:
                        self._handle(msg)
        finally:
            self.daemon.remove_client(self)
            self.close()

    @staticmethod
    def _project_dir(msg):
        """Return (project directory, error). Default to $CLAY_HOME/workspaces."""
        raw = (msg.get('project_dir') or '').strip()
        if not raw:
            fallback = config.user_path('workspaces')
            try:
                os.makedirs(fallback, exist_ok=True)
            except OSError as exc:
                return None, (f'start: no project_dir sent and the default '
                              f'{fallback} could not be created: {exc}')
            return fallback, None
        if not os.path.isdir(raw):
            return None, f'start: project_dir is not a directory: {raw}'
        return raw, None

    @staticmethod
    def _daemon_access_error(project_dir, *, auto=False, daemon_mode=False):
        """Reject unattended work even if a client bypassed its preflight."""
        if not (auto or daemon_mode):
            return None
        from ..run import workspaces
        check = workspaces.daemon_access(project_dir)
        if check.allowed:
            return None
        missing = ', '.join(sorted(check.missing))
        return (f'start: {check.path} lacks advance daemon permissions: '
                f'{missing}')

    def _handle(self, msg):
        cmd = msg.get('cmd', '')

        if cmd == 'ping':
            self.send({'ok': True, 'pong': True})

        elif cmd == 'list':
            self.send({'ok': True, 'workflows': self.daemon.list_workflows()})

        elif cmd == 'info':
            info = self.daemon.get_workflow(msg.get('id', ''))
            if info:
                self.send({'ok': True, 'workflow': info})
            else:
                self.send({'ok': False, 'error': 'workflow not found'})

        elif cmd == 'start':
            project_dir, error = self._project_dir(msg)
            error = error or self._daemon_access_error(
                project_dir,
                auto=msg.get('auto', False),
                daemon_mode=msg.get('daemon', False),
            )
            if error:
                self.send({'ok': False, 'error': error})
                return
            wf = self.daemon.start_workflow(
                filename=msg.get('workflow', ''),
                auto=msg.get('auto', False),
                daemon_mode=msg.get('daemon', False),
                project_dir=project_dir,
            )
            self.send({'ok': True, 'id': wf.wf_id, 'name': wf.name,
                        'pid': wf.pid, 'status': wf.status})

        elif cmd == 'start-json':
            project_dir, error = self._project_dir(msg)
            error = error or self._daemon_access_error(
                project_dir,
                auto=msg.get('auto', True),
                daemon_mode=msg.get('daemon', False),
            )
            if error:
                self.send({'ok': False, 'error': error})
                return
            wf = self.daemon.start_workflow(
                filename=None,
                auto=msg.get('auto', True),
                daemon_mode=msg.get('daemon', False),
                from_data=msg.get('data'),
                label=msg.get('label'),
                project_dir=project_dir,
            )
            self.send({'ok': True, 'id': wf.wf_id, 'name': wf.name,
                        'pid': wf.pid, 'status': wf.status})

        elif cmd == 'stop':
            ok = self.daemon.stop_workflow(msg.get('id', ''))
            self.send({'ok': ok, 'error': '' if ok else 'cannot stop'})

        elif cmd == 'kill':
            ok = self.daemon.kill_workflow(msg.get('id', ''))
            self.send({'ok': ok, 'error': '' if ok else 'cannot kill'})

        elif cmd == 'input':
            ok = self.daemon.send_input(msg.get('id', ''), msg.get('text', ''))
            self.send({'ok': ok})

        elif cmd == 'option':
            ok = self.daemon.set_option(msg.get('id', ''), msg.get('key', ''),
                                        msg.get('value'))
            self.send({'ok': ok, 'error': '' if ok else 'cannot set option'})

        elif cmd == 'subscribe':
            self.subscribed = True
            self.subscribe_id = msg.get('id')
            self.send({'ok': True, 'subscribed': self.subscribe_id or 'all'})

        elif cmd == 'subscribe-all':
            self.subscribed = True
            self.subscribe_id = None
            self.send({'ok': True, 'subscribed': 'all'})

        elif cmd == 'unsubscribe':
            self.subscribed = False
            self.subscribe_id = None
            self.send({'ok': True})

        elif cmd == 'tail':
            lines = self.daemon.get_tail(msg.get('id', ''), msg.get('lines', 50))
            self.send({'ok': True, 'lines': lines})

        elif cmd == 'shutdown':
            self.send({'ok': True, 'message': 'shutting down'})
            self.daemon._running = False

        else:
            self.send({'ok': False, 'error': f'unknown command: {cmd}'})


# ── Logging ──────────────────────────────────────────────────────────────────

def _log(msg):
    """Write to stdout (which is the daemon log file when forked)."""
    ts = time.strftime('%H:%M:%S')
    print(f'[{ts}] {msg}', flush=True)


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='clay daemon — workflow process manager')
    parser.add_argument('--fork', action='store_true', help='Daemonize (fork to background)')
    args = parser.parse_args()

    if args.fork:
        # Ensure log dir exists before forking
        os.makedirs(os.path.expanduser('~/.clay'), exist_ok=True)
        pid = os.fork()
        if pid > 0:
            print(f'clayd: forked to background (pid {pid})')
            sys.exit(0)
        # Child: detach
        os.setsid()
        sys.stdin.close()
        log_path = os.path.expanduser('~/.clay/clayd.log')
        log_fd = open(log_path, 'a', buffering=1)
        os.dup2(log_fd.fileno(), 1)
        os.dup2(log_fd.fileno(), 2)

    daemon = ClayDaemon()
    daemon.run()


if __name__ == '__main__':
    main()
