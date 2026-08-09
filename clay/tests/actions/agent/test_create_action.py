"""Unit tests for create_action (createAgentAction) handler."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import create_action


class TestCreateAgentAction(unittest.TestCase):

    def test_creates_file_in_agent_dir(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(create_action, '_AGENT_DIR', d):
                result = create_action.handler(
                    {"id": "out", "actionName": "my-tool", "content": "src"},
                    {"src": "def handler(action, data): pass\n"}
                )
            self.assertIsNotNone(result)
            self.assertTrue(os.path.exists(result["data"]))
            self.assertTrue(result["data"].endswith("my_tool_actions.py"))

    def test_kebab_converted_to_snake_case(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(create_action, '_AGENT_DIR', d):
                result = create_action.handler(
                    {"id": "out", "actionName": "dns-resolver", "content": "src"},
                    {"src": "# dns resolver"}
                )
        self.assertIn("dns_resolver_actions.py", result["data"])

    def test_invalid_action_name_blocked(self):
        with patch('builtins.print'):
            result = create_action.handler(
                {"id": "out", "actionName": "../../../etc/passwd", "content": "src"},
                {"src": "malicious"}
            )
        self.assertIsNone(result)

    def test_path_traversal_in_name_blocked(self):
        with patch('builtins.print'):
            result = create_action.handler(
                {"id": "out", "actionName": "good/../evil", "content": "src"},
                {"src": "bad"}
            )
        self.assertIsNone(result)

    def test_missing_action_name_returns_none(self):
        with patch('builtins.print'):
            result = create_action.handler({"id": "out", "content": "src"}, {"src": "x"})
        self.assertIsNone(result)

    def test_missing_content_key_returns_none(self):
        with patch('builtins.print'):
            result = create_action.handler(
                {"id": "out", "actionName": "valid-name"}, {}
            )
        self.assertIsNone(result)

    def test_file_content_written_correctly(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(create_action, '_AGENT_DIR', d):
                result = create_action.handler(
                    {"id": "out", "actionName": "my-action", "content": "src"},
                    {"src": "def handler(a, c):\n    return None\n"}
                )
            with open(result["data"]) as f:
                content = f.read()
        self.assertIn("def handler", content)


if __name__ == '__main__':
    unittest.main()
