"""Unit tests for human_shell_actions handler."""

import unittest
from unittest.mock import patch

from ....actions.agent import human_shell_actions


class TestHumanShellActions(unittest.TestCase):

    def test_skip_value_match_returns_skipped(self):
        result = human_shell_actions.handler(
            {"id": "out", "command": "SKIP", "skipValue": "SKIP"}, {}
        )
        self.assertEqual(result["data"], "[skipped]")

    def test_empty_command_returns_skipped(self):
        result = human_shell_actions.handler({"id": "out", "command": ""}, {})
        self.assertEqual(result["data"], "[skipped]")

    def test_blocked_command_returns_blocked_message(self):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "rm -rf /"}, {}
            )
        self.assertIn("blocked", result["data"])

    def test_blocked_command_does_not_prompt_human(self):
        with patch('builtins.print'), patch('builtins.input') as mock_in:
            human_shell_actions.handler({"id": "out", "command": "rm -rf /"}, {})
        mock_in.assert_not_called()

    @patch('builtins.input', return_value='y')
    def test_approved_command_runs(self, _):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "echo hello"}, {}
            )
        self.assertIn("hello", result["data"])

    @patch('builtins.input', return_value='')
    def test_empty_enter_approves(self, _):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "echo ok"}, {}
            )
        self.assertIn("ok", result["data"])

    @patch('builtins.input', return_value='n')
    def test_rejected_command_returns_rejected(self, _):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "echo hello"}, {}
            )
        self.assertEqual(result["data"], "[rejected by user]")

    @patch('builtins.input', return_value='echo edited')
    def test_user_edits_command_and_it_runs(self, _):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "echo original"}, {}
            )
        self.assertIn("edited", result["data"])

    @patch('builtins.input', return_value='rm -rf /edited')
    def test_edited_to_blocked_command_returns_blocked(self, _):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "echo safe"}, {}
            )
        self.assertIn("blocked after edit", result["data"])

    def test_variable_substituted_before_skip_check(self):
        result = human_shell_actions.handler(
            {"id": "out", "command": "{cmd}", "skipValue": "SKIP"},
            {"cmd": "SKIP"}
        )
        self.assertEqual(result["data"], "[skipped]")

    @patch('builtins.input', return_value='y')
    def test_injection_chars_stripped_from_variable(self, _):
        with patch('builtins.print'):
            result = human_shell_actions.handler(
                {"id": "out", "command": "echo {msg}"},
                {"msg": "safe`rm -rf /`end"}
            )
        self.assertIsNotNone(result)
        self.assertNotIn("`", result.get("data", ""))

    @patch('builtins.input', return_value='y')
    def test_always_prompts_even_in_auto_mode(self, mock_input):
        with patch('builtins.print'):
            human_shell_actions.handler(
                {"id": "out", "command": "echo x"}, {}, auto=True
            )
        mock_input.assert_called_once()


if __name__ == '__main__':
    unittest.main()
