"""payload_lines — the shared action.output renderer for text surfaces.

Used by `clay attach` and the three Qt surfaces (panels, manager, dashboard).
The terminal uses it too, but not for prompts: it returns at kind 'prompt'
and draws those in its own box, so the cut here must not double-apply.
"""

import unittest
from unittest.mock import patch

from ...lib import config
from ...run.renderers.detail import payload_lines


def _output(kind, label='', text='', action_type='scramda2'):
    return {'type': 'action.output', 'id': 'reply', 'action_type': action_type,
            'kind': kind, 'label': label, 'text': text}


class LayoutTest(unittest.TestCase):

    def test_header_then_body_every_line_indented(self):
        drawn = payload_lines(_output('file', 'greet.py written',
                                      'def greet():\n    return "hi"'))
        self.assertEqual(drawn, '  greet.py written\n'
                                '  def greet():\n'
                                '      return "hi"')

    def test_a_label_with_no_body_stands_alone(self):
        self.assertEqual(payload_lines(_output('file', 'gone.py removed')),
                         '  gone.py removed')

    def test_the_indent_is_caller_chosen(self):
        self.assertEqual(payload_lines(_output('read', 'x'), indent='> '),
                         '> x')


class PromptCapTest(unittest.TestCase):
    """display.promptMaxChars reaches every surface that draws through here."""

    def test_a_long_prompt_is_cut(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=10):
            drawn = payload_lines(_output('prompt', 'code', 'p' * 500))

        self.assertIn('p' * 10, drawn)
        self.assertNotIn('p' * 11, drawn)
        self.assertIn('490 more characters', drawn)

    def test_the_label_survives_the_cut(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=10):
            drawn = payload_lines(_output('prompt', 'code', 'p' * 500))

        self.assertTrue(drawn.startswith('  code\n'))

    def test_zero_draws_the_whole_prompt(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=0):
            drawn = payload_lines(_output('prompt', 'code', 'p' * 5000))

        self.assertIn('p' * 5000, drawn)

    def test_a_short_prompt_is_untouched(self):
        with patch.object(config, 'get_prompt_max_chars', return_value=1000):
            drawn = payload_lines(_output('prompt', 'code', 'say hello'))

        self.assertEqual(drawn, '  code\n  say hello')

    def test_the_prompt_cap_does_not_reach_other_payloads(self):
        # promptMaxChars is the prompt going to the model, and nothing else.
        # Bodies have their own per-action table; an action absent from it is
        # drawn whole no matter how tight the prompt cap is.
        with patch.object(config, 'get_prompt_max_chars', return_value=10):
            for kind in ('file', 'command', 'read'):
                with self.subTest(kind=kind):
                    drawn = payload_lines(_output(kind, 'x', 'y' * 500))
                    self.assertIn('y' * 500, drawn)
                    self.assertNotIn('more characters', drawn)


class PayloadCapTest(unittest.TestCase):
    """display.payloadMaxChars — per action type, not per kind."""

    def test_a_capped_action_is_cut_and_says_where_the_rest_is(self):
        with patch.object(config, 'get_payload_max_chars', return_value=10):
            drawn = payload_lines(_output('file', 'entry written',
                                          'm' * 500, action_type='writeMemory'))

        self.assertIn('m' * 10, drawn)
        self.assertNotIn('m' * 11, drawn)
        self.assertIn('490 more characters', drawn)
        self.assertIn('run log', drawn)

    def test_the_label_survives_the_cut(self):
        with patch.object(config, 'get_payload_max_chars', return_value=10):
            drawn = payload_lines(_output('file', 'entry written',
                                          'm' * 500, action_type='writeMemory'))

        self.assertTrue(drawn.startswith('  entry written\n'))

    def test_zero_draws_the_whole_body(self):
        with patch.object(config, 'get_payload_max_chars', return_value=0):
            drawn = payload_lines(_output('read', 'x', 'm' * 5000,
                                          action_type='searchMemory'))

        self.assertIn('m' * 5000, drawn)

    def test_the_cap_is_looked_up_by_action_type(self):
        seen = []

        def fake(action_type):
            seen.append(action_type)
            return 0

        with patch.object(config, 'get_payload_max_chars', fake):
            payload_lines(_output('file', 'x', 'y', action_type='writeSkill'))

        self.assertEqual(seen, ['writeSkill'])

    def _with_shipped_table(self):
        """The real lookup over the shipped table, whatever the dev's config says.

        These two assert the *scope decision* — which actions are in the table
        and which are not — so they must not read ~/.clay/config.json, or they
        would pass or fail on the machine rather than on the code.
        """
        return patch.object(
            config, 'load_config',
            return_value={'display':
                          {'payloadMaxChars': config.DEFAULT_PAYLOAD_MAX_CHARS}})

    def test_an_action_with_no_entry_is_drawn_whole(self):
        # applyFileWrites is deliberately absent: the file a turn just wrote is
        # the turn's result, and the reasoning that leaves a model's answer
        # uncapped applies to it too.
        with self._with_shipped_table():
            drawn = payload_lines(_output('file', 'greet.py written', 'y' * 5000,
                                          action_type='applyFileWrites'))

        self.assertIn('y' * 5000, drawn)
        self.assertNotIn('more characters', drawn)

    def test_every_scoped_action_is_capped(self):
        # An existing ~/.clay/config.json predates the key and is never
        # back-filled, so these must be capped without any config edit.
        with self._with_shipped_table():
            for action_type in ('writeMemory', 'searchMemory', 'listMemory',
                                'readMemory', 'writeSkill', 'listSkills',
                                'searchSkills', 'removeSkill', 'serveFileReads'):
                with self.subTest(action_type=action_type):
                    drawn = payload_lines(_output('read', 'x', 'y' * 5000,
                                                  action_type=action_type))
                    self.assertIn('more characters', drawn)


if __name__ == '__main__':
    unittest.main()
