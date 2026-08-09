"""TerminalRenderer — synthetic event sequences drawn to a captured stdout.

The regression guard for "the terminal still looks the same": these tests
feed the renderer the events a run emits and assert the visible output,
without running an engine at all.
"""

import io
import sys
import unittest
from unittest.mock import patch

from ...lib import config
from ...run import events, termui
from ...run.termui import engine
from ...run.renderers.detail import action_detail as _detail
from ...run.renderers.terminal import TerminalRenderer

_prev_plain = termui.PLAIN


def setUpModule():
    termui.set_plain(True)


def tearDownModule():
    termui.set_plain(_prev_plain)


def _render(sequence):
    """Feed events to a fresh renderer, return captured stdout."""
    renderer = TerminalRenderer()
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        for event in sequence:
            renderer.handle(event)
    finally:
        sys.stdout = old
        renderer._stop_spinner()
    return buf.getvalue(), renderer


class RenderingTest(unittest.TestCase):

    def test_full_run_sequence_reproduces_the_terminal_look(self):
        out, _ = _render([
            {'type': events.RUN_START, 'label': 'wf.json', 'auto': True,
             'log_path': 'logs/x.log'},
            {'type': events.STEP_START, 'step': 'think'},
            {'type': events.ACTION_START, 'action_type': 'python',
             'id': 'calc'},
            {'type': events.ACTION_DONE, 'action_type': 'python',
             'id': 'calc', 'data': '42', 'duration_ms': 3},
            {'type': events.RUN_COMPLETE, 'label': 'wf.json',
             'log_path': 'logs/x.log'},
        ])
        self.assertIn('wf.json', out)
        self.assertIn('[auto]', out)
        self.assertIn('think', out)
        self.assertIn('python', out)
        self.assertIn('→ calc', out)

    def test_scramda2_answer_is_echoed(self):
        out, _ = _render([
            {'type': events.ACTION_START, 'action_type': 'scramda2',
             'id': 'plan', 'model': 'orchestrator'},
            {'type': events.ACTION_DONE, 'action_type': 'scramda2',
             'id': 'plan', 'data': 'hello there', 'duration_ms': 10},
        ])
        self.assertIn('hello there', out)

    def test_non_scramda2_data_is_not_echoed(self):
        out, _ = _render([
            {'type': events.ACTION_START, 'action_type': 'writeFile',
             'id': 'save', 'file': 'x.txt', 'content': 'body'},
            {'type': events.ACTION_DONE, 'action_type': 'writeFile',
             'id': 'save', 'data': 'secret-body', 'duration_ms': 1},
        ])
        self.assertNotIn('secret-body', out)

    def test_log_levels_route_to_the_right_style(self):
        out, _ = _render([
            {'type': events.LOG, 'level': 'INFO', 'message': 'plain note'},
            {'type': events.LOG, 'level': 'ERROR', 'message': 'went wrong'},
        ])
        self.assertIn('plain note', out)
        self.assertIn('went wrong', out)

    def test_errors_are_drawn(self):
        out, _ = _render([
            {'type': events.RUN_ERROR, 'message': 'file missing'},
            {'type': events.ACTION_ERROR, 'action_type': 'shell',
             'id': 'x', 'message': 'boom'},
        ])
        self.assertIn('file missing', out)
        self.assertIn('boom', out)

    def test_loop_iteration_draws_nothing(self):
        out, _ = _render([
            {'type': events.LOOP_ITERATION, 'iteration': 3, 'max': 10},
        ])
        self.assertEqual(out, '')


class PromptBoxTest(unittest.TestCase):
    """The prompt box, drawn directly — it is rich-mode only, and the rest of
    this module runs in plain mode.

    A truncated prompt hides exactly the part you need when a model misreads
    its instructions, so the box is uncapped by default.
    """

    def _draw(self, prompt, theme_overrides=None):
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            engine.scramda_input(prompt, dict(theme_overrides or {}),
                                 True, model='orchestrator')
        finally:
            sys.stdout = old
        return buf.getvalue()

    def test_whole_prompt_is_printed(self):
        prompt = 'p' * 5000
        self.assertIn(prompt, self._draw(prompt))

    def test_line_breaks_are_preserved(self):
        out = self._draw('first line\nsecond line')
        self.assertIn('first line', out)
        self.assertIn('second line', out)
        self.assertNotIn('first line second line', out)

    def test_the_cap_is_not_a_theme_key(self):
        # engine.scramda_input formats what it is handed and holds no opinion
        # on length. The cut is display.promptMaxChars, applied by the
        # renderer — see PromptCapTest below.
        out = self._draw('p' * 500, {'PROMPT_BOX_MAX_CHARS': '10'})
        self.assertIn('p' * 500, out)

    def test_empty_prompt_still_draws_the_box(self):
        self.assertIn('prompt', self._draw(''))

    def test_feature_flag_still_hides_the_box(self):
        out = self._draw('hello', {'FEATURE_SCRAMDA_INPUT_BOX': 'false'})
        self.assertEqual(out, '')


