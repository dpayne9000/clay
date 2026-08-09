"""Unit tests for report_actions (email) handler."""

import unittest
from unittest.mock import patch, MagicMock

from ...actions import report_actions

_SMTP_FIELDS = {
    "to_email": "to@example.com",
    "from_email": "from@example.com",
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "smtp_username": "user",
    "smtp_password": "pass",
}


class TestReportActions(unittest.TestCase):

    def _action(self, **overrides):
        a = {"id": "email", "subject": "Test", "body": "msg", **_SMTP_FIELDS}
        a.update(overrides)
        return a

    def test_sends_email_with_all_fields_present(self):
        with patch.object(report_actions, '_send_email') as mock_send:
            result = report_actions.handler(self._action(), {"msg": "Hello!"})
        mock_send.assert_called_once()
        self.assertIsNotNone(result)
        self.assertIn("to@example.com", result["data"])

    def test_body_resolved_from_context_key(self):
        with patch.object(report_actions, '_send_email') as mock_send:
            report_actions.handler(self._action(body="content"), {"content": "My report body"})
        _, kwargs = mock_send.call_args if mock_send.call_args else ((), {})
        call_args = mock_send.call_args[0]
        self.assertEqual(call_args[1], "My report body")

    def test_body_literal_fallback_when_key_not_in_ctx(self):
        with patch.object(report_actions, '_send_email') as mock_send:
            report_actions.handler(self._action(body="literal body text"), {})
        call_args = mock_send.call_args[0]
        self.assertEqual(call_args[1], "literal body text")

    def test_missing_to_email_returns_none(self):
        action = self._action()
        del action["to_email"]
        with patch('builtins.print'):
            result = report_actions.handler(action, {})
        self.assertIsNone(result)

    def test_missing_smtp_server_returns_none(self):
        action = self._action()
        del action["smtp_server"]
        with patch('builtins.print'):
            result = report_actions.handler(action, {})
        self.assertIsNone(result)

    def test_missing_smtp_password_returns_none(self):
        action = self._action()
        del action["smtp_password"]
        with patch('builtins.print'):
            result = report_actions.handler(action, {})
        self.assertIsNone(result)

    def test_smtp_exception_returns_error_string(self):
        with patch.object(report_actions, '_send_email', side_effect=Exception("SMTP refused")), \
             patch('builtins.print'):
            result = report_actions.handler(self._action(), {"msg": "body"})
        self.assertIsNotNone(result)
        self.assertIn("error", result["data"])

    def test_id_preserved_in_result(self):
        with patch.object(report_actions, '_send_email'):
            result = report_actions.handler(self._action(id="my_email"), {"msg": "x"})
        self.assertEqual(result["id"], "my_email")

    def test_default_subject_used_when_absent(self):
        action = self._action()
        del action["subject"]
        with patch.object(report_actions, '_send_email') as mock_send:
            report_actions.handler(action, {"msg": "x"})
        call_args = mock_send.call_args[0]
        self.assertIsNotNone(call_args[0])  # subject is positional arg 0


if __name__ == '__main__':
    unittest.main()
