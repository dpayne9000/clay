import unittest
from unittest.mock import patch

from clay.channels.telegram_bridge import TelegramBridge


def _message_update(user_id=1, chat_id=10, *, edited=False):
    message = {
        'message_id': 7,
        'from': {'id': user_id},
        'chat': {'id': chat_id, 'type': 'private'},
        'text': '/start',
    }
    return {'edited_message' if edited else 'message': message}


def _callback_update(user_id=1, chat_id=10):
    return {
        'callback_query': {
            'id': 'callback-1',
            'from': {'id': user_id},
            'message': {'chat': {'id': chat_id}},
            'data': 'launch',
        }
    }


class TelegramAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.bridge = TelegramBridge(
            '1:token', allowed_users={1}, allowed_chats={10}
        )
        self.commands = []
        self.messages = []
        self.actions = []
        self.bridge.command('start')(
            lambda _ctx, _args: self.commands.append('start')
        )
        self.bridge.on_message(
            lambda _ctx: self.messages.append('message')
        )
        self.bridge.on_action('launch')(
            lambda _action: self.actions.append('launch')
        )

    def test_bridge_itself_refuses_an_empty_authorization_policy(self):
        with self.assertRaisesRegex(ValueError, 'allowed user or chat ID'):
            TelegramBridge('1:token')

    def test_authorized_message_reaches_command_dispatch(self):
        self.bridge._dispatch(_message_update())
        self.assertEqual(['start'], self.commands)

    def test_unknown_user_cannot_dispatch_message_or_command(self):
        self.bridge._dispatch(_message_update(user_id=2))
        self.assertEqual([], self.commands)
        self.assertEqual([], self.messages)

    def test_unknown_chat_cannot_dispatch_edited_message(self):
        self.bridge._dispatch(_message_update(chat_id=20, edited=True))
        self.assertEqual([], self.commands)
        self.assertEqual([], self.messages)

    def test_authorized_callback_reaches_action_dispatch(self):
        with patch.object(self.bridge, 'answer_callback') as answer:
            self.bridge._dispatch(_callback_update())
        self.assertEqual(['launch'], self.actions)
        answer.assert_called_once_with('callback-1')

    def test_unknown_callback_user_is_rejected_before_dispatch(self):
        with patch.object(self.bridge, 'answer_callback') as answer:
            self.bridge._dispatch(_callback_update(user_id=2))
        self.assertEqual([], self.actions)
        answer.assert_called_once_with(
            'callback-1', text='Not authorized.', alert=True
        )


if __name__ == '__main__':
    unittest.main()
