"""The engine emits, and what it emits is the contract.

Asserted through logger.add_listener — no stdout capture anywhere in this
file. The renderer's drawing is covered in test_terminal_renderer.py.
"""

import unittest
from unittest.mock import patch

from ...run import engine, events, logger
from ...run.dispatcher import _action_fields
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

    def first(self, event_type):
        return next(e for e in self.events if e['type'] == event_type)


def _wf(action_sets, steps=None):
    return {
        "workflow": {"steps": steps or list(action_sets.keys())},
        "actionSets": action_sets,
    }


class EmissionSequenceTest(unittest.TestCase):

    def test_run_emits_expected_sequence(self):
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, label="seq-test", auto=True)

        self.assertEqual(bus.types(), [
            events.RUN_START,
            events.STEP_START,
            events.ACTION_START,
            # The busy pair brackets the handler, inside the action's own
            # lifecycle — a front-end raises its indicator after it knows what
            # is starting and drops it before the result arrives.
            events.BUSY,
            events.BUSY,
            events.ACTION_DONE,
            events.RUN_COMPLETE,
        ])

    def test_run_start_carries_label_auto_and_log_path(self):
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, label="fields-test", auto=True)

        start = bus.first(events.RUN_START)
        self.assertEqual(start['label'], 'fields-test')
        self.assertTrue(start['auto'])
        self.assertTrue(start['log_path'])

    def test_action_events_carry_action_type_not_type(self):
        wf = _wf({"go": [{"id": "myid", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, auto=True)

        started = bus.first(events.ACTION_START)
        self.assertEqual(started['action_type'], 'python')
        self.assertEqual(started['id'], 'myid')

        done = bus.first(events.ACTION_DONE)
        self.assertEqual(done['action_type'], 'python')
        self.assertIsInstance(done['duration_ms'], int)
        self.assertGreaterEqual(done['duration_ms'], 0)

    def test_unknown_action_type_emits_action_error(self):
        wf = _wf({"go": [{"id": "x", "type": "noSuchThing"}]})
        with _Listen() as bus:
            with self.assertRaises(WorkflowFailure):
                engine.run_from_data(wf, label='bad-action', auto=True)

        error = bus.first(events.ACTION_ERROR)
        self.assertIn('noSuchThing', error['message'])
        run_error = bus.first(events.RUN_ERROR)
        self.assertIn('noSuchThing', run_error['message'])
        self.assertEqual(run_error['label'], 'bad-action')
        self.assertNotIn(events.RUN_COMPLETE, bus.types())
        self.assertIsNone(logger.get())

    def test_invalid_action_schema_is_a_known_workflow_failure(self):
        wf = _wf({"go": [{"id": "x", "type": "python"}]})
        with _Listen() as bus:
            with self.assertRaises(WorkflowFailure):
                engine.run_from_data(wf, label='bad-schema', auto=True)

        self.assertIn(events.ACTION_ERROR, bus.types())
        self.assertIn(events.RUN_ERROR, bus.types())
        self.assertNotIn(events.RUN_COMPLETE, bus.types())

    def test_run_complete_lands_in_the_log_file(self):
        """run.complete is emitted before logger.stop() — after it, _active
        is None and the event would silently skip the file."""
        wf = _wf({"go": [{"id": "v", "type": "python", "code": "1"}]})
        with _Listen() as bus:
            engine.run_from_data(wf, label="log-order", auto=True)

        log_path = bus.first(events.RUN_START)['log_path']
        with open(log_path) as fh:
            content = fh.read()
        self.assertIn(events.RUN_COMPLETE, content)

    def test_logger_warn_becomes_a_log_event(self):
        with _Listen() as bus:
            logger.warn('careful now')

        event = bus.first(events.LOG)
        self.assertEqual(event['level'], 'WARN')
        self.assertEqual(event['message'], 'careful now')

    def test_logger_debug_stays_off_the_bus(self):
        with _Listen() as bus:
            logger.debug('internal detail')
        self.assertEqual(bus.events, [])


class NotifyRobustnessTest(unittest.TestCase):

    def test_raising_listener_does_not_stop_the_others(self):
        def bad(event):
            raise RuntimeError('broken renderer')

        seen = []
        logger.add_listener(bad)
        logger.add_listener(seen.append)
        try:
            with patch('sys.stderr') as stderr:
                logger.emit('anything', value=1)
        finally:
            logger.remove_listener(bad)
            logger.remove_listener(seen.append)

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['type'], 'anything')
        # The failure is reported, not swallowed.
        written = ' '.join(str(c) for c in stderr.write.call_args_list)
        self.assertIn('failed', written)

    def test_control_flow_listener_exceptions_propagate(self):
        for exception in (KeyboardInterrupt(), SystemExit(2)):
            with self.subTest(exception=type(exception).__name__):
                def stop(_event, error=exception):
                    raise error

                logger.add_listener(stop)
                try:
                    with self.assertRaises(type(exception)):
                        logger.emit('anything')
                finally:
                    logger.remove_listener(stop)


class ActionFieldsTest(unittest.TestCase):

    def test_returns_data_not_formatted_strings(self):
        long_command = 'c' * 200
        fields = _action_fields({'type': 'shell', 'command': long_command})
        # No truncation, no prose — truncation is the renderer's business.
        self.assertEqual(fields['command'], long_command)

    def test_no_action_type_carries_a_prompt(self):
        """This runs before the handler, so action['prompt'] is always the
        unsubstituted template — never the text sent or asked. The resolved
        text arrives on action.output (scramda2) or input.request
        (humanDecision) instead."""
        for action in ({'type': 'scramda2', 'prompt': 'Mission: {mission}',
                        'modelProfile': 'orchestrator'},
                       {'type': 'humanDecision', 'prompt': 'Which {branch}?'}):
            with self.subTest(action_type=action['type']):
                self.assertNotIn('prompt', _action_fields(action))

    def test_scramda2_start_still_carries_its_model(self):
        fields = _action_fields({'type': 'scramda2', 'prompt': 'x',
                                 'modelProfile': 'orchestrator'})
        self.assertEqual(fields['model'], 'orchestrator')

    def test_shell_and_writefile_fields(self):
        self.assertEqual(
            _action_fields({'type': 'shell', 'command': 'ls -la'}),
            {'command': 'ls -la'})
        self.assertEqual(
            _action_fields({'type': 'writeFile', 'file': 'out.txt',
                            'content': 'body'}),
            {'file': 'out.txt', 'content': 'body'})

    def test_included_data_listed(self):
        fields = _action_fields({'type': 'python', 'code': '1',
                                 'includedData': ['a', 'b']})
        self.assertEqual(fields, {'included': ['a', 'b']})


class ResolvedPromptTest(unittest.TestCase):
    """The prompt on the bus is the text the model was sent.

    Before action.output existed, front-ends showed action['prompt'] from
    action.start — emitted before the handler runs, so every {placeholder} was
    still literal and no front-end had ever displayed a real query.
    """

    def _run(self, prompt, data):
        from ...actions import scramda2_actions
        wf = _wf({"go": [{"id": "ask", "type": "scramda2", "prompt": prompt,
                          "includedData": list(data)}]})
        with patch.object(scramda2_actions.gopher, 'fire', return_value='ok'):
            with _Listen() as bus:
                engine.run_from_data(wf, initial_data=data)
        return bus

    def test_the_emitted_prompt_is_the_resolved_one(self):
        bus = self._run('Files:\n{listing}', {'listing': 'greet.py'})
        event = bus.first(events.ACTION_OUTPUT)
        self.assertEqual(event['kind'], 'prompt')
        self.assertEqual(event['text'], 'Files:\ngreet.py')
        self.assertNotIn('{listing}', event['text'])

    def test_the_output_names_the_action_that_emitted_it(self):
        bus = self._run('hi', {})
        event = bus.first(events.ACTION_OUTPUT)
        self.assertEqual(event['id'], 'ask')
        self.assertEqual(event['action_type'], 'scramda2')

    def test_action_start_no_longer_carries_a_prompt(self):
        bus = self._run('Files:\n{listing}', {'listing': 'greet.py'})
        self.assertNotIn('prompt', bus.first(events.ACTION_START))

    def test_the_prompt_precedes_the_answer(self):
        """logger.output relabels the busy indicator from the prompt and the
        dispatcher drops it after the answer, so the order is load-bearing."""
        bus = self._run('hi', {})
        kinds = [e['type'] for e in bus.events
                 if e['type'] in (events.ACTION_OUTPUT, events.ACTION_DONE)]
        self.assertEqual(kinds, [events.ACTION_OUTPUT, events.ACTION_DONE])


class AutoHumanDecisionTest(unittest.TestCase):
    """Open question 2's fix: the auto model call is a real scramda2 dispatch."""

    def test_auto_answer_is_a_scramda2_action_on_the_bus(self):
        from ...actions import scramda2_actions
        wf = _wf({"go": [{"id": "ans", "type": "humanDecision",
                          "prompt": "Approve?"}]})
        with patch.object(scramda2_actions.gopher, 'fire',
                          return_value='model says yes'):
            with _Listen() as bus:
                result = engine.run_from_data(wf, auto=True)

        scramda_done = [e for e in bus.events
                        if e['type'] == events.ACTION_DONE
                        and e['action_type'] == 'scramda2']
        self.assertEqual(len(scramda_done), 1)
        self.assertEqual(scramda_done[0]['data'], 'model says yes')
        self.assertEqual(scramda_done[0]['id'], 'ans')
        self.assertEqual(result['ans'], 'model says yes')

    def test_context_braces_survive_the_nested_dispatch(self):
        """Accumulated context may contain JSON — the brace-escape must keep
        it intact through the scramda2 handler's format_map."""
        from ...actions import scramda2_actions
        blob = '{"key": "value"}'
        wf = _wf({"go": [{"id": "ans", "type": "humanDecision",
                          "prompt": "Approve?", "includedData": ["blob"]}]})
        with patch.object(scramda2_actions.gopher, 'fire',
                          return_value='ok') as fire:
            engine.run_from_data(wf, auto=True, initial_data={'blob': blob})

        sent_prompt = fire.call_args[0][0]
        self.assertIn(blob, sent_prompt)


if __name__ == '__main__':
    unittest.main()
