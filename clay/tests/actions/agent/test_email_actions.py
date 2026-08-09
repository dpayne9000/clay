"""Unit tests for sendEmail action handler."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ....actions.agent import email_actions


class TestEmailConfigLoading(unittest.TestCase):

    def test_loads_from_json_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump({
                'smtp_server': 'mail.test.com',
                'smtp_port': 465,
                'smtp_username': 'user@test.com',
                'smtp_password': 'secret',
                'from_email': 'noreply@test.com',
            }, f)
            f.flush()
            with patch.object(email_actions, 'CONFIG_PATH', f.name):
                cfg = email_actions._load_config()
        os.unlink(f.name)
        self.assertEqual(cfg['smtp_server'], 'mail.test.com')
        self.assertEqual(cfg['smtp_port'], 465)
        self.assertEqual(cfg['from_email'], 'noreply@test.com')

    def test_falls_back_to_env_vars(self):
        env = {
            'CLAY_SMTP_SERVER': 'env.smtp.com',
            'CLAY_SMTP_PORT': '2525',
            'CLAY_SMTP_USERNAME': 'envuser',
            'CLAY_SMTP_PASSWORD': 'envpass',
            'CLAY_FROM_EMAIL': 'env@test.com',
        }
        with patch.object(email_actions, 'CONFIG_PATH', '/nonexistent'), \
             patch.dict(os.environ, env, clear=False):
            cfg = email_actions._load_config()
        self.assertEqual(cfg['smtp_server'], 'env.smtp.com')
        self.assertEqual(cfg['from_email'], 'env@test.com')


class TestEmailHandler(unittest.TestCase):

    def _action(self, **overrides):
        return {'id': 'email_result', 'to': 'recipient@test.com', 'body': 'msg', **overrides}

    @patch.object(email_actions, 'send_email')
    def test_sends_email_with_resolved_fields(self, mock_send):
        ctx = {'msg': 'Hello world', 'name': 'Alice'}
        result = email_actions.handler(
            self._action(to='to-{name}@test.com', subject='Hi {name}'),
            ctx,
        )
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        self.assertEqual(args[0], 'to-Alice@test.com')
        self.assertEqual(args[1], 'Hi Alice')
        self.assertIn('sent to', result['data'])

    @patch.object(email_actions, 'send_email')
    def test_body_resolved_from_context_key(self, mock_send):
        email_actions.handler(self._action(body='content'), {'content': 'The body'})
        args = mock_send.call_args[0]
        self.assertEqual(args[2], 'The body')

    @patch.object(email_actions, 'send_email')
    def test_body_literal_fallback(self, mock_send):
        email_actions.handler(self._action(body='literal text'), {})
        args = mock_send.call_args[0]
        self.assertEqual(args[2], 'literal text')

    def test_missing_to_returns_none(self):
        result = email_actions.handler({'id': 'x', 'body': 'y', 'to': ''}, {})
        self.assertIsNone(result)

    @patch.object(email_actions, 'send_email', side_effect=Exception('Connection refused'))
    def test_smtp_failure_returns_error(self, _):
        result = email_actions.handler(self._action(), {'msg': 'x'})
        self.assertIn('error', result['data'])

    @patch.object(email_actions, 'send_email')
    def test_id_preserved(self, mock_send):
        result = email_actions.handler(self._action(id='my_id'), {'msg': 'x'})
        self.assertEqual(result['id'], 'my_id')

    @patch.object(email_actions, 'send_email')
    def test_default_subject(self, mock_send):
        email_actions.handler(self._action(), {'msg': 'x'})
        args = mock_send.call_args[0]
        self.assertEqual(args[1], 'No Subject')

    @patch.object(email_actions, 'send_email')
    def test_html_format_passed(self, mock_send):
        email_actions.handler(self._action(format='html'), {'msg': '<b>bold</b>'})
        args = mock_send.call_args[0]
        self.assertEqual(args[3], 'html')


if __name__ == '__main__':
    unittest.main()
