"""Unit tests for human_decision handler and its SafeMap.

Auto mode dispatches a real scramda2 action, so the model boundary to patch
is scramda2_actions.gopher.fire — not a private helper on this module.
"""

import unittest
from unittest.mock import patch

from ...actions import scramda2_actions
from ...actions.human_decision import handler, _SafeMap


class TestSafeMap(unittest.TestCase):

    def test_known_key_substituted(self):
        m = _SafeMap({"name": "Alice"})
        self.assertEqual("Hello Alice".format_map(m), "Hello Alice")

    def test_unknown_key_preserved(self):
        m = _SafeMap({"name": "Alice"})
        result = "Hello {name}, your id is {id}".format_map(m)
        self.assertEqual(result, "Hello Alice, your id is {id}")

    def test_multiple_keys(self):
        m = _SafeMap({"a": "one", "b": "two"})
        self.assertEqual("{a} and {b}".format_map(m), "one and two")

    def test_empty_data(self):
        m = _SafeMap({})
        self.assertEqual("{topic} report".format_map(m), "{topic} report")

    def test_numeric_value(self):
        m = _SafeMap({"n": 42})
        self.assertEqual("count: {n}".format_map(m), "count: 42")


class TestHumanDecisionHandler(unittest.TestCase):

    @patch('builtins.input', return_value="Paris")
    def test_returns_user_input(self, _):
        result = handler({"id": "city", "prompt": "Enter city"}, {})
        self.assertEqual(result, {"id": "city", "data": "Paris"})

    @patch('builtins.input', return_value="investors")
    def test_substitutes_variable_in_prompt(self, mock_input):
        handler({"id": "out", "prompt": "Who is the {role}?"}, {"role": "audience"})
        call_arg = mock_input.call_args[0][0]
        self.assertIn("Who is the audience?", call_arg)
        self.assertNotIn("{role}", call_arg)

    @patch('builtins.input', return_value="x")
    def test_missing_variable_preserved(self, mock_input):
        handler(
            {"id": "out", "prompt": "Topic: {topic}, Type: {doc_type}"},
            {"topic": "AI"}
        )
        call_arg = mock_input.call_args[0][0]
        self.assertIn("Topic: AI", call_arg)
        self.assertIn("{doc_type}", call_arg)

    def test_empty_prompt_returns_none(self):
        result = handler({"id": "out", "prompt": ""}, {})
        self.assertIsNone(result)

    def test_missing_prompt_returns_none(self):
        result = handler({"id": "out"}, {})
        self.assertIsNone(result)

    @patch('builtins.input', return_value="feedback here")
    def test_id_stored_in_result(self, _):
        result = handler({"id": "my_key", "prompt": "Enter:"}, {})
        self.assertEqual(result["id"], "my_key")
        self.assertEqual(result["data"], "feedback here")

    @patch('builtins.input', return_value="")
    def test_empty_input_stored(self, _):
        result = handler({"id": "out", "prompt": "Press enter"}, {})
        self.assertEqual(result["data"], "")

    @patch('builtins.input')
    @patch.object(scramda2_actions.gopher, 'fire', return_value="auto answer")
    def test_auto_mode_dispatches_scramda2_not_input(self, mock_fire, mock_input):
        result = handler(
            {"id": "out", "prompt": "What is it?"},
            {},
            auto=True,
            auto_context="some context"
        )
        mock_fire.assert_called_once()
        mock_input.assert_not_called()
        self.assertEqual(result["data"], "auto answer")

    @patch('builtins.input')
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ai response")
    def test_auto_mode_prompt_includes_auto_context_and_resolved_prompt(self, mock_fire, mock_input):
        handler(
            {"id": "out", "prompt": "Summarise {topic}"},
            {"topic": "AI"},
            auto=True,
            auto_context="You are a helpful assistant"
        )
        sent_prompt = mock_fire.call_args[0][0]
        self.assertIn("You are a helpful assistant", sent_prompt)
        self.assertIn("Summarise AI", sent_prompt)

    @patch('builtins.input')
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_auto_mode_prompt_includes_accumulated_context(self, mock_fire, mock_input):
        handler(
            {"id": "out", "prompt": "Next step?"},
            {"topic": "AI", "draft": "some draft text"},
            auto=True
        )
        sent_prompt = mock_fire.call_args[0][0]
        self.assertIn("topic", sent_prompt)
        self.assertIn("draft", sent_prompt)

    @patch('builtins.input')
    @patch.object(scramda2_actions.gopher, 'fire')
    def test_non_auto_mode_never_calls_the_model(self, mock_fire, mock_input):
        mock_input.return_value = "user typed this"
        handler({"id": "out", "prompt": "Enter value"}, {}, auto=False)
        mock_fire.assert_not_called()


if __name__ == '__main__':
    unittest.main()
