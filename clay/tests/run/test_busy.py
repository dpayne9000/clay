"""The busy indicator — the one event `"visible": false` does not silence.

A hidden action emits nothing else a front-end can see, so before this event
existed every surface simply went quiet for however long it took. These tests
assert the signal, not the drawing: the spinner is covered in
test_terminal_renderer.py.
"""

import threading
import time
import unittest
from unittest.mock import patch

from ...run import dispatcher, engine, events, io, logger
from ...run.failure import WorkflowFailure
from ...run.renderers.detail import busy_label


class _Listen:
    """Collects bus events; use as a context manager."""

    def __init__(self):
        self.events = []

    def __enter__(self):
        logger.add_listener(self.events.append)
        return self

    def __exit__(self, *exc):
        logger.remove_listener(self.events.append)
        return False

    def busy(self):
        return [e for e in self.events if e['type'] == events.BUSY]

    def actives(self):
        return [bool(e['active']) for e in self.busy()]


def _wf(action_sets, steps=None):
    return {
        "workflow": {"steps": steps or list(action_sets.keys())},
        "actionSets": action_sets,
    }


class EmissionTest(unittest.TestCase):

    def test_an_action_is_bracketed_by_busy(self):
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, label="busy", auto=True)
        self.assertEqual(bus.actives(), [True, False])

    def test_a_hidden_action_still_raises_busy(self):
        """The bug this event exists for.

        Everything else about a hidden action is suppressed, so a front-end had
        nothing at all to hang an indicator on and sat silent for the whole
        call.
        """
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1",
                          "visible": False}]})
        with _Listen() as bus:
            engine.run_from_data(wf, label="busy", auto=True)

        drawn = [e['type'] for e in bus.events
                 if e['type'] in (events.ACTION_START, events.ACTION_DONE)]
        self.assertEqual(drawn, [], 'hidden action leaked a lifecycle event')
        self.assertEqual(bus.actives(), [True, False])

    def test_busy_carries_the_action_type(self):
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, label="busy", auto=True)
        self.assertEqual(bus.busy()[0]['action_type'], 'python')

    def test_busy_is_dropped_when_a_handler_raises(self):
        """Otherwise three front-ends claim to be working after a crash."""
        def boom(action, ctx):
            raise RuntimeError('handler exploded')

        with _Listen() as bus:
            with patch.object(dispatcher, '_handler_for_type',
                              return_value=boom):
                with self.assertRaises(RuntimeError):
                    dispatcher.dispatch(
                        {'id': 'v', 'type': 'python', 'code': '1'}, {})
        self.assertEqual(bus.actives(), [True, False])

    def test_busy_is_dropped_for_an_unknown_action_type(self):
        """Known dispatch failure still drops the indicator in finally."""
        with _Listen() as bus:
            with self.assertRaises(WorkflowFailure):
                dispatcher.dispatch({'id': 'v', 'type': 'nosuchtype'}, {})
        self.assertEqual(bus.actives(), [True, False])

    #: Enough of each type to pass schema validation, which runs before the
    #: indicator is raised — an action rejected by the schema would prove
    #: nothing about the exclusion list.
    _VALID = {
        'workflow': {'file': 'sub.json'},
        'loop': {'file': 'sub.json'},
        'humanDecision': {'prompt': 'go?'},
        'humanShell': {'command': 'ls'},
    }

    def test_containers_and_human_prompts_raise_no_busy(self):
        self.assertEqual(set(self._VALID), dispatcher._NO_BUSY_TYPES,
                         'the exclusion list changed — fix _VALID with it')
        for action_type, fields in sorted(self._VALID.items()):
            with self.subTest(action_type=action_type):
                action = {'id': 'v', 'type': action_type, **fields}
                with _Listen() as bus:
                    with patch.object(dispatcher, '_handler_for_type',
                                      return_value=lambda *a, **k: None):
                        dispatcher.dispatch(action, {})
                self.assertEqual(bus.busy(), [])
                self.assertIn(events.ACTION_START,
                              [e['type'] for e in bus.events],
                              'the action never ran — check the schema fields')


class PreviewTest(unittest.TestCase):
    """The resolved prompt, which only exists inside the handler."""

    def test_a_resolved_prompt_relabels_the_indicator(self):
        with _Listen() as bus:
            logger.output({'id': 'ask', 'type': 'scramda2'}, 'prompt',
                          'deepseek-r1', 'summarise the workspace')
        self.assertEqual(bus.busy()[0]['preview'], 'summarise the workspace')
        self.assertTrue(bus.busy()[0]['active'])

    def test_a_hidden_prompt_still_previews(self):
        """Deliberate: one truncated line saying what the wait is for.

        The prompt itself stays off the bus — action.output is gated — and the
        whole of it stays in the run log.
        """
        action = {'id': 'ask', 'type': 'scramda2', 'visible': False}
        with _Listen() as bus:
            logger.output(action, 'prompt', 'deepseek-r1', 'a hidden question')

        self.assertEqual([e['type'] for e in bus.events], [events.BUSY])
        self.assertEqual(bus.busy()[0]['preview'], 'a hidden question')

    def test_only_a_prompt_payload_relabels(self):
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'applyFileWrites'}, 'file',
                          'a.py written', 'print(1)')
        self.assertEqual(bus.busy(), [])

    def test_preview_is_capped(self):
        with _Listen() as bus:
            logger.busy(True, 'scramda2', 'x' * 500)
        self.assertEqual(len(bus.busy()[0]['preview']),
                         logger.BUSY_PREVIEW_MAX_CHARS)

    def test_preview_is_one_line(self):
        """A spinner label that contains a newline breaks its own redraw."""
        with _Listen() as bus:
            logger.busy(True, 'scramda2', 'read this\n\nand   that\n')
        self.assertEqual(bus.busy()[0]['preview'], 'read this and that')


