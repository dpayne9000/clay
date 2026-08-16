"""Provide one bidirectional input path for workflow prompts.

A workflow asks humans questions (humanDecision, humanShell approval) and must
work in three situations:

    plain `clay run` in a terminal          → TerminalIO  (builtins.input)
    clayd-managed run (--events-socket)     → SocketIO    (JSON lines)
    embedded/test in-process caller         → QueueIO     (thread to thread)

The launcher attaches the channel for its launch mode. Runs without an attached
channel use the terminal; environment variables do not select the channel.

Socket protocol (JSON lines, same framing as logger events):

    workflow → clayd    {"type": "input.request",  "id": ..., "prompt": ...}
    clayd → workflow    {"type": "input.response", "id": ..., "text": ...}

clayd relays messages between front-ends and workflows, allowing all remote
front-ends to share one socket implementation.

Usage from an action handler:

    from ..run import io
    answer = io.get().prompt(action.get('id', ''), 'How many retries?')
"""

import json
import queue
import threading

from . import commands
from . import events
from . import logger
from . import termui


class ChannelClosed(RuntimeError):
    """The input channel closed while a prompt was awaiting its response."""


def _floor_to_human() -> None:
    """Clear busy indicators before presenting a question.

    A terminal spinner can overwrite a question. Telegram typing indicators and
    Qt working labels also incorrectly imply that processing continues while
    the workflow is waiting for input.

    Clearing indicators here also covers ordinary actions that pause for manual
    approval, which the dispatcher cannot identify by action type.
    """
    logger.busy(False)


class TerminalIO:
    """Prompt a human on the local terminal.

    Session commands are recognized at prompts. A command is handled and shown
    locally before the question is repeated, so the workflow never receives it.
    """

    def prompt(self, prompt_id: str, text: str) -> str:
        _floor_to_human()
        while True:
            answer = input(f"\n{text}\n> ")
            outcome = commands.handle(answer)
            if outcome is None:
                return answer
            termui.command_echo(answer.strip(), outcome)

    def close(self) -> None:
        pass


class SocketIO:
    """Prompt a human through the front-end connected by clayd.

    Owns a reader thread for the workflow's end of the events socket. Writes
    share the logger's send lock so event lines and prompt lines cannot
    interleave mid-message on the stream.
    """

    def __init__(self, sock, send_lock=None):
        self._sock = sock
        self._send_lock = send_lock or threading.Lock()
        self._pending: dict[str, queue.Queue] = {}
        self._pending_lock = threading.Lock()
        self._closed = threading.Event()
        self._reader = threading.Thread(
            target=self._read_loop,
            name='workflow-io',
            daemon=True,
        )
        self._reader.start()

    # ── prompting ────────────────────────────────────────────────────────

    def prompt(self, prompt_id: str, text: str) -> str:
        """Send an input.request and block until the response arrives.

        Raise ChannelClosed if the socket closes while waiting. A workflow must
        not infer an answer after losing its input channel.
        """
        _floor_to_human()
        if self._closed.is_set():
            raise ChannelClosed('input channel is closed')

        key = str(prompt_id or '')
        inbox: queue.Queue = queue.Queue(maxsize=1)

        with self._pending_lock:
            if key in self._pending:
                raise RuntimeError(
                    f"a prompt for '{key}' is already awaiting a response")
            self._pending[key] = inbox

        try:
            self._send({'type': events.INPUT_REQUEST, 'id': key, 'prompt': text})
            answer = inbox.get()
        finally:
            with self._pending_lock:
                self._pending.pop(key, None)

        if answer is _CLOSED:
            raise ChannelClosed(
                f"input channel closed while waiting on prompt '{key}'")
        return answer

    def deliver(self, prompt_id: str, text: str) -> bool:
        """Hand a response to the waiting prompt. Returns False if unclaimed."""
        key = str(prompt_id or '')

        with self._pending_lock:
            inbox = self._pending.get(key)
            if inbox is None and len(self._pending) == 1:
                # One workflow can have only one pending prompt, so accept a
                # mismatched relay ID when the intended recipient is unambiguous.
                inbox = next(iter(self._pending.values()))

        if inbox is None:
            logger.debug(f'io: dropped input.response for unknown prompt {key!r}')
            return False

        try:
            inbox.put_nowait(text)
            return True
        except queue.Full:
            logger.debug(f'io: prompt {key!r} already answered')
            return False

    def close(self) -> None:
        """Stop reading and release every waiting prompt."""
        if self._closed.is_set():
            return
        self._closed.set()

        with self._pending_lock:
            waiting = list(self._pending.values())
        for inbox in waiting:
            try:
                inbox.put_nowait(_CLOSED)
            except queue.Full:
                pass

    # ── internals ────────────────────────────────────────────────────────

    def _send(self, message: dict) -> None:
        line = (json.dumps(message, default=str) + '\n').encode('utf-8')
        with self._send_lock:
            try:
                self._sock.sendall(line)
            except OSError as exc:
                self.close()
                raise ChannelClosed(f'input channel send failed: {exc}') from exc

    def _read_loop(self) -> None:
        buffer = ''
        try:
            while not self._closed.is_set():
                try:
                    chunk = self._sock.recv(8192)
                except OSError:
                    break
                if not chunk:
                    break

                buffer += chunk.decode('utf-8', errors='replace')
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    self._handle_line(line.strip())
        finally:
            self.close()

    def _handle_line(self, line: str) -> None:
        if not line:
            return
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            return
        if not isinstance(message, dict):
            return

        kind = message.get('type')
        if kind == events.INPUT_RESPONSE:
            self.deliver(message.get('id', ''), message.get('text', ''))
        elif kind == events.OPTION_SET:
            # Apply cross-process setting changes on the reader thread because
            # they are independent of prompts. This ensures that a change made
            # during a model call applies before the next gated operation.
            self._set_option(message.get('key', ''), message.get('value'))

    def _set_option(self, key: str, value) -> None:
        from . import approval  # deferred: approval's confirm() imports io

        if key == 'manual':
            approval.set_manual(bool(value))
        elif key in approval.GATES:
            approval.set_gate(key, bool(value))
        else:
            logger.warn(f'io: ignored option.set for unknown key {key!r}')
            return
        logger.info(f'io: {approval.summary()}')


