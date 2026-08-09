"""`"visible": false` — an action that draws nothing, and still logs everything.

The flag is read in one place (logger.visible) and applied in two: dispatcher
gates action.start / action.complete, logger.output gates payloads. Both go
through logger.emit's `show`, so the log file keeps the whole run either way.
"""

import unittest

from ...run import engine, events, logger
from ...run.failure import WorkflowFailure


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

    def types(self):
        return [e['type'] for e in self.events]


class _Recorder:
    """Stands in for the RunLogger, so log-file writes can be asserted on."""

    def __init__(self):
        self.events = []
        self.lines = []

    def log_event(self, event):
        self.events.append(event)

    def log(self, line):
        self.lines.append(line)


def _wf(action_sets, steps=None):
    return {
        "workflow": {"steps": steps or list(action_sets.keys())},
        "actionSets": action_sets,
    }


class VisiblePredicateTest(unittest.TestCase):
    """Absent means visible; strings are parsed rather than trusted to bool()."""

    def test_absent_is_visible(self):
        self.assertTrue(logger.visible({'id': 'a', 'type': 'python'}))

    def test_true_is_visible(self):
        self.assertTrue(logger.visible({'visible': True}))

    def test_false_is_hidden(self):
        self.assertFalse(logger.visible({'visible': False}))

    def test_the_string_false_is_hidden(self):
        # A non-empty string is truthy, so bool() alone would silently ignore
        # exactly the value a person hand-writing json is most likely to type.
        for text in ('false', 'False', 'FALSE', ' false ', 'no', 'off', '0', ''):
            with self.subTest(text=text):
                self.assertFalse(logger.visible({'visible': text}))

    def test_the_string_true_is_visible(self):
        for text in ('true', 'True', 'yes', 'on', '1'):
            with self.subTest(text=text):
                self.assertTrue(logger.visible({'visible': text}))


class HiddenActionTest(unittest.TestCase):

    def test_a_visible_action_emits_start_and_complete(self):
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, auto=True)

        self.assertIn(events.ACTION_START, bus.types())
        self.assertIn(events.ACTION_DONE, bus.types())

    def test_a_hidden_action_emits_neither(self):
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1",
                          "visible": False}]})
        with _Listen() as bus:
            engine.run_from_data(wf, auto=True)

        # busy is the one thing left, and it exists because of this flag: a
        # hidden action used to emit nothing at all between start and finish,
        # so every front-end went quiet for however long it took. It carries no
        # id and nothing the action did — see logger.busy() and test_busy.py.
        self.assertEqual(bus.types(), [events.RUN_START,
                                       events.STEP_START,
                                       events.BUSY,
                                       events.BUSY,
                                       events.RUN_COMPLETE])

    def test_hiding_one_action_does_not_hide_its_neighbour(self):
        wf = _wf({"go": [
            {"id": "quiet", "type": "python", "code": "1", "visible": False},
            {"id": "loud", "type": "python", "code": "2"},
        ]})
        with _Listen() as bus:
            engine.run_from_data(wf, auto=True)

        started = [e['id'] for e in bus.events
                   if e['type'] == events.ACTION_START]
        self.assertEqual(started, ['loud'])

    def test_a_hidden_action_still_reaches_the_log_file(self):
        # Hiding an action is a decision about a screen. A run debugged after
        # the fact needs the whole record, so `show` gates listeners only.
        recorder = _Recorder()
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1",
                          "visible": False}]})
        original = logger._active
        logger._active = recorder
        try:
            engine.run_from_data(wf, auto=True)
        finally:
            logger._active = original

        logged = [e['type'] for e in recorder.events]
        self.assertIn(events.ACTION_START, logged)
        self.assertIn(events.ACTION_DONE, logged)

    def test_an_error_is_never_hidden(self):
        # An action you chose not to watch is still one you have to be told
        # about when it fails. Schema errors are emitted before the gate.
        wf = _wf({"go": [{"id": "v", "type": "python", "visible": False}]})
        with _Listen() as bus:
            with self.assertRaises(WorkflowFailure):
                engine.run_from_data(wf, auto=True)

        self.assertIn(events.ACTION_ERROR, bus.types())
        self.assertIn(events.RUN_ERROR, bus.types())
        self.assertNotIn(events.RUN_COMPLETE, bus.types())


class HiddenOutputTest(unittest.TestCase):
    """logger.output reads the same flag, so no handler can leak a payload."""

    def test_a_payload_from_a_visible_action_is_emitted(self):
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'writeSkill'},
                          'file', 'a.py written', 'print(1)')

        self.assertEqual(len(bus.events), 1)
        self.assertEqual(bus.events[0]['kind'], 'file')
        self.assertEqual(bus.events[0]['text'], 'print(1)')

    def test_a_payload_from_a_hidden_action_is_not(self):
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'writeSkill', 'visible': False},
                          'file', 'a.py written', 'print(1)')

        self.assertEqual(bus.events, [])

    def test_the_payload_carries_its_provenance(self):
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'writeSkill'}, 'file', 'a.py', '')

        event = bus.events[0]
        self.assertEqual(event['id'], 'w')
        self.assertEqual(event['action_type'], 'writeSkill')


class OutputCapTest(unittest.TestCase):
    """One cap for every payload, instead of a copy per action module."""

    def setUp(self):
        self._original = logger.OUTPUT_MAX_CHARS
        self.addCleanup(setattr, logger, 'OUTPUT_MAX_CHARS', self._original)

    def test_uncapped_by_default(self):
        self.assertEqual(logger.OUTPUT_MAX_CHARS, 0)
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'shell'}, 'command', '$ x', 'y' * 5000)
        self.assertEqual(len(bus.events[0]['text']), 5000)

    def test_a_long_body_is_truncated_and_says_so(self):
        logger.OUTPUT_MAX_CHARS = 10
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'shell'}, 'command', '$ x', 'y' * 5000)

        text = bus.events[0]['text']
        self.assertTrue(text.startswith('y' * 10))
        self.assertIn('truncated', text)

    def test_the_label_is_never_truncated(self):
        # The header is what makes a truncated body legible; capping it would
        # lose the filename the contents belong to.
        logger.OUTPUT_MAX_CHARS = 5
        label = 'a-very-long-path-that-exceeds-the-cap.py written'
        with _Listen() as bus:
            logger.output({'id': 'w', 'type': 'writeFile'}, 'file', label, 'x' * 100)

        self.assertEqual(bus.events[0]['label'], label)


if __name__ == '__main__':
    unittest.main()
