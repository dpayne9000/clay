"""Unit tests for the chat message batcher.

Batching is what makes relaying the full event stream affordable in a message
thread. These tests use a fake sink and, where timing matters, a very short
interval — nothing here touches Telegram.
"""

import threading
import time
import unittest

from ...channels.message_batcher import MessageBatcher, _split


class _Sink:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail
        self._lock = threading.Lock()

    def __call__(self, text):
        with self._lock:
            self.messages.append(text)
        if self.fail:
            raise RuntimeError('send failed')


class ConstructionTest(unittest.TestCase):

    def test_non_positive_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            MessageBatcher(_Sink(), interval=0)

    def test_non_positive_max_chars_is_rejected(self):
        with self.assertRaises(ValueError):
            MessageBatcher(_Sink(), max_chars=0)


class BufferingTest(unittest.TestCase):

    def setUp(self):
        self.sink = _Sink()
        # No start() — nothing drains unless a test asks it to.
        self.batcher = MessageBatcher(self.sink, interval=3600)

    def test_nothing_is_sent_until_flush(self):
        self.batcher.add('one')
        self.batcher.add('two')
        self.assertEqual(self.sink.messages, [])

    def test_flush_joins_lines_into_one_message(self):
        self.batcher.add('one')
        self.batcher.add('two')
        self.batcher.flush()
        self.assertEqual(self.sink.messages, ['one\ntwo'])

    def test_flush_when_empty_sends_nothing(self):
        self.batcher.flush()
        self.batcher.add('one')
        self.batcher.flush()
        self.batcher.flush()
        self.assertEqual(self.sink.messages, ['one'])

    def test_blank_lines_are_dropped(self):
        self.batcher.add('')
        self.batcher.add('   ')
        self.batcher.add(None)
        self.assertEqual(self.batcher.pending, 0)

    def test_lines_are_stripped(self):
        self.batcher.add('  padded  ')
        self.batcher.flush()
        self.assertEqual(self.sink.messages, ['padded'])

    def test_full_buffer_sends_without_waiting(self):
        batcher = MessageBatcher(self.sink, interval=3600, max_chars=20)
        batcher.add('x' * 25)
        # Oversized on its own, so it goes out split rather than as one
        # message the transport would refuse.
        self.assertEqual(self.sink.messages, ['x' * 20, 'x' * 5])
        self.assertEqual(batcher.pending, 0)


class SplitTest(unittest.TestCase):
    """A file echo or a command's whole output can be far larger than one
    chat message. Splitting happens here so no transport is handed a message
    it will reject."""

    def test_short_text_is_one_message(self):
        self.assertEqual(_split('one\ntwo', 100), ['one\ntwo'])

    def test_split_falls_on_line_boundaries(self):
        text = 'aaaa\nbbbb\ncccc'
        self.assertEqual(_split(text, 10), ['aaaa\nbbbb', 'cccc'])

    def test_a_line_longer_than_the_limit_is_cut(self):
        self.assertEqual(_split('short\n' + 'y' * 12, 10),
                         ['short', 'y' * 10, 'yy'])

    def test_every_chunk_is_within_the_limit(self):
        text = '\n'.join(f'line {n} of the echoed file' for n in range(200))
        chunks = _split(text, 120)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))
        self.assertEqual('\n'.join(chunks), text)

    def test_blank_lines_inside_a_chunk_survive(self):
        self.assertEqual(_split('a\n\nb', 100), ['a\n\nb'])

    def test_all_blank_text_sends_nothing(self):
        self.assertEqual(_split('   \n  ', 2), [])

    def test_a_file_echo_reaches_the_sink_whole(self):
        sink = _Sink()
        batcher = MessageBatcher(sink, interval=3600, max_chars=100)
        body = '\n'.join(f'    line_{n} = {n}' for n in range(60))
        batcher.add(f'drop.py written\n{body}')
        batcher.flush()
        self.assertTrue(all(len(m) <= 100 for m in sink.messages))
        self.assertEqual('\n'.join(sink.messages), f'drop.py written\n{body}')


class DrainThreadTest(unittest.TestCase):

    def test_quiet_stream_is_flushed_automatically(self):
        sink = _Sink()
        batcher = MessageBatcher(sink, interval=0.05).start()
        self.addCleanup(batcher.stop)

        batcher.add('one')
        batcher.add('two')

        deadline = time.monotonic() + 3
        while not sink.messages and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(sink.messages, ['one\ntwo'])

    def test_a_failing_send_does_not_kill_the_drain_thread(self):
        sink = _Sink(fail=True)
        batcher = MessageBatcher(sink, interval=0.05).start()
        self.addCleanup(batcher.stop)

        batcher.add('first')
        deadline = time.monotonic() + 3
        while len(sink.messages) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)

        sink.fail = False
        batcher.add('second')
        deadline = time.monotonic() + 3
        while len(sink.messages) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)

        self.assertEqual(sink.messages, ['first', 'second'])

    def test_stop_flushes_what_is_left(self):
        sink = _Sink()
        batcher = MessageBatcher(sink, interval=3600).start()
        batcher.add('last words')
        batcher.stop()
        self.assertEqual(sink.messages, ['last words'])

    def test_start_is_idempotent(self):
        batcher = MessageBatcher(_Sink(), interval=3600)
        self.addCleanup(batcher.stop)
        first = batcher.start()._thread
        self.assertIs(batcher.start()._thread, first)


if __name__ == '__main__':
    unittest.main()
