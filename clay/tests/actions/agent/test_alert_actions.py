"""Unit tests for sendAlert action handler."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ....actions.agent import alert_actions, email_actions


class TestAlertFileChannel(unittest.TestCase):

    def test_appends_to_log_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'test-alerts.log')
            cfg = {'channels': {'file': {'enabled': True, 'path': log_path}}}
            with patch.object(alert_actions, '_load_config', return_value=cfg):
                result = alert_actions.handler(
                    {'id': 'a', 'channel': 'file', 'message': 'disk full', 'level': 'critical'},
                    {},
                )
            self.assertIn('logged to', result['data'])
            with open(log_path) as f:
                content = f.read()
            self.assertIn('[CRITICAL]', content)
            self.assertIn('disk full', content)

    def test_multiple_alerts_append(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'multi.log')
            cfg = {'channels': {'file': {'enabled': True, 'path': log_path}}}
            with patch.object(alert_actions, '_load_config', return_value=cfg):
                alert_actions.handler({'id': 'a', 'channel': 'file', 'message': 'first'}, {})
                alert_actions.handler({'id': 'b', 'channel': 'file', 'message': 'second'}, {})
            with open(log_path) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 2)


class TestAlertEmailChannel(unittest.TestCase):

    @patch.object(email_actions, 'send_email')
    def test_sends_email_alert_with_level_prefix(self, mock_send):
        result = alert_actions.handler(
            {'id': 'a', 'channel': 'email', 'message': 'server down', 'level': 'critical', 'to': 'admin@test.com'},
            {},
        )
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        self.assertIn('[CRITICAL]', args[1])  # subject
        self.assertIn('server down', args[2])  # body
        self.assertIn('sent', result['data'])

    @patch.object(email_actions, 'send_email')
    @patch.object(email_actions, '_load_config', return_value={
        'smtp_server': 's', 'smtp_port': 587, 'smtp_username': 'u',
        'smtp_password': 'p', 'from_email': 'self@test.com',
    })
    def test_falls_back_to_from_email_when_no_to(self, _, mock_send):
        alert_actions.handler(
            {'id': 'a', 'channel': 'email', 'message': 'test'},
            {},
        )
        args = mock_send.call_args[0]
        self.assertEqual(args[0], 'self@test.com')


class TestAlertWebhookChannel(unittest.TestCase):

    @patch('urllib.request.urlopen')
    def test_posts_json_to_webhook(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        cfg = {'channels': {'webhook': {'enabled': True, 'url': 'https://hooks.test.com/alert'}}}
        with patch.object(alert_actions, '_load_config', return_value=cfg):
            result = alert_actions.handler(
                {'id': 'a', 'channel': 'webhook', 'message': 'deploy failed', 'level': 'warning'},
                {},
            )
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(body['message'], 'deploy failed')
        self.assertEqual(body['level'], 'warning')
        self.assertIn('timestamp', body)


class TestAlertCommon(unittest.TestCase):

    def test_disabled_channel_returns_skipped(self):
        cfg = {'channels': {'file': {'enabled': False}}}
        with patch.object(alert_actions, '_load_config', return_value=cfg):
            result = alert_actions.handler(
                {'id': 'a', 'channel': 'file', 'message': 'test'},
                {},
            )
        self.assertIn('skipped', result['data'])

    def test_unknown_channel_returns_none(self):
        result = alert_actions.handler(
            {'id': 'a', 'channel': 'pigeon', 'message': 'test'},
            {},
        )
        self.assertIsNone(result)

    def test_missing_channel_returns_none(self):
        result = alert_actions.handler({'id': 'a', 'message': 'test'}, {})
        self.assertIsNone(result)

    def test_message_resolved_from_context_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'ctx.log')
            cfg = {'channels': {'file': {'enabled': True, 'path': log_path}}}
            with patch.object(alert_actions, '_load_config', return_value=cfg):
                alert_actions.handler(
                    {'id': 'a', 'channel': 'file', 'message': 'analysis'},
                    {'analysis': 'Found 3 new devices on network'},
                )
            with open(log_path) as f:
                content = f.read()
            self.assertIn('Found 3 new devices', content)

    def test_message_placeholder_resolution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, 'ph.log')
            cfg = {'channels': {'file': {'enabled': True, 'path': log_path}}}
            with patch.object(alert_actions, '_load_config', return_value=cfg):
                alert_actions.handler(
                    {'id': 'a', 'channel': 'file', 'message': 'Alert for {host}'},
                    {'host': 'server-42'},
                )
            with open(log_path) as f:
                content = f.read()
            self.assertIn('Alert for server-42', content)

    def test_id_preserved(self):
        cfg = {'channels': {'file': {'enabled': False}}}
        with patch.object(alert_actions, '_load_config', return_value=cfg):
            result = alert_actions.handler(
                {'id': 'my_alert', 'channel': 'file', 'message': 'test'},
                {},
            )
        self.assertEqual(result['id'], 'my_alert')


if __name__ == '__main__':
    unittest.main()
