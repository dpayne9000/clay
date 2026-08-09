"""Workflow input channel — one bidirectional path for human prompts.

A workflow asks humans questions (humanDecision, humanShell approval) and must
work in three situations:

    plain `clay run` in a terminal          → TerminalIO  (builtins.input)
    clayd-managed run (--events-socket)     → SocketIO    (JSON lines)
    embedded/test in-process caller         → QueueIO     (thread to thread)

Selection follows launch mode, never an env var: the launcher attaches the
channel that matches how it started the run, and anything that attaches none
prompts on the terminal.

Socket protocol (JSON lines, same framing as logger events):

    workflow → clayd    {"type": "input.request",  "id": ..., "prompt": ...}
    clayd → workflow    {"type": "input.response", "id": ..., "text": ...}

Front-ends (clay ui, telegram, future channels) never speak to a workflow
directly — clayd relays, so one implementation serves all of them.

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
    """Drop every front-end's busy indicator — a question is going out.

    Called by all three channels, not just the terminal, because each has its
    own reason. A terminal spinner rewrites the line it lives on, so one still
    running when builtins.input() draws the question eats the question. A
    Telegram typing indicator left up beside a question the bot has already
    asked claims the bot is still composing. A Qt "working" label next to a
    live input row says the same.

    This is what keeps the dispatcher's busy honest under manual approval:
    applyFileWrites is an ordinary action that raises an indicator and then
    blocks here, and no list of action types in the dispatcher could know that.
    """
    logger.busy(False)


class TerminalIO:
    """Prompts the human on the local terminal.

    A terminal session has exactly one moment where the person has the floor —
    a prompt — so that is where session commands are recognised. A line that
    parses as one is answered, drawn as a command rather than echoed back as
    though it were an answer, and the same question is asked again; the
    workflow never sees it and never has to know the grammar exists.
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
    """Prompts a human through whichever front-end clayd is relaying to.

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

        Raises ChannelClosed if the socket drops while waiting — a workflow
        that can no longer reach its human must fail loudly, not guess.
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
                # Only one prompt can be outstanding per workflow, so an id
                # mismatch is a relay quirk, not an ambiguity.
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
            # A setting change from a front-end in another process. It arrives
            # between prompts, not in answer to one, so it is handled here on
            # the reader thread rather than by deliver(): there may be no
            # pending prompt at all, and a workflow mid-model-call still has to
            # be gated by the time it reaches the next write.
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
    """Prompts a human in *this* process, from another thread.

    The channel `clay ui` uses for an in-process run. There is no socket
    because there is no second process: the engine runs on a worker thread and
    the answer is typed on the GUI thread, so a queue is the whole transport.

    Without it such a run falls through to TerminalIO, whose builtins.input()
    reads the terminal the app was launched from — or raises EOFError when
    there is no tty — never the window the person is looking at.

    The request goes out on the event bus rather than down a private channel,
    so it reaches every listener the run already has, the log file included,
    and a front-end handles it in the same switch as every other event.
    """

    def __init__(self):
        self._inbox: queue.Queue = queue.Queue(maxsize=1)
        self._closed = threading.Event()
        self._pending = ''
        self._lock = threading.Lock()

    def prompt(self, prompt_id: str, text: str) -> str:
        """Ask, then block until deliver() supplies an answer.

        Raises ChannelClosed if the channel closes while waiting — same
        contract as SocketIO: a workflow that can no longer reach its human
        must fail loudly, not guess.
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
    """Return the active input channel — socket when attached, else terminal."""
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
