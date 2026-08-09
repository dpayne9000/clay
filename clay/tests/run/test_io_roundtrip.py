"""Input round-trip — the prompt/answer path the refactor must not break.

SocketIO sends input.request and blocks; the daemon side answers with
input.response; prompt() returns the text. Asserted against the events
constants, proving the vocabulary matches what is actually on the wire.

QueueIO is the same contract for an embedded/test in-process run, where the
request goes on the event bus instead of down a socket. Tested here rather than
beside the UI because it holds no Qt — it is a channel, not a widget.
"""

import json
import socket
import threading
import time
import unittest

from ...run import events
from ...run import logger
from ...run.io import ChannelClosed, QueueIO, SocketIO


class SocketRoundTripTest(unittest.TestCase):

    def setUp(self):
        self.workflow_end, self.daemon_end = socket.socketpair()
        self.channel = SocketIO(self.workflow_end)

    def tearDown(self):
        self.channel.close()
        for sock in (self.workflow_end, self.daemon_end):
            try:
                sock.close()
            except OSError:
                pass

    def _read_line(self):
        buf = b''
        while not buf.endswith(b'\n'):
            chunk = self.daemon_end.recv(4096)
            if not chunk:
                break
            buf += chunk
        return json.loads(buf.decode())

    def test_prompt_round_trip(self):
        answers = {}

        def ask():
            answers['value'] = self.channel.prompt('q1', 'Which branch?')

        asker = threading.Thread(target=ask, daemon=True)
        asker.start()

        request = self._read_line()
        self.assertEqual(request['type'], events.INPUT_REQUEST)
        self.assertEqual(request['id'], 'q1')
        self.assertEqual(request['prompt'], 'Which branch?')

        response = json.dumps({'type': events.INPUT_RESPONSE,
                               'id': 'q1', 'text': 'main'}) + '\n'
        self.daemon_end.sendall(response.encode())

        asker.join(timeout=5)
        self.assertFalse(asker.is_alive(), 'prompt() never returned')
        self.assertEqual(answers['value'], 'main')

    def test_channel_close_releases_a_waiting_prompt(self):
        errors = {}

        def ask():
            try:
                self.channel.prompt('q1', 'Anyone there?')
            except ChannelClosed as exc:
                errors['raised'] = exc

        asker = threading.Thread(target=ask, daemon=True)
        asker.start()
        self._read_line()  # wait until the request is on the wire

        self.channel.close()
        asker.join(timeout=5)
        self.assertFalse(asker.is_alive())
        self.assertIn('raised', errors)


class QueueRoundTripTest(unittest.TestCase):
    """The in-process channel: bus for the question, queue for the answer."""

    def setUp(self):
        self.channel = QueueIO()
        self.seen: list[dict] = []
        self._listener = self.seen.append
        logger.add_listener(self._listener)
        self.addCleanup(logger.remove_listener, self._listener)
        self.addCleanup(self.channel.close)

    def _ask(self, prompt_id, text, into):
        def run():
            try:
                into['value'] = self.channel.prompt(prompt_id, text)
            except ChannelClosed as exc:
                into['raised'] = exc

        asker = threading.Thread(target=run, daemon=True)
        asker.start()
        for _ in range(500):
            if self.seen:
                break
            time.sleep(0.005)
        return asker

    def test_the_question_goes_out_on_the_event_bus(self):
        # Not down a private signal: the log file and every attached renderer
        # are listeners, and a question only the widget hears is not recorded.
        result = {}
        asker = self._ask('q1', 'Which branch?', result)

        requests = [e for e in self.seen if e.get('type') == events.INPUT_REQUEST]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['id'], 'q1')
        self.assertEqual(requests[0]['prompt'], 'Which branch?')

        self.channel.deliver('q1', 'main')
        asker.join(timeout=5)
        self.assertEqual(result.get('value'), 'main')

    def test_an_empty_answer_is_an_answer(self):
        # humanDecision reads a blank line as "take the default", so the panel
        # must be able to send one and the channel must not treat it as nothing.
        result = {}
        asker = self._ask('q1', 'Continue?', result)

        self.assertTrue(self.channel.deliver('q1', ''))
        asker.join(timeout=5)
        self.assertFalse(asker.is_alive(), 'prompt() never returned')
        self.assertEqual(result.get('value'), '')

    def test_an_answer_with_no_question_is_refused(self):
        self.assertFalse(self.channel.deliver('q1', 'main'))

    def test_close_releases_a_waiting_prompt(self):
        # What Stop depends on: a run parked in humanDecision has no next
        # action to unwind at, so cancellation has to come through here.
        result = {}
        asker = self._ask('q1', 'Anyone there?', result)

        self.channel.close()
        asker.join(timeout=5)
        self.assertFalse(asker.is_alive())
        self.assertIsInstance(result.get('raised'), ChannelClosed)

    def test_a_second_question_while_one_waits_is_a_programming_error(self):
        result = {}
        self._ask('q1', 'First?', result)
        with self.assertRaises(RuntimeError):
            self.channel.prompt('q2', 'Second?')


if __name__ == '__main__':
    unittest.main()
