"""`"when": "key"` — an action that runs only when an earlier output says yes.

Asserted on the bus and on the accumulated step_output, not on stdout: the
question is whether the action *ran*, which is a dispatch fact. The one line
each front-end draws for it is covered in test_terminal_renderer.py.
"""

import unittest
from unittest.mock import patch

from ...lib.flags import FALSY_WORDS, is_truthy
from ...run import engine, events, io, logger
from ...run.dispatcher import should_run
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


# `shell` with `echo` is the one action that stores a value this test chooses.
# `python` cannot: its exec() strips __builtins__, so print is undefined and it
# can only ever store an empty string.
def _says(action_id, word, **extra):
    return {"id": action_id, "type": "shell", "command": f"echo {word}", **extra}


def _gated(verdict):
    """A workflow whose second action is gated on the first action's value."""
    return _wf({"go": [
        _says("verdict", verdict),
        _says("gated", "ran", when="verdict"),
    ]})


class VocabularyTest(unittest.TestCase):
    """The gate and the loop read "yes" the same way, from one list."""

    def test_every_falsy_word_means_no(self):
        for word in FALSY_WORDS:
            with self.subTest(word=word):
                self.assertFalse(is_truthy(word))

    def test_case_and_surrounding_space_do_not_change_the_answer(self):
        for value in ('NO', ' no ', 'No\n', 'DONE', '  Stop'):
            with self.subTest(value=value):
                self.assertFalse(is_truthy(value))

    def test_a_word_it_does_not_recognise_means_yes(self):
        # Not a general truthy test. The only safe reading of an unrecognised
        # answer is "not one of the ways of saying no".
        for value in ('YES', 'yes', 'maybe', 'ok', '1', 'files were written'):
            with self.subTest(value=value):
                self.assertTrue(is_truthy(value))

    def test_a_real_bool_answers_for_itself(self):
        # A JSON false must not arrive as the truthy string "False".
        self.assertFalse(is_truthy(False))
        self.assertTrue(is_truthy(True))

    def test_none_is_no(self):
        self.assertFalse(is_truthy(None))


class ShouldRunTest(unittest.TestCase):

    def test_no_when_field_runs(self):
        run, key, value = should_run({'id': 'a', 'type': 'python'}, {})
        self.assertTrue(run)
        self.assertEqual((key, value), ('', ''))

    def test_an_open_gate_reports_no_reason(self):
        # The key and value exist to explain a *skip*. Nothing to explain here.
        self.assertEqual(should_run({'when': 'files_written'},
                                    {'files_written': 'greet.py'}),
                         (True, '', ''))

    def test_a_closed_gate_reports_the_key_and_value_that_closed_it(self):
        run, key, value = should_run({'when': 'files_written'},
                                     {'files_written': ''})
        self.assertFalse(run)
        self.assertEqual((key, value), ('files_written', ''))

    def test_whenNot_is_the_mirror(self):
        action = {'whenNot': 'files_written'}
        self.assertTrue(should_run(action, {'files_written': ''})[0])
        self.assertFalse(should_run(action, {'files_written': 'greet.py'})[0])

    def test_whenNot_names_itself_in_the_reason(self):
        _, key, value = should_run({'whenNot': 'files_written'},
                                   {'files_written': 'greet.py'})
        self.assertEqual((key, value), ('not files_written', 'greet.py'))

    def test_both_fields_together_mean_both_must_hold(self):
        action = {'when': 'wrote', 'whenNot': 'failed'}
        self.assertTrue(should_run(action, {'wrote': 'a.py', 'failed': ''})[0])
        self.assertFalse(should_run(action, {'wrote': '', 'failed': ''})[0])
        self.assertFalse(should_run(action, {'wrote': 'a.py', 'failed': 'boom'})[0])

    def test_it_reads_step_output_not_includedData(self):
        # A gate is not data the action consumes. Requiring the key in
        # includedData would mean pouring a value into a prompt purely to be
        # allowed to test it.
        action = {'when': 'verdict', 'includedData': ['something_else']}
        run, _, _ = should_run(action, {'verdict': 'YES'})
        self.assertTrue(run)

    def test_a_key_no_action_produced_skips_and_warns(self):
        with _Listen() as bus:
            run, key, _ = should_run({'id': 'x', 'when': 'typo'}, {})

        self.assertFalse(run)
        self.assertEqual(key, 'typo')
        warnings = [e for e in bus.events if e['type'] == events.LOG
                    and str(e.get('level', '')).upper() == 'WARN']
        self.assertTrue(warnings, 'a when on a key nothing produces must say so')
        self.assertIn('typo', warnings[0]['message'])


