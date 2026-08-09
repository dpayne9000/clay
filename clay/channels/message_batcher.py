"""Coalesces a stream of short lines into whole chat messages.

A workflow turn emits a dozen or more events — a step header, an action line
per action, the model prompt echo, the file-written logs. The terminal can
draw each one the instant it arrives because a terminal line costs nothing. A
chat thread cannot: one message per event is a dozen notifications, which is
why the Telegram front-end used to drop progress events entirely rather than
relay them.

Dropping them was the wrong half of the trade. This class keeps the events and
fixes the cost: lines accumulate, and go out as one message once the stream
goes quiet for `interval` seconds or the buffer grows past `max_chars`.

The front-end must flush() before anything that depends on ordering — a
question put to the user, or the closing summary — so the narration cannot
arrive after the thing it was narrating.

Thread-safe. add() is called from the daemon subscriber's reader thread while
the worker thread drains.
"""

import threading
import time

#: How often the worker wakes to check whether the stream has gone quiet.
TICK = 0.25


def _split(text: str, limit: int) -> list:
    """`text` as messages of at most `limit` characters, in order.

    Breaks on line boundaries so a file echo or a command's output stays
    readable across the split. A single line longer than the limit — minified
    JSON, a base64 blob — is cut at the limit, because the alternative is a
    message the transport refuses whole.
    """
    if len(text) <= limit:
        return [text]

    # `current` is None rather than '' so a blank line joins the chunk it
    # belongs to instead of being dropped as falsy.
    chunks, current = [], None
    for line in text.split('\n'):
        while len(line) > limit:
            if current is not None:
                chunks.append(current)
                current = None
            chunks.append(line[:limit])
            line = line[limit:]
        if current is None:
            current = line
        elif len(current) + 1 + len(line) <= limit:
            current += '\n' + line
        else:
            chunks.append(current)
            current = line
    if current is not None:
        chunks.append(current)
    # An all-blank chunk is nothing to send and some transports reject it.
    return [chunk for chunk in chunks if chunk.strip()]


class MessageBatcher:
    """Buffers lines and hands them to `send` as one joined message."""

    def __init__(self, send, *, interval: float = 1.5, max_chars: int = 3500):
        if interval <= 0:
            raise ValueError('interval must be positive')
        if max_chars <= 0:
            raise ValueError('max_chars must be positive')

        self._send = send
        self._interval = interval
        self._max_chars = max_chars

        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._pending_chars = 0
        self._last_add = 0.0

        self._stopped = threading.Event()
        self._thread = None

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self) -> 'MessageBatcher':
        """Start the drain thread. Idempotent."""
        if self._thread is not None:
            return self
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._loop, name='chat-batcher', daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Flush what is buffered, then stop the drain thread."""
        self._stopped.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=TICK * 4)
        self.flush()

    # ── buffering ────────────────────────────────────────────────────────

    def add(self, text) -> None:
        """Queue one line. Sends immediately if the buffer is already full."""
        if text is None:
            return
        line = str(text).strip()
        if not line:
            return

        with self._lock:
            self._pending.append(line)
            self._pending_chars += len(line) + 1
            self._last_add = time.monotonic()
            full = self._pending_chars >= self._max_chars

        if full:
            self.flush()

    def flush(self) -> None:
        """Send everything buffered. Safe when empty.

        One message where it fits. A single add() can be far larger than
        max_chars on its own — a file echo or a command's whole output — and a
        transport with a per-message limit rejects the send outright, so
        oversized content is split rather than handed over to fail.
        """
        with self._lock:
            if not self._pending:
                return
            lines = self._pending
            self._pending = []
            self._pending_chars = 0

        for chunk in _split('\n'.join(lines), self._max_chars):
            self._send(chunk)

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._pending)

    # ── internals ────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stopped.wait(TICK):
            with self._lock:
                quiet = (
                    bool(self._pending)
                    and time.monotonic() - self._last_add >= self._interval
                )
            if not quiet:
                continue
            # A send that raises must not kill the drain thread — every later
            # line would then sit in the buffer forever with nothing to
            # report it. The caller's send is responsible for reporting its
            # own failure; here the buffer has already been drained.
            try:
                self.flush()
            except Exception:
                pass
