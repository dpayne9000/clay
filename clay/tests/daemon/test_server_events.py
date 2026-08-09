"""_handle_engine_event — status fields and broadcast wrapping.

The handler is exercised directly with a stub daemon and workflow object, so
no sockets or subprocesses are involved.
"""

import unittest
from types import SimpleNamespace

from ...daemon.server import ClayDaemon
from ...run import events


class _StubDaemon:
    """Only what _handle_engine_event touches."""

    def __init__(self):
        self.broadcasts = []

    def _broadcast_event(self, event, subscriber_filter=None):
        self.broadcasts.append(event)


def _wf():
    return SimpleNamespace(
        wf_id='wf-0001', status='starting', events_received=0,
        current_step='', current_action='', iterations=0,
        pending_prompt='', pending_prompt_id='',
    )


def _handle(daemon, wf, event):
    ClayDaemon._handle_engine_event(daemon, wf, event)


class EngineEventTest(unittest.TestCase):

    def test_action_start_records_the_action_type(self):
        """current_action shows python:myid — not the event name."""
        daemon, wf = _StubDaemon(), _wf()
        _handle(daemon, wf, {'type': events.ACTION_START,
                             'action_type': 'python', 'id': 'myid'})
        self.assertEqual(wf.current_action, 'python:myid')

    def test_action_complete_clears_current_action(self):
        daemon, wf = _StubDaemon(), _wf()
        wf.current_action = 'python:myid'
        _handle(daemon, wf, {'type': events.ACTION_DONE,
                             'action_type': 'python', 'id': 'myid'})
        self.assertEqual(wf.current_action, '')

    def test_step_start_sets_step_and_running(self):
        daemon, wf = _StubDaemon(), _wf()
        _handle(daemon, wf, {'type': events.STEP_START, 'step': 'think'})
        self.assertEqual(wf.current_step, 'think')
        self.assertEqual(wf.status, 'running')

    def test_engine_events_are_broadcast_wrapped_as_workflow(self):
        daemon, wf = _StubDaemon(), _wf()
        event = {'type': events.ACTION_DONE, 'action_type': 'scramda2',
                 'id': 'plan', 'data': 'answer'}
        _handle(daemon, wf, event)
        self.assertEqual(daemon.broadcasts, [
            {'event': 'workflow', 'id': 'wf-0001', 'data': event}])

    def test_input_request_becomes_a_prompt_broadcast(self):
        daemon, wf = _StubDaemon(), _wf()
        _handle(daemon, wf, {'type': events.INPUT_REQUEST,
                             'id': 'q1', 'prompt': 'Which branch?'})
        self.assertEqual(wf.pending_prompt_id, 'q1')
        self.assertEqual(daemon.broadcasts, [
            {'event': 'prompt', 'id': 'wf-0001',
             'prompt_id': 'q1', 'text': 'Which branch?'}])


if __name__ == '__main__':
    unittest.main()