class QueueIO:
    """Prompt a human through another thread in the same process.

    The channel `clay ui` uses for an in-process run. There is no socket
    because there is no second process: the engine runs on a worker thread and
    the answer is typed on the GUI thread, so a queue is the whole transport.

    Without this channel, the run would use TerminalIO and read from the
    launching terminal instead of the application window.

    Requests use the event bus so existing listeners and the log receive them
    through the same path as other workflow events.
    """

    def __init__(self):
        self._inbox: queue.Queue = queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._pending = ''
        self._lock = threading.Lock()

    def prompt(self, prompt_id: str, text: str) -> str:
        """Ask, then block until deliver() supplies an answer.

        Raise ChannelClosed if the channel closes while waiting. This matches
        SocketIO and prevents the workflow from inferring an answer.
        """
        _floor_to_human()
        if self._closed.is_set():
            raise ChannelClosed('input channel is closed')

        key = str(prompt_id or '')
        with self._lock:
            if self._pending:
                raise RuntimeError(
                    f"a prompt for '{self._pending}' is already awaiting a response")
            self._pending = key

        try:
            logger.emit(events.INPUT_REQUEST, id=key, prompt=text)
            answer = self._inbox.get()
        finally:
            with self._lock:
                self._pending = ''

        if answer is _CLOSED:
            raise ChannelClosed(
                f"input channel closed while waiting on prompt '{key}'")
        return answer

    def deliver(self, prompt_id: str, text: str) -> bool:
        """Hand an answer to the waiting prompt. Returns False if none is.

        `prompt_id` is accepted for parity with SocketIO but not matched on:
        prompt() permits exactly one outstanding question, so there is nothing
        to disambiguate and matching could only drop a correct answer.
        """
        with self._lock:
            if not self._pending:
                return False
        try:
            self._inbox.put_nowait(text)
            return True
        except queue.Full:
            return False

    def close(self) -> None:
        """Release a waiting prompt so a cancelled run cannot wedge its thread."""
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._inbox.put_nowait(_CLOSED)
        except queue.Full:
            pass


_CLOSED = object()


# ── Module-level channel ─────────────────────────────────────────────────────

_terminal = TerminalIO()
_channel = None


def get():
    """Return the attached input channel, or the terminal channel by default."""
    return _channel or _terminal


def attach_socket(sock, send_lock=None) -> SocketIO:
    """Route prompts over an events socket. Called by logger.start_socket_bridge."""
    return attach(SocketIO(sock, send_lock))


def attach(channel):
    """Route prompts through a caller-supplied channel.

    The socket exists because clayd and the workflow are separate processes.
    QueueIO remains the caller-supplied in-process/testing implementation of
    the same contract; the Qt desktop UI no longer runs workflows in-process.

    A channel needs `prompt(id, text) -> str` and `close()`.
    """
    global _channel
    detach()
    _channel = channel
    return channel


def detach() -> None:
    """Return to terminal prompting. Called by logger.stop_socket_bridge."""
    global _channel
    if _channel is not None:
        _channel.close()
        _channel = None
