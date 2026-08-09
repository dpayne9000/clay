"""Unit tests for the chat renderer.

The bug these exist for: a Telegram user saw neither the action being run nor
the prompt going to the model nor the files being written, while a CLI user saw
all three. The renderer is the single place that decides that now, so parity is
asserted here rather than through a bot, a daemon and a socket.
"""

import unittest
from unittest.mock import patch

from ...lib import config
from ...run import events
from ...run.renderers.chat import ChatRenderer, ConciseChatRenderer


class _RenderTestCase(unittest.TestCase):

    def setUp(self):
        self.renderer = ChatRenderer()

    def render(self, **event):
        return self.renderer.render(event)


class ActionStartTest(_RenderTestCase):

    def test_names_the_action_and_its_id(self):
        text = self.render(type=events.ACTION_START,
                           action_type='applyFileWrites', id='files_written')
        self.assertIn('applyFileWrites', text)
        self.assertIn('files_written', text)

    def test_model_call_summary_shows_the_model_and_no_prompt(self):
        """A scramda2 action.start carries no prompt — the resolved text
        arrives separately as an action.output."""
        text = self.render(type=events.ACTION_START, action_type='scramda2',
                           id='reply', model='orchestrator')
        self.assertNotIn('prompt', text)
        self.assertIn('orchestrator', text)

    def test_non_model_action_gets_no_prompt_echo(self):
        text = self.render(type=events.ACTION_START, action_type='shell',
                           id='run', command='python3 flap.py')
        self.assertNotIn('prompt:', text)
        self.assertIn('python3 flap.py', text)

    def test_empty_action_draws_nothing(self):
        self.assertIsNone(self.render(type=events.ACTION_START))


class ActionOutputTest(_RenderTestCase):
    """The payload events — a prompt, a written file, a command's output.

    This is where a per-front-end visibility list would go, so the fields it
    would filter on (kind, id, action_type) are asserted to be usable.
    """

    def _prompt(self, text, **extra):
        return self.render(type=events.ACTION_OUTPUT, action_type='scramda2',
                           id='reply', kind='prompt', text=text, **extra)

    def test_the_prompt_is_echoed_with_its_model(self):
        text = self._prompt('Write the flapping bird', label='orchestrator')
        self.assertIn('Write the flapping bird', text)
        self.assertIn('orchestrator', text)

    def test_a_long_prompt_is_cut_to_the_configured_limit(self):
        """A coding workflow's prompt is the whole mission, protocol and
        transcript — resent every turn, and not what a chat is for."""
        prompt = 'line one\n' + ('word ' * 2000) + '\nlast line'
        with patch.object(config, 'get_prompt_max_chars', return_value=20):
            echo = self._prompt(prompt).split('prompt:\n', 1)[1]

        self.assertTrue(echo.startswith(prompt[:20]))
        self.assertIn('more characters', echo)
        self.assertNotIn('last line', echo)

    def test_zero_shows_the_whole_prompt(self):
        prompt = 'line one\n' + ('word ' * 2000) + '\nlast line'
        with patch.object(config, 'get_prompt_max_chars', return_value=0):
            echo = self._prompt(prompt).split('prompt:\n', 1)[1]

        self.assertEqual(echo, prompt.strip())

    def test_line_breaks_in_the_prompt_survive(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=0):
            self.assertIn('first\nsecond', self._prompt('first\nsecond'))

    def test_the_model_answer_is_never_cut(self):
        # display.promptMaxChars caps the prompt going out. The answer is the
        # result of the run and every front-end shows all of it.
        answer = 'a' * 5000
        with patch.object(config, 'get_prompt_max_chars', return_value=10):
            text = self.render(type=events.ACTION_DONE, id='reply',
                               action_type='scramda2', data=answer)
        self.assertEqual(text, answer)

    def test_a_written_file_shows_its_header_and_contents(self):
        text = self.render(type=events.ACTION_OUTPUT, kind='file',
                           action_type='applyFileWrites', id='files_written',
                           label='greet.py written (2 lines)',
                           text='def greet():\n    return "hi"')
        self.assertEqual(
            text, 'greet.py written (2 lines)\ndef greet():\n    return "hi"')

    def test_a_command_arrives_with_its_output(self):
        text = self.render(type=events.ACTION_OUTPUT, kind='command',
                           action_type='runReplyCommands', id='command_output',
                           label='$ python3 greet.py', text='hi\nthere')
        self.assertEqual(text, '$ python3 greet.py\nhi\nthere')

    def test_a_bodyless_output_is_its_label(self):
        text = self.render(type=events.ACTION_OUTPUT, kind='read',
                           action_type='serveFileReads', id='file_context',
                           label='greet.py read', text='')
        self.assertEqual(text, 'greet.py read')

    def test_an_empty_prompt_draws_nothing(self):
        self.assertIsNone(self._prompt('   '))

    def test_kind_and_provenance_are_available_to_filter_on(self):
        """The documented way to silence prompts and workspace scanning in the
        chat is `if event.get('kind') in ('prompt', 'read')`, so the fields
        have to be exactly these tokens."""
        for kind in ('prompt', 'file', 'command', 'read'):
            with self.subTest(kind=kind):
                event = {'type': events.ACTION_OUTPUT, 'kind': kind,
                         'action_type': 'scramda2', 'id': 'reply',
                         'label': 'l', 'text': 'body'}
                self.assertTrue(self.renderer.render(event))


