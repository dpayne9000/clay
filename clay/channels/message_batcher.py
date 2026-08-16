"""Combine short event lines into bounded chat messages.

A workflow turn can emit many progress events. A terminal can display each
event immediately, but sending each event as a chat message creates excessive
notifications.

This class retains those events while batching them. It sends accumulated lines
after `interval` seconds of inactivity or when the buffer reaches `max_chars`.

The front-end must call flush() before ordered output such as a question or
closing summary, ensuring earlier progress appears first.

The class is thread-safe because the daemon reader adds lines while a worker
thread drains them.
"""

import threading
import time

#: Interval between checks for an inactive input stream.
TICK = 0.25


def _split(text: str, limit: int) -> list:
    """Split `text` into ordered messages of at most `limit` characters.

    Prefer line boundaries to preserve readable file and command output. Split
    an individual oversized line at the exact limit so transports can accept it.
    """
    if len(text) <= limit:
        return [text]

    # None distinguishes an empty chunk from a blank line that must be retained.
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
    # Remove all-blank chunks because some transports reject them.
    return [chunk for chunk in chunks if chunk.strip()]


class MessageBatcher:
    """Buffer lines and pass joined messages to `send`."""

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
        """Start the drain thread if it is not already running."""
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
        """Queue one line and flush when the buffer reaches its limit."""
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
        """Send all buffered content, doing nothing when the buffer is empty.

        Send one message when possible. Split oversized content before passing
        it to a transport with a per-message limit.
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
            # Keep the drain thread alive after a send failure. The send callback
            # reports its own errors, and flush() has already drained the buffer.
            try:
                self.flush()
            except Exception:
                pass
