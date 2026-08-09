"""Integration tests for the workflow input channel (clay/run/io.py).

Replaces the former WEB_MODE marker tests. A workflow now asks humans
questions through one channel that picks its transport from the launch mode:

    no events socket attached  → TerminalIO, builtins.input
    events socket attached     → SocketIO, input.request / input.response

These tests drive the real SocketIO over a socket.socketpair(), standing in
for clayd on the far end, and check that humanDecision routes through
whichever channel is active.
"""

import json
import socket
import threading
import unittest
from unittest.mock import patch

from clay.actions import scramda2_actions
from clay.actions.human_decision import handler
from clay.run import io


class _FakeRelay:
    """The clayd end of a workflow's event socket."""

    def __init__(self, sock):
        self._sock = sock
        self._buf = b''

    def next_request(self, timeout=2.0):
        """Block until an input.request line arrives; return it decoded."""
        self._sock.settimeout(timeout)
        while b'\n' not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise AssertionError('relay closed before a request arrived')
            self._buf += chunk
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line)

    def respond(self, prompt_id, text):
        payload = json.dumps({
            'type': 'input.response', 'id': prompt_id, 'text': text,
        }) + '\n'
        self._sock.sendall(payload.encode('utf-8'))

    def answer_next(self, text, transform=None):
        """Answer the next request in a background thread. Returns the thread."""
        seen = {}

        def pump():
            request = self.next_request()
            seen.update(request)
            prompt_id = request.get('id', '')
            self.respond(prompt_id, transform(request) if transform else text)

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        return thread, seen


class SocketChannelTest(unittest.TestCase):

    def setUp(self):
        self.workflow_sock, self.relay_sock = socket.socketpair()
        self.relay = _FakeRelay(self.relay_sock)
        self.channel = io.attach_socket(self.workflow_sock)
        self.addCleanup(self._teardown)

    def _teardown(self):
        io.detach()
        for sock in (self.workflow_sock, self.relay_sock):
            try:
                sock.close()
            except OSError:
                pass

    # ── channel selection ────────────────────────────────────────────────

    def test_socket_channel_active_while_attached(self):
        self.assertIsInstance(io.get(), io.SocketIO)

    def test_detach_returns_to_terminal(self):
        io.detach()
        self.assertIsInstance(io.get(), io.TerminalIO)

    # ── request / response ───────────────────────────────────────────────

    def test_prompt_sends_input_request_and_returns_response(self):
        thread, seen = self.relay.answer_next('42')
        answer = io.get().prompt('retries', 'How many retries?')
        thread.join(timeout=2)

        self.assertEqual(answer, '42')
        self.assertEqual(seen['type'], 'input.request')
        self.assertEqual(seen['id'], 'retries')
        self.assertEqual(seen['prompt'], 'How many retries?')

    def test_response_with_mismatched_id_still_delivered(self):
        """Only one prompt is outstanding, so an id drift is not ambiguous."""
        def pump():
            self.relay.next_request()
            self.relay.respond('some-other-id', 'delivered')

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        answer = io.get().prompt('q1', 'Question?')
        thread.join(timeout=2)
        self.assertEqual(answer, 'delivered')

    def test_empty_response_returns_empty_string(self):
        thread, _ = self.relay.answer_next('')
        answer = io.get().prompt('x', 'Q?')
        thread.join(timeout=2)
        self.assertEqual(answer, '')

    def test_unrelated_events_are_ignored(self):
        def pump():
            self.relay.next_request()
            self.relay_sock.sendall(b'{"type":"step.start","step":"one"}\n')
            self.relay_sock.sendall(b'not json at all\n')
            self.relay.respond('x', 'real answer')

        thread = threading.Thread(target=pump, daemon=True)
        thread.start()
        answer = io.get().prompt('x', 'Q?')
        thread.join(timeout=2)
        self.assertEqual(answer, 'real answer')

    def test_closed_channel_raises_instead_of_hanging(self):
        def drop():
            self.relay.next_request()
            self.relay_sock.close()

        thread = threading.Thread(target=drop, daemon=True)
        thread.start()
        with self.assertRaises(io.ChannelClosed):
            io.get().prompt('x', 'never answered')
        thread.join(timeout=2)

    def test_duplicate_prompt_id_is_rejected(self):
        started = threading.Event()

        def first():
            started.set()
            try:
                io.get().prompt('dup', 'first')
            except io.ChannelClosed:
                pass

        thread = threading.Thread(target=first, daemon=True)
        thread.start()
        started.wait(timeout=2)
        self.relay.next_request()

        with self.assertRaises(RuntimeError):
            io.get().prompt('dup', 'second')

        io.detach()
        thread.join(timeout=2)


class HumanDecisionRoutingTest(unittest.TestCase):
    """humanDecision must use whichever channel is active, with no env var."""

    def setUp(self):
        self.workflow_sock, self.relay_sock = socket.socketpair()
        self.relay = _FakeRelay(self.relay_sock)
        io.attach_socket(self.workflow_sock)
        self.addCleanup(self._teardown)

    def _teardown(self):
        io.detach()
        for sock in (self.workflow_sock, self.relay_sock):
            try:
                sock.close()
            except OSError:
                pass

    def test_prompt_carries_action_id_and_resolved_text(self):
        thread, seen = self.relay.answer_next('Paris')
        result = handler({'id': 'city', 'prompt': 'Enter city for {purpose}'},
                         {'purpose': 'demo'})
        thread.join(timeout=2)

        self.assertEqual(seen['id'], 'city')
        self.assertEqual(seen['prompt'], 'Enter city for demo')
        self.assertEqual(result, {'id': 'city', 'data': 'Paris'})

    def test_missing_placeholder_is_preserved(self):
        thread, seen = self.relay.answer_next('ok')
        handler({'id': 'out', 'prompt': 'Topic: {topic}, Type: {doc_type}'},
                {'topic': 'AI'})
        thread.join(timeout=2)

        self.assertIn('Topic: AI', seen['prompt'])
        self.assertIn('{doc_type}', seen['prompt'])

    def test_auto_mode_never_prompts(self):
        # Auto mode dispatches a real scramda2 action, so the model is mocked
        # at the connector rather than at a helper inside human_decision.
        with patch.object(scramda2_actions.gopher, 'fire',
                          return_value='auto-ans') as model:
            result = handler({'id': 'x', 'prompt': 'Q?'}, {}, auto=True)

        model.assert_called_once()
        self.assertEqual(result['data'], 'auto-ans')
        self.relay_sock.settimeout(0.2)
        with self.assertRaises((socket.timeout, BlockingIOError, OSError)):
            self.relay_sock.recv(4096)

    def test_empty_prompt_returns_none_without_asking(self):
        self.assertIsNone(handler({'id': 'x', 'prompt': ''}, {}))


class TerminalChannelTest(unittest.TestCase):

    def test_terminal_channel_uses_builtin_input(self):
        io.detach()
        with patch('builtins.input', return_value='typed') as mock_input:
            result = handler({'id': 'x', 'prompt': 'Q?'}, {})
        mock_input.assert_called_once()
        self.assertEqual(result['data'], 'typed')


if __name__ == '__main__':
    unittest.main()