class PayloadCapTest(_RenderTestCase):
    """display.payloadMaxChars reaches the chat exactly as it reaches the CLI.

    Asserted here as well as in test_payload_lines because the chat takes a
    different route into the same helper — payload_body() directly rather than
    through payload_lines() — and a chat that pastes an entire memory store
    into a thread is the case this setting exists for.
    """

    def _body(self, action_type, text):
        return self.render(type=events.ACTION_OUTPUT, kind='read',
                           action_type=action_type, id='mem',
                           label='memory read', text=text)

    def test_a_capped_action_is_cut(self):
        with patch.object(config, 'get_payload_max_chars', return_value=10):
            text = self._body('writeMemory', 'm' * 500)

        self.assertIn('m' * 10, text)
        self.assertNotIn('m' * 11, text)
        self.assertIn('490 more characters', text)
        self.assertIn('run log', text)
        self.assertTrue(text.startswith('memory read\n'))

    def test_an_uncapped_action_is_whole(self):
        # applyFileWrites has no entry in the shipped table: the file a turn
        # just wrote is the turn's result, not something quoted back off disk.
        with patch.object(config, 'get_payload_max_chars', return_value=0):
            text = self._body('applyFileWrites', 'y' * 5000)

        self.assertIn('y' * 5000, text)
        self.assertNotIn('more characters', text)

    def test_the_cap_is_looked_up_by_action_type(self):
        seen = []

        def fake(action_type):
            seen.append(action_type)
            return 0

        with patch.object(config, 'get_payload_max_chars', fake):
            self._body('serveFileReads', 'y')

        self.assertEqual(seen, ['serveFileReads'])

    def test_the_payload_cap_does_not_reach_the_model_answer(self):
        answer = 'a' * 5000
        with patch.object(config, 'get_payload_max_chars', return_value=10):
            text = self.render(type=events.ACTION_DONE, id='reply',
                               action_type='scramda2', data=answer)
        self.assertEqual(text, answer)


class ActionSkippedTest(_RenderTestCase):

    def test_the_gated_action_and_the_value_that_closed_it(self):
        text = self.render(type=events.ACTION_SKIPPED, action_type='loop',
                           id='review_log', key='files_written', value='')
        self.assertIn('review_log', text)
        self.assertIn('files_written', text)

    def test_an_anonymous_skip_draws_nothing(self):
        self.assertIsNone(self.render(type=events.ACTION_SKIPPED))


class ActionDoneTest(_RenderTestCase):

    def test_model_answer_is_the_message(self):
        text = self.render(type=events.ACTION_DONE, action_type='scramda2',
                           id='reply', data='  the model answer  ')
        self.assertEqual(text, 'the model answer')

    def test_other_action_payloads_are_not_pasted_into_the_chat(self):
        self.assertIsNone(self.render(
            type=events.ACTION_DONE, action_type='writeFile',
            id='save', data='the entire file body'))

    def test_empty_answer_draws_nothing(self):
        self.assertIsNone(self.render(
            type=events.ACTION_DONE, action_type='scramda2', id='r', data='  '))


class LogTest(_RenderTestCase):

    def test_info_is_relayed_verbatim(self):
        """`flap.py written` and `$ python3 flap.py` are INFO logs."""
        self.assertEqual(
            self.render(type=events.LOG, level='INFO',
                        message='flap.py written'),
            'flap.py written')

    def test_warn_and_error_are_labelled(self):
        self.assertIn('WARN', self.render(
            type=events.LOG, level='WARN', message='low disk'))
        self.assertIn('ERROR', self.render(
            type=events.LOG, level='ERROR', message='boom'))

    def test_empty_message_draws_nothing(self):
        self.assertIsNone(self.render(type=events.LOG, level='INFO',
                                      message='   '))


class ErrorTest(_RenderTestCase):

    def test_action_error(self):
        self.assertIn('command failed', self.render(
            type=events.ACTION_ERROR, action_type='shell', id='x',
            message='command failed'))

    def test_run_error(self):
        self.assertIn('file not found', self.render(
            type=events.RUN_ERROR, message='file not found'))

    def test_cancelled_says_so(self):
        self.assertIn('stopped', self.render(type=events.RUN_CANCELLED))


