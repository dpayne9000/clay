"""ConciseRenderer — what the default terminal draws, and what it refuses to.

Same shape as test_terminal_renderer.py: synthetic events, captured stdout, no
engine. The two files together are the contract for `-v`, so several tests
here render the *same* event twice, once through each renderer, and assert the
difference rather than one side alone. A silencing rule that stops silencing is
invisible otherwise — the assertion still passes against a renderer that draws
nothing at all.
"""

import io
import sys
import unittest
from unittest.mock import patch

from ...run import events, termui
from ...run.renderers.concise import ConciseRenderer
from ...run.renderers.terminal import TerminalRenderer

_prev_plain = termui.PLAIN


def setUpModule():
    termui.set_plain(True)


def tearDownModule():
    termui.set_plain(_prev_plain)


def _draw(renderer_cls, sequence):
    """Feed events to a fresh renderer of `renderer_cls`, return stdout."""
    renderer = renderer_cls()
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        for event in sequence:
            renderer.handle(event)
    finally:
        sys.stdout = old
        renderer._stop_spinner()
    return buf.getvalue()


def _concise(sequence):
    return _draw(ConciseRenderer, sequence)


def _verbose(sequence):
    return _draw(TerminalRenderer, sequence)


class SilencedTest(unittest.TestCase):
    """The five things concise mode drops. Each asserted against -v as well."""

    def test_step_headers_are_dropped_but_verbose_keeps_them(self):
        sequence = [{'type': events.STEP_START, 'step': 'recall'}]
        self.assertNotIn('recall', _concise(sequence))
        self.assertIn('recall', _verbose(sequence))

    def test_action_lines_are_dropped_but_verbose_keeps_them(self):
        sequence = [{'type': events.ACTION_START, 'action_type': 'searchMemory',
                     'id': 'relevant_memory'}]
        self.assertEqual('', _concise(sequence))
        self.assertIn('relevant_memory', _verbose(sequence))

    def test_skipped_actions_are_dropped_but_verbose_keeps_them(self):
        sequence = [{'type': events.ACTION_SKIPPED, 'id': 'review',
                     'action_type': 'workflow', 'key': 'files_written',
                     'value': ''}]
        self.assertEqual('', _concise(sequence))
        self.assertIn('review', _verbose(sequence))

    PROMPT = [{'type': events.ACTION_OUTPUT, 'id': 'reply',
               'action_type': 'scramda2', 'kind': 'prompt',
               'label': 'deepseek-r1', 'text': 'You are a helpful thing.'}]

    def _prompts_drawn(self, renderer_cls):
        """Whether the renderer handed a prompt down to be drawn.

        Asserted at the hand-off rather than in captured stdout, for the reason
        PromptCapTest gives in test_terminal_renderer.py: the box prints only
        when _rich() is true, which needs a real tty, so under the suite
        scramda_input draws nothing for either renderer and stdout cannot tell
        the two apart.
        """
        calls = []
        with patch.object(termui, 'scramda_input',
                          lambda *a, **k: calls.append(a)):
            _draw(renderer_cls, self.PROMPT)
        return calls

    def test_the_outgoing_prompt_is_dropped_but_verbose_keeps_it(self):
        self.assertEqual([], self._prompts_drawn(ConciseRenderer))
        self.assertEqual(1, len(self._prompts_drawn(TerminalRenderer)))

    def test_info_is_dropped_but_verbose_keeps_it(self):
        sequence = [{'type': events.LOG, 'level': 'INFO',
                     'message': 'serveFileReads: read 3 file(s)'}]
        self.assertEqual('', _concise(sequence))
        self.assertIn('read 3 file(s)', _verbose(sequence))


class NeverSilencedTest(unittest.TestCase):
    """What no display mode is allowed to take away."""

    def test_warnings_survive(self):
        out = _concise([{'type': events.LOG, 'level': 'WARN',
                         'message': 'could not reach gopher'}])
        self.assertIn('could not reach gopher', out)

    def test_errors_survive(self):
        out = _concise([{'type': events.LOG, 'level': 'ERROR',
                         'message': 'no such workspace'}])
        self.assertIn('no such workspace', out)

    def test_action_errors_survive(self):
        out = _concise([{'type': events.ACTION_ERROR, 'id': 'write',
                         'action_type': 'applyFileWrites',
                         'message': 'one fence had no path'}])
        self.assertIn('one fence had no path', out)

    def test_the_model_answer_is_the_content_and_is_drawn_whole(self):
        answer = 'line one\nline two\nline three'
        out = _concise([{'type': events.ACTION_DONE, 'action_type': 'scramda2',
                         'id': 'reply', 'data': answer, 'duration_ms': 9}])
        for line in answer.split('\n'):
            self.assertIn(line, out)