class _ApprovingIO:
    """Answers every prompt 'y'. `_says()` always builds a `shell` action —
    the one action type in this file that stores a value — and `shell`
    reaches approval.confirm() (required=True, 573aee4) for any whitelisted
    command, gated or not."""

    def prompt(self, prompt_id, text):
        return 'y'


class DispatchTest(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_an_open_gate_runs_the_action_normally(self):
        with _Listen() as bus:
            out = engine.run_from_data(_gated('YES'), label='open', auto=True)

        self.assertEqual(str(out.get('gated')).strip(), 'ran')
        self.assertNotIn(events.ACTION_SKIPPED, bus.types())

    def test_a_closed_gate_emits_skipped_and_no_lifecycle(self):
        with _Listen() as bus:
            out = engine.run_from_data(_gated('NO'), label='closed', auto=True)

        self.assertNotIn('gated', out)

        # One start/complete pair for the ungated action, and none for the
        # gated one — a skipped action must not emit a start line, or the
        # terminal holds a spinner open on a call that never happens.
        starts = [e for e in bus.events if e['type'] == events.ACTION_START]
        self.assertEqual([e['id'] for e in starts], ['verdict'])

        skipped = bus.first(events.ACTION_SKIPPED)
        self.assertEqual(skipped['id'], 'gated')
        self.assertEqual(skipped['key'], 'verdict')
        self.assertEqual(skipped['value'].strip(), 'NO')

    def test_a_skipped_action_stores_nothing(self):
        out = engine.run_from_data(_gated('no'), label='store', auto=True)
        self.assertNotIn('gated', out)

    def test_output_key_stores_the_same_result_under_a_second_key(self):
        wf = _wf({"go": [
            _says("primary", "value", outputKey="secondary"),
        ]})
        out = engine.run_from_data(wf, label='output-key', auto=True)

        self.assertEqual(out['primary'], out['secondary'])

    def test_a_skipped_action_clears_a_stale_value_under_its_id(self):
        # The loop case: the same actions run again each iteration, so an
        # action skipped on pass 2 must not leave pass 1's answer standing for
        # a later `when` to gate on.
        wf = _wf({"go": [
            _says("gated", "stale"),
            _says("verdict", "no"),
            _says("gated", "fresh", when="verdict"),
        ]})
        out = engine.run_from_data(wf, label='stale', auto=True)
        self.assertNotIn('gated', out)

    def test_a_skipped_action_clears_a_stale_output_key(self):
        wf = _wf({"go": [
            _says("first", "stale", outputKey="secondary"),
            _says("verdict", "no"),
            _says("replacement", "fresh", outputKey="secondary",
                  when="verdict"),
        ]})
        out = engine.run_from_data(wf, label='stale-output-key', auto=True)

        self.assertNotIn('secondary', out)

    def test_a_gated_action_is_still_validated(self):
        # Finding a typo only on the turn the gate happens to open is how a
        # workflow breaks in front of a user weeks later.
        wf = _wf({"go": [
            _says("verdict", "no"),
            # No `command`, which is required — the gate must not hide that.
            {"id": "broken", "type": "shell", "when": "verdict"},
        ]})
        with _Listen() as bus:
            with self.assertRaises(WorkflowFailure):
                engine.run_from_data(wf, label='validate', auto=True)

        self.assertIn(events.ACTION_ERROR, bus.types())
        self.assertIn(events.RUN_ERROR, bus.types())
        self.assertNotIn(events.ACTION_SKIPPED, bus.types())
        self.assertNotIn(events.RUN_COMPLETE, bus.types())

    def test_visible_false_silences_the_skip_line_too(self):
        wf = _wf({"go": [
            _says("verdict", "no"),
            _says("gated", "ran", when="verdict", visible=False),
        ]})
        with _Listen() as bus:
            engine.run_from_data(wf, label='hidden', auto=True)

        self.assertNotIn(events.ACTION_SKIPPED, bus.types())


if __name__ == '__main__':
    unittest.main()