class SilentEventTest(_RenderTestCase):

    def test_run_start_and_complete_draw_nothing(self):
        """The front-end announces the launch and the finish itself, with the
        label the user picked from the menu."""
        self.assertIsNone(self.render(type=events.RUN_START, label='coding2'))
        self.assertIsNone(self.render(type=events.RUN_COMPLETE, label='coding2'))

    def test_loop_iteration_draws_nothing(self):
        self.assertIsNone(self.render(type=events.LOOP_ITERATION, iteration=2))

    def test_input_request_draws_nothing(self):
        """The front-end asks the question itself — it has to hold the prompt
        id to route the answer back. Rendering it here would ask twice."""
        self.assertIsNone(self.render(type=events.INPUT_REQUEST, id='q1',
                                      prompt='Which branch?'))

    def test_unknown_event_draws_nothing(self):
        self.assertIsNone(self.render(type='something.new', message='hi'))

    def test_step_without_a_name_draws_nothing(self):
        self.assertIsNone(self.render(type=events.STEP_START, step=''))


class StepTest(_RenderTestCase):

    def test_step_header_names_the_step(self):
        self.assertIn('converse', self.render(type=events.STEP_START,
                                              step='converse'))


class ParityTest(unittest.TestCase):
    """Every event the terminal renderer draws, the chat renderer draws.

    Not a formatting comparison — the two media differ — but a check that no
    event type is handled by one and silently dropped by the other, which is
    exactly how the reported bug arose.
    """

    DRAWN_BY_TERMINAL = (
        events.STEP_START,
        events.ACTION_START,
        events.ACTION_DONE,
        events.ACTION_ERROR,
        events.ACTION_OUTPUT,
        events.ACTION_SKIPPED,
        events.RUN_ERROR,
        events.RUN_CANCELLED,
        events.LOG,
    )

    def test_no_terminal_event_is_dropped_by_the_chat(self):
        renderer = ChatRenderer()
        sample = {
            events.STEP_START: {'step': 'apply'},
            events.ACTION_START: {'action_type': 'shell', 'id': 'run'},
            events.ACTION_DONE: {'action_type': 'scramda2', 'id': 'r',
                                 'data': 'answer'},
            events.ACTION_ERROR: {'message': 'failed'},
            events.ACTION_OUTPUT: {'action_type': 'applyFileWrites',
                                   'id': 'w', 'kind': 'file',
                                   'label': 'x.py written (1 lines)',
                                   'text': 'pass'},
            events.ACTION_SKIPPED: {'action_type': 'loop', 'id': 'review_log',
                                    'key': 'files_written', 'value': ''},
            events.RUN_ERROR: {'message': 'failed'},
            events.RUN_CANCELLED: {},
            events.LOG: {'level': 'INFO', 'message': 'written'},
        }
        for kind in self.DRAWN_BY_TERMINAL:
            with self.subTest(event=kind):
                text = renderer.render({'type': kind, **sample[kind]})
                self.assertTrue(text, f'{kind} renders nothing for a chat')


class ConciseChatRendererTest(unittest.TestCase):
    """Telegram's default content policy matches CLI operation without -v."""

    def setUp(self):
        self.renderer = ConciseChatRenderer()

    def render(self, **event):
        return self.renderer.render(event)

    def test_diagnostic_narration_is_suppressed(self):
        events_to_hide = (
            {'type': events.STEP_START, 'step': 'orient'},
            {'type': events.ACTION_START, 'action_type': 'scramda2', 'id': 'r'},
            {'type': events.ACTION_SKIPPED, 'id': 'review', 'key': 'continue'},
            {'type': events.ACTION_OUTPUT, 'kind': 'prompt',
             'action_type': 'scramda2', 'id': 'r', 'text': 'internal prompt'},
            {'type': events.LOG, 'level': 'INFO', 'message': 'background query'},
        )
        for event in events_to_hide:
            with self.subTest(event=event['type']):
                self.assertIsNone(self.renderer.render(event))

    def test_model_answers_warnings_errors_and_diffs_remain(self):
        answer = self.render(type=events.ACTION_DONE,
                             action_type='scramda2', id='r', data='answer')
        warning = self.render(type=events.LOG, level='WARN', message='warning')
        error = self.render(type=events.ACTION_ERROR, message='failed')
        diff = self.render(type=events.ACTION_OUTPUT, kind='diff',
                           action_type='applyFileWrites', id='files',
                           label='a.py updated (+1 -1)', text='-old\n+new')
        self.assertEqual(answer, 'answer')
        self.assertIn('warning', warning)
        self.assertIn('failed', error)
        self.assertIn('a.py updated', diff)
        self.assertIn('-old\n+new', diff)

    def test_created_files_and_reads_are_named_without_their_bodies(self):
        created = self.render(type=events.ACTION_OUTPUT, kind='file',
                              action_type='applyFileWrites', id='files',
                              label='a.py written', text='secret body')
        read = self.render(type=events.ACTION_OUTPUT, kind='read',
                           action_type='serveFileReads', id='reads',
                           label='a.py read', text='secret body')
        self.assertEqual(created, 'a.py written')
        self.assertEqual(read, 'a.py read')

    def test_command_output_remains(self):
        command = self.render(type=events.ACTION_OUTPUT, kind='command',
                              action_type='runReplyCommands', id='commands',
                              label='$ python a.py', text='ok')
        self.assertEqual(command, '$ python a.py\nok')


if __name__ == '__main__':
    unittest.main()