class PayloadDrawingTest(unittest.TestCase):
    """The four kinds a turn actually did something with."""

    DIFF = ('--- utils/text.py (before)\n'
            '+++ utils/text.py (after)\n'
            '@@ -1,2 +1,3 @@\n'
            ' def slug(title):\n'
            '-    return title\n'
            '+    return title.strip().lower()\n')

    def test_a_created_file_is_named_without_its_body(self):
        out = _concise([{'type': events.ACTION_OUTPUT, 'id': 'files_written',
                         'action_type': 'applyFileWrites', 'kind': 'file',
                         'label': 'greet.py written (3 lines)',
                         'text': 'print("hello")\n'}])
        self.assertIn('greet.py written (3 lines)', out)
        self.assertNotIn('print("hello")', out)

    def test_an_edited_file_shows_its_diff(self):
        out = _concise([{'type': events.ACTION_OUTPUT, 'id': 'files_written',
                         'action_type': 'applyFileWrites', 'kind': 'diff',
                         'label': 'utils/text.py updated (+1 −1)',
                         'text': self.DIFF}])
        self.assertIn('utils/text.py updated (+1 −1)', out)
        self.assertIn('+    return title.strip().lower()', out)
        self.assertIn('-    return title', out)
        self.assertIn('@@ -1,2 +1,3 @@', out)

    def test_the_diff_file_header_is_not_drawn_twice(self):
        # The label above it already names the file, and '---'/'+++' would
        # colour as a removal and an addition in a themed terminal.
        out = _concise([{'type': events.ACTION_OUTPUT, 'id': 'files_written',
                         'action_type': 'applyFileWrites', 'kind': 'diff',
                         'label': 'utils/text.py updated (+1 −1)',
                         'text': self.DIFF}])
        self.assertNotIn('(before)', out)
        self.assertNotIn('(after)', out)

    def test_a_read_is_named_and_nothing_more(self):
        out = _concise([{'type': events.ACTION_OUTPUT, 'id': 'reviewed_files',
                         'action_type': 'serveFileReads', 'kind': 'read',
                         'label': 'utils/text.py read', 'text': ''}])
        self.assertIn('utils/text.py read', out)

    def test_a_command_is_drawn_with_its_output(self):
        out = _concise([{'type': events.ACTION_OUTPUT, 'id': 'command_output',
                         'action_type': 'runReplyCommands', 'kind': 'command',
                         'label': '$ python3 greet.py', 'text': 'hello\n'}])
        self.assertIn('$ python3 greet.py', out)
        self.assertIn('hello', out)

    def test_an_unknown_kind_falls_through_rather_than_vanishing(self):
        """A payload this class has not been taught about is still a payload.

        The failure mode worth a test: a new action type emits a kind nobody
        added here, and the turn silently stops showing what it did.
        """
        out = _concise([{'type': events.ACTION_OUTPUT, 'id': 'x',
                         'action_type': 'somethingNew', 'kind': 'chart',
                         'label': 'a chart', 'text': 'the body'}])
        self.assertIn('a chart', out)
        self.assertIn('the body', out)


class SpinnerTest(unittest.TestCase):
    """Inherited from the parent, and the only progress signal left."""

    def test_busy_raises_and_drops_the_spinner(self):
        renderer = ConciseRenderer()
        buf, old = io.StringIO(), sys.stdout
        sys.stdout = buf
        try:
            renderer.handle({'type': events.BUSY, 'active': True,
                             'action_type': 'scramda2', 'preview': 'thinking'})
            self.assertIsNotNone(renderer._spinner)
            renderer.handle({'type': events.BUSY, 'active': False,
                             'action_type': '', 'preview': ''})
            self.assertIsNone(renderer._spinner)
        finally:
            sys.stdout = old
            renderer._stop_spinner()


if __name__ == '__main__':
    unittest.main()