class LogFileTest(unittest.TestCase):

    def test_busy_never_reaches_the_log_file(self):
        """A spinner is not a thing that happened."""
        recorded = []

        class _Log:
            def log_event(self, event):
                recorded.append(event)

            def log(self, line):
                recorded.append(line)

        with patch.object(logger, '_active', _Log()):
            logger.busy(True, 'python')
            logger.busy(False)
        self.assertEqual(recorded, [])


class FloorToHumanTest(unittest.TestCase):
    """Every channel drops the indicator before a question goes out."""

    def test_terminal_prompt_drops_busy_before_reading(self):
        with _Listen() as bus:
            with patch('builtins.input', return_value='yes'):
                answer = io.TerminalIO().prompt('q', 'ready?')
        self.assertEqual(answer, 'yes')
        self.assertEqual(bus.actives(), [False])

    def test_queue_prompt_drops_busy_before_asking(self):
        channel = io.QueueIO()
        with _Listen() as bus:
            threading.Timer(0.05, lambda: channel.deliver('q', 'yes')).start()
            channel.prompt('q', 'ready?')

        self.assertEqual(bus.actives(), [False])
        # And it happens before the question, not after: a Qt panel that showed
        # "working" beside a live input row would be lying about both.
        order = [e['type'] for e in bus.events]
        self.assertLess(order.index(events.BUSY),
                        order.index(events.INPUT_REQUEST))

    def test_a_closed_channel_still_drops_busy(self):
        """The indicator must not survive the run that raised it."""
        channel = io.QueueIO()
        channel.close()
        with _Listen() as bus:
            with self.assertRaises(io.ChannelClosed):
                channel.prompt('q', 'ready?')
        self.assertEqual(bus.actives(), [False])


class BusyLabelTest(unittest.TestCase):

    def test_preview_wins(self):
        self.assertEqual(
            busy_label({'action_type': 'scramda2', 'preview': 'summarise'}),
            'summarise')

    def test_action_type_when_no_preview_yet(self):
        """What the dispatcher's busy carries — it runs before the handler."""
        self.assertEqual(busy_label({'action_type': 'scramda2', 'preview': ''}),
                         'scramda2')

    def test_a_bare_word_when_there_is_nothing(self):
        self.assertEqual(busy_label({}), 'working')

    def test_limit_cuts_and_marks(self):
        self.assertEqual(busy_label({'preview': 'abcdefghij'}, 4), 'abcd…')

    def test_limit_zero_leaves_it_whole(self):
        self.assertEqual(busy_label({'preview': 'abcdefghij'}, 0), 'abcdefghij')


class TypingKeepaliveTest(unittest.TestCase):
    """Telegram clears its hint after ~5s, so a long wait has to re-send."""

    def setUp(self):
        from ...actions.agent.telegram_actions import Typing
        self.Typing = Typing

    def test_it_types_immediately_and_repeats(self):
        sent = []
        typing = self.Typing(sent.append, interval=0.02)
        typing.start(42)
        try:
            deadline = time.monotonic() + 2.0
            while len(sent) < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            typing.stop()
        self.assertGreaterEqual(len(sent), 3)
        self.assertEqual(set(sent), {42})

    def test_stop_joins_the_thread(self):
        typing = self.Typing(lambda chat_id: None, interval=0.02)
        typing.start(42)
        typing.stop()
        self.assertIsNone(typing._thread)

    def test_stop_is_idempotent(self):
        typing = self.Typing(lambda chat_id: None, interval=0.02)
        typing.stop()
        typing.stop()

    def test_restart_does_not_leave_the_first_thread_running(self):
        sent = []
        typing = self.Typing(sent.append, interval=0.02)
        typing.start(1)
        typing.start(2)
        try:
            time.sleep(0.1)
            self.assertNotIn(1, sent[-2:], 'the first keepalive is still going')
        finally:
            typing.stop()

    def test_a_send_failure_ends_the_keepalive_quietly(self):
        """One failed hint is not worth taking a bot thread down."""
        calls = []

        def explode(chat_id):
            calls.append(chat_id)
            raise RuntimeError('telegram said no')

        typing = self.Typing(explode, interval=0.02)
        typing.start(42)
        time.sleep(0.1)
        typing.stop()
        self.assertEqual(calls, [42])

    def test_it_gives_up_after_max_seconds(self):
        """A run whose socket drops never sends its own active=False."""
        sent = []
        typing = self.Typing(sent.append, interval=0.01, max_seconds=0.03)
        typing.start(42)
        time.sleep(0.2)
        self.assertIsNotNone(typing._thread)
        self.assertFalse(typing._thread.is_alive())
        self.assertLess(len(sent), 10)
        typing.stop()


if __name__ == '__main__':
    unittest.main()