class ResponseErrorBoundaryTest(unittest.TestCase):
    """Response drawing owns no exception policy of its own.

    Ordinary renderer failures are isolated by logger._notify; control-flow
    exceptions must reach that boundary unchanged so it can deliberately let
    them escape. These direct tests prevent a local broad catch returning.
    """

    def test_keyboard_interrupt_is_not_swallowed(self):
        # Header succeeds; interruption occurs inside the response-body loop
        # where the former bare except used to consume it.
        with patch('builtins.print', side_effect=[None, KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                engine.scramda_output('answer', {}, True)

    def test_system_exit_is_not_swallowed(self):
        with patch('builtins.print', side_effect=[None, SystemExit(2)]):
            with self.assertRaises(SystemExit):
                engine.scramda_output('answer', {}, True)


class PromptCapTest(unittest.TestCase):
    """display.promptMaxChars cuts the outgoing prompt, never the answer."""

    def _drawn(self, prompt):
        """The prompt text the renderer hands down to be drawn.

        Asserted at the hand-off, not in captured stdout: the prompt box only
        prints when _rich() is true, which needs a real tty, so under the
        suite scramda_input returns without printing anything. The renderer's
        responsibility is to cut and delegate — drawing is termui's, and
        PromptBoxTest above covers that half by calling engine directly.
        """
        renderer = TerminalRenderer()
        try:
            with patch.object(termui, 'scramda_input') as draw:
                renderer.handle({'type': events.ACTION_OUTPUT, 'id': 'reply',
                                 'kind': 'prompt', 'action_type': 'scramda2',
                                 'label': 'code', 'text': prompt})
        finally:
            renderer._stop_spinner()
        return draw.call_args[0][0]

    def test_a_long_prompt_is_cut_and_says_where_the_rest_is(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=10):
            body = self._drawn('p' * 500)

        self.assertTrue(body.startswith('p' * 10))
        self.assertNotIn('p' * 11, body)
        self.assertIn('490 more characters', body)
        self.assertIn('run log', body)

    def test_a_short_prompt_is_untouched(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=1000):
            body = self._drawn('say hello')

        self.assertEqual(body, 'say hello')

    def test_zero_means_the_whole_prompt(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=0):
            body = self._drawn('p' * 5000)

        self.assertEqual(body, 'p' * 5000)

    def test_the_answer_is_never_cut(self):
        # The cap is on the prompt going out. A truncated answer is the result
        # of the run thrown away, so no setting may shorten it. Asserted on
        # stdout because scramda_output prints in plain mode too.
        with patch.object(config, 'get_prompt_max_chars', return_value=10):
            out, _ = _render([
                {'type': events.ACTION_DONE, 'id': 'reply',
                 'action_type': 'scramda2', 'data': 'a' * 5000},
            ])

        self.assertIn('a' * 5000, out)


class SummaryLineTest(unittest.TestCase):
    """The action line above the box must not repeat a truncated prompt."""

    def test_model_call_summary_shows_the_model_and_no_prompt(self):
        """A scramda2 action.start carries no prompt to repeat — see
        test_event_emission.ActionFieldsTest."""
        out, _ = _render([
            {'type': events.ACTION_START, 'action_type': 'scramda2',
             'id': 'plan', 'model': 'orchestrator'},
        ])
        self.assertNotIn('prompt="', out)
        self.assertIn('orchestrator', out)

    def test_a_question_is_not_repeated_on_the_summary_line(self):
        """TerminalIO prints the question itself and input.request carries it
        to every other front-end, so a copy here would ask it twice."""
        out, _ = _render([
            {'type': events.ACTION_START, 'action_type': 'humanDecision',
             'id': 'ask'},
        ])
        self.assertNotIn('prompt=', out)
        self.assertIn('humanDecision', out)


class ActionOutputTest(unittest.TestCase):
    """Payload events: a prompt draws the box, everything else draws its
    header and body in the indented column, exactly as a logger.info did."""

    def test_file_output_prints_label_and_every_body_line(self):
        out, _ = _render([
            {'type': events.ACTION_OUTPUT, 'action_type': 'applyFileWrites',
             'id': 'files_written', 'kind': 'file',
             'label': 'greet.py written (2 lines)',
             'text': 'def greet():\n    return "hi"'},
        ])
        self.assertIn('  greet.py written (2 lines)', out)
        self.assertIn('  def greet():', out)
        self.assertIn('      return "hi"', out)

    def test_command_output_keeps_command_and_output_together(self):
        out, _ = _render([
            {'type': events.ACTION_OUTPUT, 'action_type': 'runReplyCommands',
             'id': 'command_output', 'kind': 'command',
             'label': '$ python3 greet.py', 'text': 'hi'},
        ])
        self.assertIn('  $ python3 greet.py', out)
        self.assertIn('  hi', out)

    def test_a_bodyless_output_draws_its_label_alone(self):
        out, _ = _render([
            {'type': events.ACTION_OUTPUT, 'action_type': 'serveFileReads',
             'id': 'file_context', 'kind': 'read',
             'label': 'greet.py read', 'text': ''},
        ])
        self.assertEqual(out, '  greet.py read\n')


class SpinnerTest(unittest.TestCase):
    """The spinner runs on the busy event and nothing else, and every
    terminating event must close it, or the terminal is left spinning.

    It moved off action.output for one reason: a `"visible": false` action
    emits no action.output, so the terminal used to sit silent for the whole
    of a hidden model call. busy is not gated by that flag. It still spans
    exactly the model call — logger.output emits a busy carrying the resolved
    prompt immediately before gopher.fire.
    """

    def _spinning(self):
        renderer = TerminalRenderer()
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            renderer.handle({'type': events.BUSY, 'active': True,
                             'action_type': 'scramda2', 'preview': 'Q'})
        finally:
            sys.stdout = old
        self.assertIsNotNone(renderer._spinner)
        return renderer

    def test_action_start_alone_does_not_spin(self):
        """A renderer draws the action line; the engine says when it is busy.

        Driven directly rather than through _render(), which stops the spinner
        in its own teardown.
        """
        renderer = TerminalRenderer()
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            renderer.handle({'type': events.ACTION_START,
                             'action_type': 'scramda2', 'id': 'p'})
            spinner = renderer._spinner
        finally:
            sys.stdout = old
            renderer._stop_spinner()
        self.assertIsNone(spinner)

    def test_a_prompt_payload_alone_does_not_spin(self):
        """One spinner, one source. logger.output emits the busy itself, and
        starting it here as well is how the two would drift apart.

        The box is asserted through the termui call, not through stdout: this
        module runs plain (setUpModule), and engine.scramda_input draws nothing
        at all unless rich mode is on.
        """
        renderer = TerminalRenderer()
        with patch.object(termui, 'scramda_input') as box:
            renderer.handle({'type': events.ACTION_OUTPUT,
                             'action_type': 'scramda2', 'id': 'p',
                             'kind': 'prompt', 'label': 'orchestrator',
                             'text': 'Q'})
            spinner = renderer._spinner
        renderer._stop_spinner()

        self.assertIsNone(spinner)
        # Still routed to the prompt box, not to the generic payload path.
        box.assert_called_once_with('Q', model='orchestrator')

    def test_busy_inactive_stops_the_spinner(self):
        self._stopped_by({'type': events.BUSY, 'active': False,
                          'action_type': '', 'preview': ''})

    def test_a_second_busy_relabels_rather_than_stacking(self):
        renderer = self._spinning()
        first = renderer._spinner
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            renderer.handle({'type': events.BUSY, 'active': True,
                             'action_type': 'scramda2',
                             'preview': 'summarise the workspace'})
            second = renderer._spinner
        finally:
            sys.stdout = old
            renderer._stop_spinner()
        self.assertIsNotNone(second)
        self.assertIsNot(second, first)

    def test_a_payload_output_stops_the_spinner_before_printing(self):
        self._stopped_by({'type': events.ACTION_OUTPUT, 'kind': 'file',
                          'action_type': 'applyFileWrites', 'id': 'w',
                          'label': 'x.py written (1 lines)', 'text': 'pass'})

    def _stopped_by(self, event):
        renderer = self._spinning()
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            renderer.handle(event)
        finally:
            sys.stdout = old
        self.assertIsNone(renderer._spinner)

    def test_action_complete_stops_spinner(self):
        self._stopped_by({'type': events.ACTION_DONE,
                          'action_type': 'scramda2', 'id': 'p', 'data': 'a'})

    def test_action_error_stops_spinner(self):
        self._stopped_by({'type': events.ACTION_ERROR,
                          'action_type': 'scramda2', 'id': 'p',
                          'message': 'handler crashed'})

    def test_run_error_stops_spinner(self):
        self._stopped_by({'type': events.RUN_ERROR, 'message': 'bad'})

    def test_run_cancelled_stops_spinner(self):
        self._stopped_by({'type': events.RUN_CANCELLED})

    def test_log_stops_spinner_before_printing(self):
        self._stopped_by({'type': events.LOG, 'level': 'WARN',
                          'message': 'retrying'})

    def test_detach_stops_spinner(self):
        renderer = self._spinning()
        renderer.detach()
        self.assertIsNone(renderer._spinner)


class DetailTest(unittest.TestCase):

    def test_command_truncated_to_80_chars(self):
        detail = _detail({'action_type': 'shell', 'command': 'c' * 100})
        self.assertIn('c' * 80, detail)
        self.assertNotIn('c' * 81, detail)
        self.assertIn('...', detail)

    def test_a_prompt_on_the_event_is_never_drawn(self):
        """action.start carries no prompt for any action type; if one turns up
        it is a stale template and must not reach a display line."""
        self.assertEqual(
            _detail({'action_type': 'humanDecision', 'prompt': 'Which one?'}),
            '')

    def test_loop_shows_iterations(self):
        detail = _detail({'action_type': 'loop', 'file': 'sub.json',
                          'iterations': 4})
        self.assertIn('file="sub.json"', detail)
        self.assertIn('iterations=4', detail)


if __name__ == '__main__':
    unittest.main()
