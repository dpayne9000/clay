"""Unit tests for manual approval.

What these exist for: a gate that fails open is worse than no gate. Every test
that reads like a formality — a typo approves nothing, a closed channel
approves nothing, an unknown gate name raises — is there because the failure it
describes is silent, and a workspace written without being asked about looks
exactly like one written after a yes.
"""

import unittest
from unittest.mock import patch

from ...run import approval, commands, io


class _FakeIO:
    """An input channel with a queue of scripted answers."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def prompt(self, prompt_id, text):
        self.prompts.append((prompt_id, text))
        return self.answers.pop(0) if self.answers else ''


class _ClosedIO:
    def prompt(self, prompt_id, text):
        raise io.ChannelClosed('gone')


class _ApprovalTestCase(unittest.TestCase):

    def setUp(self):
        approval.reset()
        self.addCleanup(approval.reset)

    def confirm(self, *answers, gate='fileWrites', items=None):
        channel = _FakeIO(*answers)
        with patch.object(io, 'get', return_value=channel):
            decision = approval.confirm(
                gate, 'do these things:',
                items if items is not None else [('a', ''), ('b', ''), ('c', '')])
        self.channel = channel
        return decision


class StateTest(_ApprovalTestCase):

    def test_defaults_come_from_config_and_gate_nothing(self):
        # The shipped default is off, so installing this changes no behaviour
        # for anyone who does not ask for it.
        self.assertFalse(approval.manual())
        for gate in approval.GATES:
            self.assertFalse(approval.enabled(gate))

    def test_master_switch_reveals_the_gates_underneath(self):
        approval.set_manual(True)
        self.assertTrue(approval.enabled('fileWrites'))
        self.assertTrue(approval.enabled('commands'))
        # Reads are the one gate off by default.
        self.assertFalse(approval.enabled('fileReads'))

    def test_a_gate_alone_does_nothing_until_manual_is_on(self):
        approval.set_gate('fileReads', True)
        self.assertFalse(approval.enabled('fileReads'))
        approval.set_manual(True)
        self.assertTrue(approval.enabled('fileReads'))

    def test_turning_manual_off_and_on_keeps_the_arrangement(self):
        approval.set_manual(True)
        approval.set_gate('fileWrites', False)
        approval.set_manual(False)
        approval.set_manual(True)
        self.assertFalse(approval.enabled('fileWrites'))

    def test_an_unknown_gate_raises_rather_than_being_ignored(self):
        with self.assertRaises(ValueError):
            approval.set_gate('fileWrite', True)

    def test_state_is_a_copy(self):
        approval.state()['manual'] = True
        self.assertFalse(approval.manual())

    def test_a_non_boolean_in_config_falls_back_and_says_so(self):
        from ...lib import config
        with patch.object(config, 'load_config',
                          return_value={'approval': {'manual': 'yes'}}):
            config._approval_bad_keys.clear()
            settings = config.get_approval_defaults()
        self.assertFalse(settings['manual'])


class CommandGrammarTest(_ApprovalTestCase):

    def test_a_plain_answer_is_not_a_command(self):
        self.assertIsNone(commands.handle('write me a parser'))
        self.assertIsNone(approval.parse_command('manual on'))

    def test_manual_on_and_off(self):
        commands.handle('/manual on')
        self.assertTrue(approval.manual())
        commands.handle('/manual off')
        self.assertFalse(approval.manual())

    def test_gate_aliases(self):
        approval.set_manual(True)
        for word in ('reads', 'read', 'fileReads'):
            commands.handle(f'/manual {word} off')
            self.assertFalse(approval.enabled('fileReads'))
            commands.handle(f'/manual {word} on')
            self.assertTrue(approval.enabled('fileReads'))

    def test_a_bare_manual_reports_without_changing_anything(self):
        before = approval.state()
        message = commands.handle('/manual')
        self.assertEqual(before, approval.state())
        self.assertIn('manual approval', message)

    def test_an_unknown_gate_changes_nothing_and_says_so(self):
        before = approval.state()
        message = commands.handle('/manual sideways on')
        self.assertEqual(before, approval.state())
        self.assertIn('not a manual setting', message)

    def test_a_gate_set_while_manual_is_off_says_it_is_not_live_yet(self):
        message = commands.handle('/manual writes on')
        self.assertIn('takes effect', message)

    def test_an_unknown_command_is_answered_not_passed_through(self):
        # It must not fall through to the workflow as an answer: "/undo" typed
        # at a coding prompt would otherwise become the next request.
        message = commands.handle('/undo')
        self.assertIsNotNone(message)
        self.assertIn('not a command', message)

    def test_parse_command_reports_changes_without_applying_them(self):
        parsed = approval.parse_command('/manual on')
        self.assertEqual([('manual', True)], parsed.changes)
        self.assertFalse(approval.manual())


class ConfirmTest(_ApprovalTestCase):

    def test_a_disabled_gate_approves_everything_without_asking(self):
        decision = self.confirm('n')
        self.assertTrue(decision.all_approved)
        self.assertEqual([], self.channel.prompts)

    def test_blank_and_y_approve_everything(self):
        approval.set_manual(True)
        for answer in ('', '  ', 'y', 'Y', 'yes', 'all'):
            self.assertTrue(self.confirm(answer).all_approved, answer)

    def test_n_approves_nothing(self):
        approval.set_manual(True)
        for answer in ('n', 'no', 'none', 'reject'):
            decision = self.confirm(answer)
            self.assertEqual([], decision.approved, answer)
            self.assertFalse(decision)

    def test_numbers_name_what_to_skip_not_what_to_keep(self):
        approval.set_manual(True)
        decision = self.confirm('2')
        self.assertEqual(['a', 'c'], decision.approved_labels())
        self.assertEqual(['b'], decision.rejected_labels())

    def test_several_numbers_with_or_without_commas(self):
        approval.set_manual(True)
        for answer in ('1 3', '1,3', '1, 3', '3 1'):
            self.assertEqual(['b'], self.confirm(answer).approved_labels(), answer)

    def test_an_unreadable_answer_approves_nothing(self):
        # The direction that matters: a typo must never be read as consent.
        approval.set_manual(True)
        for answer in ('maybe', '2 or 3', 'y n', '-1'):
            self.assertEqual([], self.confirm(answer).approved, answer)

    def test_an_out_of_range_number_approves_nothing(self):
        approval.set_manual(True)
        self.assertEqual([], self.confirm('9').approved)
        self.assertEqual([], self.confirm('0').approved)

    def test_a_closed_channel_approves_nothing(self):
        approval.set_manual(True)
        with patch.object(io, 'get', return_value=_ClosedIO()):
            decision = approval.confirm('fileWrites', 'do it',
                                        [('a', ''), ('b', '')])
        self.assertEqual([], decision.approved)

    def test_an_unattended_run_rejects_enabled_approval_items(self):
        approval.set_manual(True)
        approval.set_unattended(True)
        decision = self.confirm('n')
        self.assertEqual([], decision.approved)
        self.assertEqual([], self.channel.prompts)

    def test_a_required_gate_cannot_be_disabled(self):
        approval.set_manual(False)
        with patch.object(io, 'get', return_value=_FakeIO('n')):
            decision = approval.confirm(
                'fileWrites', 'do it', [('a', '')], required=True)
        self.assertEqual([], decision.approved)

    def test_an_empty_item_list_asks_nothing(self):
        approval.set_manual(True)
        decision = self.confirm('n', items=[])
        self.assertTrue(decision.all_approved)
        self.assertEqual([], self.channel.prompts)

    def test_the_prompt_id_marks_it_as_an_approval(self):
        approval.set_manual(True)
        channel = _FakeIO('y')
        with patch.object(io, 'get', return_value=channel):
            approval.confirm('fileWrites', 'do it', [('a', '')],
                             prompt_id='writes')
        prompt_id, text = channel.prompts[0]
        self.assertTrue(prompt_id.endswith(approval.PROMPT_SUFFIX))
        # Every item is numbered in the text, or the numeric answer is unusable.
        self.assertIn('1. a', text)

    def test_details_are_shown_under_their_item(self):
        approval.set_manual(True)
        channel = _FakeIO('y')
        with patch.object(io, 'get', return_value=channel):
            approval.confirm('fileWrites', 'do it', [('x.py', '--- a\n+++ b')])
        self.assertIn('+++ b', channel.prompts[0][1])


class TerminalCommandInterceptionTest(_ApprovalTestCase):

    def test_a_command_is_answered_and_the_question_asked_again(self):
        # The workflow must never see the command, and must still get its
        # answer — a setting change is not an answer to anything.
        typed = iter(['/manual on', 'the real answer'])
        echoed = []
        with patch('builtins.input', lambda _: next(typed)), \
             patch('clay.run.termui.command_echo',
                   lambda cmd, out: echoed.append((cmd, out))):
            answer = io.TerminalIO().prompt('q', 'what next?')
        self.assertEqual('the real answer', answer)
        self.assertTrue(approval.manual())
        self.assertEqual(1, len(echoed))
        self.assertEqual('/manual on', echoed[0][0])


class SocketOptionTest(_ApprovalTestCase):

    def _channel(self):
        channel = io.SocketIO.__new__(io.SocketIO)
        return channel

    def test_option_set_changes_this_process(self):
        channel = self._channel()
        channel._set_option('manual', True)
        self.assertTrue(approval.manual())
        channel._set_option('fileReads', True)
        self.assertTrue(approval.enabled('fileReads'))

    def test_an_unknown_key_is_ignored_rather_than_guessed(self):
        channel = self._channel()
        before = approval.state()
        channel._set_option('fileWrite', True)
        self.assertEqual(before, approval.state())


if __name__ == '__main__':
    unittest.main()
