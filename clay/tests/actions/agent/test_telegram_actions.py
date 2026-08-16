"""Unit tests for the telegram control channel.

The bot is a clayd front-end: it starts workflows through the daemon, relays
prompts to the chat, and hands replies back. Both the Telegram bridge and the
daemon client are injected, so every test here runs without a network or a
running daemon.
"""

import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from clay.actions.agent import telegram_actions as tg
from clay.run import events as run_events


class _FakeBridge:
    """Records registrations and outbound sends; can replay inbound events."""

    def __init__(self):
        self.commands = {}
        self.actions = {}
        self.message_handlers = []
        self.sent = []
        self.hints = []
        self.started = False
        self.stopped = False

    # registration API used by TelegramWorkflowBot._register
    def command(self, *names, description=None):
        def decorator(func):
            for name in names:
                self.commands[name] = func
            return func
        return decorator

    def on_action(self, *names):
        def decorator(func):
            for name in names:
                self.actions[name] = func
            return func
        return decorator

    def on_message(self, func):
        self.message_handlers.append(func)
        return func

    def send(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, str(text)))
        return {}

    def chat_action(self, chat_id, action='typing'):
        self.hints.append((chat_id, action))
        return True

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    # test helpers
    def press(self, callback_data, chat_id=99):
        return self.actions[callback_data](_FakeAction(chat_id))

    def say(self, text, chat_id=99):
        return self.message_handlers[0](_FakeMessage(self, chat_id, text))


class _FakeAction:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.user_id = 1
        self.data = {}


class _FakeMessage:
    def __init__(self, bridge, chat_id, text):
        self._bridge = bridge
        self.chat_id = chat_id
        self.text = text
        self.replies = []

    def reply(self, text, **kwargs):
        self.replies.append(str(text))
        self._bridge.sent.append((self.chat_id, str(text)))


class _FakeDaemonClient:
    """Context-manager daemon client. `calls` is shared across instances."""

    def __init__(self, script=None, calls=None):
        self.script = script if script is not None else {}
        self.calls = calls if calls is not None else []

    def __call__(self, *args, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def _record(self, name, *args):
        self.calls.append((name,) + args)
        result = self.script.get(name)
        if isinstance(result, Exception):
            raise result
        return result

    def start_workflow(self, filename, auto=False, daemon_mode=False):
        return self._record('start_workflow', filename, auto) or {
            'ok': True, 'id': 'wf-0001', 'status': 'running'}

    def stop_workflow(self, wf_id):
        return self._record('stop_workflow', wf_id) or {'ok': True}

    def send_input(self, wf_id, text):
        return self._record('send_input', wf_id, text) or {'ok': True}

    def tail(self, wf_id, lines=50):
        return self._record('tail', wf_id, lines) or []


class _FakeTyping:
    """Records the bot's start/stop calls instead of running a keepalive.

    The keepalive thread itself — its interval, its ceiling and its join — is
    covered in clay/tests/run/test_busy.py. What these tests are about is
    *when* the bot raises and drops the hint.
    """

    def __init__(self):
        self.calls = []

    def start(self, chat_id):
        self.calls.append(('start', chat_id))

    def stop(self):
        self.calls.append(('stop',))


class _FakeSubscriber:
    def __init__(self):
        self.callbacks = []
        self.started = False
        self.stopped = False

    def __call__(self, *args, **kwargs):
        return self

    def on_event(self, callback):
        self.callbacks.append(callback)

    def start(self, wf_id=None):
        self.started = True

    def stop(self):
        self.stopped = True

    def emit(self, event):
        for callback in self.callbacks:
            callback(event)


ENTRIES = [
    tg.MenuEntry('System editor', 'workflows/system/editor/main.json'),
    tg.MenuEntry('Traqr', 'workflows/templates/agents/celeb-tracker/main.json'),
]


def _build(script=None, start=True):
    """Build a bot wired to fakes.

    start=True mirrors real use: run_forever() brings the bridge and the event
    subscriber up before any menu press, and it is start() that registers the
    bot's event callback. Without it, emitted daemon events go nowhere.

    The batch interval is set past any test's lifetime so the drain thread
    never fires on its own. Relayed lines therefore sit in the buffer until a
    test flushes, or until the bot flushes for a prompt or a finish — which is
    the ordering these tests are here to pin down.
    """
    bridge = _FakeBridge()
    client = _FakeDaemonClient(script)
    subscriber = _FakeSubscriber()
    bot = tg.TelegramWorkflowBot(
        bridge, ENTRIES,
        client_factory=client,
        subscriber_factory=subscriber,
        batch_interval=3600,
        typing_hint=_FakeTyping(),
    )
    if start:
        bot.start()
    return bot, bridge, client, subscriber


class _BotTestCase(unittest.TestCase):
    """Keeps the chat-model fallthrough off the network."""

    def setUp(self):
        models = patch.object(tg.app_config, 'get_models', return_value={})
        fire = patch.object(tg.gopher, 'fire', return_value='model reply')
        models.start()
        fire.start()
        self.addCleanup(models.stop)
        self.addCleanup(fire.stop)


class ImportSafetyTest(unittest.TestCase):
    """The original bug: importing this module must never need the env var."""

    def test_handler_raises_clean_error_without_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as caught:
                tg.handler({'type': 'telegram', 'id': 'bot'}, {})
        self.assertIn('TELEGRAM_BOT_TOKEN', str(caught.exception))

    def test_blank_token_is_treated_as_missing(self):
        with patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': '   '}, clear=True):
            with self.assertRaises(ValueError):
                tg.handler({'type': 'telegram', 'id': 'bot'}, {})

    def test_handler_refuses_to_start_without_an_allowlist(self):
        with patch.dict(
            os.environ, {'TELEGRAM_BOT_TOKEN': '1:token'}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, 'non-empty TELEGRAM_ALLOWED'):
                tg.handler({'type': 'telegram', 'id': 'bot'}, {})

    def test_allowlists_accept_comma_whitespace_and_negative_chat_ids(self):
        users, chats = tg.telegram_allowlists({
            'TELEGRAM_ALLOWED_USERS': '11, 22  11',
            'TELEGRAM_ALLOWED_CHATS': '-100123, 44',
        })
        self.assertEqual({11, 22}, users)
        self.assertEqual({-100123, 44}, chats)

    def test_allowlists_reject_malformed_ids(self):
        with self.assertRaisesRegex(ValueError, 'TELEGRAM_ALLOWED_USERS'):
            tg.telegram_allowlists({'TELEGRAM_ALLOWED_USERS': '11, stranger'})

    def test_allowlists_reject_zero(self):
        with self.assertRaisesRegex(ValueError, 'invalid Telegram ID 0'):
            tg.telegram_allowlists({'TELEGRAM_ALLOWED_CHATS': '0'})

    @patch.object(tg, 'ensure_daemon')
    @patch.object(tg, '_authorize_daemon_over_telegram', return_value=True)
    @patch.object(tg, 'TelegramWorkflowBot')
    @patch.object(tg, 'TelegramBridge')
    def test_handler_passes_required_allowlists_to_bridge(
        self, bridge, bot_class, authorize, _ensure_daemon
    ):
        with patch.dict(os.environ, {
            'TELEGRAM_BOT_TOKEN': '1:token',
            'TELEGRAM_ALLOWED_USERS': '11',
            'TELEGRAM_ALLOWED_CHATS': '-10022',
        }, clear=True):
            tg.handler({'type': 'telegram', 'id': 'bot'}, {})

        bridge.assert_called_once_with(
            '1:token', allowed_users={11}, allowed_chats={-10022}
        )
        authorize.assert_called_once_with(bridge.return_value, {-10022})
        bot_class.assert_called_once_with(bridge.return_value, [])
        bot_class.return_value.run_forever.assert_called_once_with()

    def test_module_exposes_no_bot_at_import_time(self):
        self.assertFalse(hasattr(tg, 'bot'))


class DaemonPreflightTest(unittest.TestCase):

    def _check(self):
        return SimpleNamespace(
            path=Path('/project'),
            required=frozenset(tg.approval.GATES),
            missing=frozenset(tg.approval.GATES),
            allowed=False,
        )

    def test_telegram_approval_is_visible_before_preflight_completes(self):
        bridge = _FakeBridge()
        result = []
        with patch.object(tg.workspaces, 'daemon_access', return_value=self._check()), \
                patch.object(tg.paths, 'project_dir', return_value='/project'), \
                patch.object(tg, 'authorize_daemon_workspace') as authorize:
            thread = threading.Thread(
                target=lambda: result.append(
                    tg._authorize_daemon_over_telegram(bridge, {-100})))
            thread.start()
            deadline = time.time() + 1
            while not bridge.sent and time.time() < deadline:
                time.sleep(0.01)
            self.assertTrue(bridge.sent)
            self.assertIn('/project', bridge.sent[0][1])
            callback = next(name for name in bridge.actions
                            if name.startswith('daemon.access.yes.'))
            bridge.press(callback, chat_id=-100)
            thread.join(timeout=1)

        self.assertEqual([True], result)
        authorize.assert_called_once()

    def test_telegram_refusal_does_not_grant(self):
        bridge = _FakeBridge()
        result = []
        with patch.object(tg.workspaces, 'daemon_access', return_value=self._check()), \
                patch.object(tg.paths, 'project_dir', return_value='/project'), \
                patch.object(tg, 'authorize_daemon_workspace') as authorize:
            thread = threading.Thread(
                target=lambda: result.append(
                    tg._authorize_daemon_over_telegram(bridge, {99})))
            thread.start()
            deadline = time.time() + 1
            while not bridge.sent and time.time() < deadline:
                time.sleep(0.01)
            callback = next(name for name in bridge.actions
                            if name.startswith('daemon.access.no.'))
            bridge.press(callback)
            thread.join(timeout=1)

        self.assertEqual([False], result)
        authorize.assert_not_called()

    def test_existing_permissions_do_not_start_or_prompt_the_bridge(self):
        bridge = _FakeBridge()
        check = self._check()
        check.allowed = True
        check.missing = frozenset()
        with patch.object(tg.workspaces, 'daemon_access', return_value=check), \
                patch.object(tg.paths, 'project_dir', return_value='/project'):
            self.assertTrue(tg._authorize_daemon_over_telegram(bridge, {99}))
        self.assertFalse(bridge.sent)

    def test_missing_recipients_fails_closed_without_waiting(self):
        bridge = _FakeBridge()
        with patch.object(tg.workspaces, 'daemon_access', return_value=self._check()), \
                patch.object(tg.paths, 'project_dir', return_value='/project'):
            self.assertFalse(tg._authorize_daemon_over_telegram(bridge, set()))
        self.assertFalse(bridge.started)
        self.assertFalse(bridge.sent)

    def test_send_failure_stops_the_bridge(self):
        bridge = _FakeBridge()
        bridge.send = Mock(side_effect=RuntimeError('offline'))
        bridge.stop = Mock()
        with patch.object(tg.workspaces, 'daemon_access', return_value=self._check()), \
                patch.object(tg.paths, 'project_dir', return_value='/project'):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                tg._authorize_daemon_over_telegram(bridge, {99})
        bridge.stop.assert_called_once_with()

    def test_failed_grant_settles_the_wait_as_refused(self):
        bridge = _FakeBridge()
        result = []
        with patch.object(tg.workspaces, 'daemon_access', return_value=self._check()), \
                patch.object(tg.paths, 'project_dir', return_value='/project'), \
                patch.object(
                    tg, 'authorize_daemon_workspace',
                    side_effect=tg.DaemonPermissionDenied('write failed')):
            thread = threading.Thread(
                target=lambda: result.append(
                    tg._authorize_daemon_over_telegram(bridge, {99})))
            thread.start()
            deadline = time.time() + 1
            while not bridge.sent and time.time() < deadline:
                time.sleep(0.01)
            callback = next(name for name in bridge.actions
                            if name.startswith('daemon.access.yes.'))
            response = bridge.press(callback)
            thread.join(timeout=1)

        self.assertIn('Could not grant', response)
        self.assertEqual([False], result)

    def test_unexpected_grant_error_releases_the_wait_before_propagating(self):
        bridge = _FakeBridge()
        result = []
        with patch.object(tg.workspaces, 'daemon_access', return_value=self._check()), \
                patch.object(tg.paths, 'project_dir', return_value='/project'), \
                patch.object(tg, 'authorize_daemon_workspace',
                             side_effect=RuntimeError('bug')):
            thread = threading.Thread(
                target=lambda: result.append(
                    tg._authorize_daemon_over_telegram(bridge, {99})))
            thread.start()
            deadline = time.time() + 1
            while not bridge.sent and time.time() < deadline:
                time.sleep(0.01)
            callback = next(name for name in bridge.actions
                            if name.startswith('daemon.access.yes.'))
            with self.assertRaisesRegex(RuntimeError, 'bug'):
                bridge.press(callback)
            thread.join(timeout=1)
        self.assertEqual([False], result)


class MenuEntryTest(unittest.TestCase):

    def test_builds_entries_from_action_param(self):
        entries = tg.menu_entries([
            {'label': 'One', 'path': 'a.json'},
            {'label': 'Two', 'path': 'b.json'},
        ])
        self.assertEqual(entries, [
            tg.MenuEntry('One', 'a.json'), tg.MenuEntry('Two', 'b.json')])

    def test_missing_workflows_param_is_an_empty_menu(self):
        self.assertEqual(tg.menu_entries(None), [])

    def test_entry_without_path_raises(self):
        with self.assertRaises(ValueError):
            tg.menu_entries([{'label': 'One'}])

    def test_entry_without_label_raises(self):
        with self.assertRaises(ValueError):
            tg.menu_entries([{'path': 'a.json'}])

    def test_non_object_entry_raises(self):
        with self.assertRaises(ValueError):
            tg.menu_entries(['workflows/a.json'])


class PanelTest(unittest.TestCase):

    def test_panel_lists_one_button_per_workflow(self):
        bot, bridge, _, _ = _build()
        panel = bridge.commands['start'](None, '')
        rows = panel['menu']['inline_keyboard']
        labels = [button['text'] for row in rows for button in row]
        self.assertIn('System editor', labels)
        self.assertIn('Traqr', labels)

    def test_buttons_carry_index_callbacks_not_paths(self):
        """Telegram caps callback_data at 64 bytes."""
        bot, bridge, _, _ = _build()
        panel = bridge.commands['start'](None, '')
        rows = panel['menu']['inline_keyboard']
        data = [button['callback_data'] for row in rows for button in row]
        self.assertIn('wf:0', data)
        self.assertIn('wf:1', data)
        for value in data:
            self.assertLessEqual(len(value.encode('utf-8')), 64)

    def test_empty_menu_explains_itself(self):
        bridge = _FakeBridge()
        tg.TelegramWorkflowBot(
            bridge, [],
            client_factory=_FakeDaemonClient(),
            subscriber_factory=_FakeSubscriber(),
        )
        panel = bridge.commands['start'](None, '')
        self.assertIn('No workflows configured', panel['text'])
        self.assertNotIn('menu', panel)


class LaunchTest(unittest.TestCase):

    def test_menu_press_starts_workflow_through_daemon(self):
        bot, bridge, client, _ = _build()
        result = bridge.press('wf:0')

        self.assertIn(
            ('start_workflow', 'workflows/system/editor/main.json', False),
            client.calls)
        self.assertIn('System editor', result)

    def test_workflow_runs_non_auto_so_it_can_prompt(self):
        bot, bridge, client, _ = _build()
        bridge.press('wf:0')
        call = next(c for c in client.calls if c[0] == 'start_workflow')
        self.assertFalse(call[2], 'workflow must start non-auto to ask questions')

    def test_second_launch_is_rejected_while_one_runs(self):
        bot, bridge, client, _ = _build()
        bridge.press('wf:0')
        result = bridge.press('wf:1')

        self.assertIn('already running', result)
        starts = [c for c in client.calls if c[0] == 'start_workflow']
        self.assertEqual(len(starts), 1)

    def test_launch_reports_daemon_failure(self):
        bot, bridge, _, _ = _build(
            script={'start_workflow': ConnectionRefusedError('no socket')})
        result = bridge.press('wf:0')
        self.assertIn('Could not reach clayd', result)

    def test_failed_launch_leaves_no_active_run(self):
        bot, bridge, _, _ = _build(script={'start_workflow': {'ok': False,
                                                              'error': 'boom'}})
        bridge.press('wf:0')
        self.assertIn('Idle', bridge.commands['status'](None, ''))


class PromptRelayTest(_BotTestCase):

    def _running_bot(self, script=None):
        bot, bridge, client, subscriber = _build(script)
        bridge.press('wf:0')
        client.calls.clear()
        return bot, bridge, client, subscriber

    def test_prompt_event_is_relayed_to_the_chat(self):
        bot, bridge, _, subscriber = self._running_bot()
        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Which branch?'})

        chat_id, text = bridge.sent[-1]
        self.assertEqual(chat_id, 99)
        self.assertIn('Which branch?', text)

    def test_reply_is_sent_back_as_workflow_input(self):
        bot, bridge, client, subscriber = self._running_bot()
        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Which branch?'})
        bridge.say('main')

        self.assertIn(('send_input', 'wf-0001', 'main'), client.calls)

    def test_events_for_other_workflows_are_ignored(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        subscriber.emit({'event': 'prompt', 'id': 'wf-9999',
                         'prompt_id': 'q1', 'text': 'not ours'})
        self.assertEqual(len(bridge.sent), before)

    def test_chat_falls_through_to_the_model_when_nothing_is_pending(self):
        bot, bridge, client, _ = self._running_bot()
        with patch.object(tg.TelegramWorkflowBot, '_chat',
                          return_value='model reply') as chat:
            bridge.say('hello there')

        chat.assert_called_once_with('hello there')
        self.assertNotIn('send_input', [c[0] for c in client.calls])

    def test_answering_clears_pending_so_next_message_is_chat(self):
        bot, bridge, client, subscriber = self._running_bot()
        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Which branch?'})
        bridge.say('main')

        with patch.object(tg.TelegramWorkflowBot, '_chat',
                          return_value='model reply') as chat:
            bridge.say('and now something else')
        chat.assert_called_once()


class FinishTest(_BotTestCase):

    def _running_bot(self, script=None):
        bot, bridge, client, subscriber = _build(script)
        bridge.press('wf:0')
        return bot, bridge, client, subscriber

    def test_finish_reports_status_without_tailing_stdout(self):
        """The engine no longer prints — the summary comes from what was
        relayed during the run, not from clayd's stdout capture."""
        bot, bridge, client, subscriber = self._running_bot()
        subscriber.emit({'event': 'workflow', 'id': 'wf-0001',
                         'data': {'type': 'action.complete',
                                  'action_type': 'scramda2', 'id': 'a',
                                  'data': 'the answer'}})
        subscriber.emit({'event': 'finished', 'id': 'wf-0001',
                         'status': 'done', 'exit_code': 0})

        _, text = bridge.sent[-1]
        self.assertIn('System editor', text)
        self.assertIn('done', text)
        self.assertNotIn('(no output)', text)
        self.assertNotIn('tail', [c[0] for c in client.calls])

    def test_finish_with_nothing_relayed_says_so(self):
        bot, bridge, _, subscriber = self._running_bot()
        subscriber.emit({'event': 'finished', 'id': 'wf-0001',
                         'status': 'done', 'exit_code': 0})
        _, text = bridge.sent[-1]
        self.assertIn('(no output)', text)

    def test_nonzero_exit_is_reported(self):
        bot, bridge, _, subscriber = self._running_bot()
        subscriber.emit({'event': 'finished', 'id': 'wf-0001',
                         'status': 'error', 'exit_code': 2})
        _, text = bridge.sent[-1]
        self.assertIn('exit 2', text)

    def test_finish_frees_the_slot_for_the_next_workflow(self):
        bot, bridge, client, subscriber = self._running_bot()
        subscriber.emit({'event': 'finished', 'id': 'wf-0001',
                         'status': 'done', 'exit_code': 0})
        result = bridge.press('wf:1')

        self.assertNotIn('already running', result)
        starts = [c for c in client.calls if c[0] == 'start_workflow']
        self.assertEqual(len(starts), 2)


class ContentRelayTest(_BotTestCase):
    """Telegram relays the default CLI's concise content policy."""

    def _running_bot(self, script=None):
        bot, bridge, client, subscriber = _build(script)
        bridge.press('wf:0')
        client.calls.clear()
        return bot, bridge, client, subscriber

    def _emit_workflow(self, bot, subscriber, data, wf_id='wf-0001'):
        subscriber.emit({'event': 'workflow', 'id': wf_id, 'data': data})
        bot._batcher.flush()

    def test_scramda2_answer_reaches_the_chat(self):
        bot, bridge, _, subscriber = self._running_bot()
        self._emit_workflow(bot, subscriber, {
            'type': 'action.complete', 'action_type': 'scramda2',
            'id': 'plan', 'data': 'the model answer'})

        chat_id, text = bridge.sent[-1]
        self.assertEqual(chat_id, 99)
        self.assertEqual(text, 'the model answer')

    def test_writefile_result_is_not_relayed(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._emit_workflow(bot, subscriber, {
            'type': 'action.complete', 'action_type': 'writeFile',
            'id': 'save', 'data': 'file body'})
        self.assertEqual(len(bridge.sent), before)

    def test_action_start_is_hidden_like_non_verbose_cli(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._emit_workflow(bot, subscriber, {
            'type': 'action.start', 'action_type': 'applyFileWrites',
            'id': 'files_written'})
        self.assertEqual(len(bridge.sent), before)

    def test_model_prompt_is_hidden_like_non_verbose_cli(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._emit_workflow(bot, subscriber, {
            'type': 'action.output', 'action_type': 'scramda2', 'id': 'reply',
            'kind': 'prompt', 'label': 'orchestrator',
            'text': 'Write the flapping bird'})
        self.assertEqual(len(bridge.sent), before)

    def test_step_header_is_hidden_like_non_verbose_cli(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._emit_workflow(bot, subscriber,
                            {'type': 'step.start', 'step': 'converse'})
        self.assertEqual(len(bridge.sent), before)

    def test_errors_reach_the_chat(self):
        bot, bridge, _, subscriber = self._running_bot()
        self._emit_workflow(bot, subscriber, {
            'type': 'action.error', 'action_type': 'shell',
            'id': 'x', 'message': 'command failed'})
        self.assertIn('command failed', bridge.sent[-1][1])

        self._emit_workflow(bot, subscriber, {
            'type': 'run.error', 'message': 'file not found'})
        self.assertIn('file not found', bridge.sent[-1][1])

    def test_info_log_is_hidden_like_non_verbose_cli(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._emit_workflow(bot, subscriber, {
            'type': 'log', 'level': 'INFO', 'message': 'a plain note'})
        self.assertEqual(len(bridge.sent), before)

    def test_file_name_and_command_output_reach_the_chat(self):
        bot, bridge, _, subscriber = self._running_bot()
        self._emit_workflow(bot, subscriber, {
            'type': 'action.output', 'action_type': 'applyFileWrites',
            'id': 'files_written', 'kind': 'file',
            'label': 'flap.py written (1 lines)', 'text': 'print("flap")'})
        self.assertIn('flap.py written', bridge.sent[-1][1])
        self.assertNotIn('print("flap")', bridge.sent[-1][1])

        self._emit_workflow(bot, subscriber, {
            'type': 'action.output', 'action_type': 'runReplyCommands',
            'id': 'command_output', 'kind': 'command',
            'label': '$ python3 flap.py', 'text': 'flap'})
        self.assertIn('$ python3 flap.py', bridge.sent[-1][1])

    def test_warn_log_is_labelled(self):
        bot, bridge, _, subscriber = self._running_bot()
        self._emit_workflow(bot, subscriber, {
            'type': 'log', 'level': 'WARN', 'message': 'low disk'})
        text = bridge.sent[-1][1]
        self.assertIn('WARN', text)
        self.assertIn('low disk', text)

    def test_lines_are_batched_into_one_message(self):
        """Multiple visible results become one Telegram message."""
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        subscriber.emit({'event': 'workflow', 'id': 'wf-0001',
                         'data': {'type': 'action.complete',
                                  'action_type': 'scramda2', 'id': 'one',
                                  'data': 'first answer'}})
        subscriber.emit({'event': 'workflow', 'id': 'wf-0001',
                         'data': {'type': 'log', 'level': 'WARN',
                                  'message': 'check this'}})
        self.assertEqual(len(bridge.sent), before,
                         'nothing should go out before the stream goes quiet')

        bot._batcher.flush()
        self.assertEqual(len(bridge.sent), before + 1)
        text = bridge.sent[-1][1]
        self.assertIn('first answer', text)
        self.assertIn('check this', text)

    def test_buffered_lines_land_before_a_prompt(self):
        """Answering a question means having read what led to it."""
        bot, bridge, _, subscriber = self._running_bot()
        subscriber.emit({'event': 'workflow', 'id': 'wf-0001',
                         'data': {'type': 'action.complete',
                                  'action_type': 'scramda2', 'id': 'reply',
                                  'data': 'result before question'}})
        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Anything else?'})

        self.assertIn('result before question', bridge.sent[-2][1])
        self.assertIn('Anything else?', bridge.sent[-1][1])

    def test_other_workflows_content_is_ignored(self):
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._emit_workflow(bot, subscriber, {
            'type': 'action.complete', 'action_type': 'scramda2',
            'id': 'plan', 'data': 'not ours'}, wf_id='wf-9999')
        self.assertEqual(len(bridge.sent), before)

    # ── typing hint ──────────────────────────────────────────────────────

    def _busy(self, subscriber, active, preview=''):
        subscriber.emit({'event': 'workflow', 'id': 'wf-0001',
                         'data': {'type': run_events.BUSY, 'active': active,
                                  'action_type': 'scramda2',
                                  'preview': preview}})

    def test_busy_raises_and_drops_the_typing_hint(self):
        bot, _, _, subscriber = self._running_bot()
        bot._typing.calls.clear()
        self._busy(subscriber, True, 'summarise the workspace')
        self._busy(subscriber, False)
        self.assertEqual(bot._typing.calls, [('start', 99), ('stop',)])

    def test_busy_sends_no_chat_line(self):
        """A 'working…' line per action would be the noisiest thing in the
        thread, and it would still be there after the wait ended."""
        bot, bridge, _, subscriber = self._running_bot()
        before = len(bridge.sent)
        self._busy(subscriber, True, 'summarise')
        bot._batcher.flush()
        self.assertEqual(len(bridge.sent), before)

    def test_queued_lines_go_out_before_the_hint(self):
        """A hint in front of the lines explaining the work reads as a stall,
        and Telegram clears the hint on the next message anyway."""
        bot, bridge, _, subscriber = self._running_bot()
        subscriber.emit({'event': 'workflow', 'id': 'wf-0001',
                         'data': {'type': 'log', 'level': 'WARN',
                                  'message': 'reading the workspace'}})
        bot._typing.calls.clear()
        before = len(bridge.sent)
        self._busy(subscriber, True, 'summarise')

        self.assertEqual(len(bridge.sent), before + 1)
        self.assertIn('reading the workspace', bridge.sent[-1][1])
        self.assertEqual(bot._typing.calls, [('start', 99)])

    def test_a_prompt_drops_the_hint(self):
        bot, _, _, subscriber = self._running_bot()
        self._busy(subscriber, True, 'summarise')
        bot._typing.calls.clear()
        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Anything else?'})
        self.assertIn(('stop',), bot._typing.calls)

    def test_a_finished_run_drops_the_hint(self):
        """A run that crashed mid-action never sent its own active=False."""
        bot, _, _, subscriber = self._running_bot()
        self._busy(subscriber, True, 'summarise')
        bot._typing.calls.clear()
        subscriber.emit({'event': 'finished', 'id': 'wf-0001',
                         'status': 'error', 'exit_code': 1})
        self.assertIn(('stop',), bot._typing.calls)


class ChatTypingTest(_BotTestCase):
    """A conversational turn is a model call with no workflow behind it.

    Nothing emits EVT.BUSY for it, so _on_message raises the same hint itself —
    otherwise the one wait the user sits through most often is the one with no
    indicator at all.
    """

    def test_a_chat_turn_raises_and_drops_the_hint(self):
        bot, bridge, _, _ = _build()
        bridge.say('hello there')
        self.assertEqual(bot._typing.calls, [('start', 99), ('stop',)])

    def test_the_hint_is_dropped_before_the_reply_is_sent(self):
        """Telegram clears the hint on the next message anyway — leaving it up
        past the reply would only leave a thread that looks still busy."""
        bot, bridge, _, _ = _build()
        at_stop = []
        bot._typing.stop = lambda: at_stop.append(len(bridge.sent))
        bridge.say('hello there')

        self.assertEqual(len(at_stop), 1, 'the hint was never dropped')
        self.assertEqual(at_stop[0], len(bridge.sent) - 1,
                         'the reply was sent before the hint was dropped')

    def test_a_failing_model_call_still_drops_the_hint(self):
        """Without the finally, one timeout types into that chat for ten
        minutes."""
        bot, bridge, _, _ = _build()
        with patch.object(tg.gopher, 'fire', side_effect=RuntimeError('no model')):
            with self.assertRaises(RuntimeError):
                bridge.say('hello there')
        self.assertEqual(bot._typing.calls[-1], ('stop',))

    def test_answering_a_prompt_raises_no_hint(self):
        """That path posts the answer to clayd and returns — the wait that
        follows belongs to the workflow, which raises its own busy."""
        bot, bridge, _, subscriber = _build()
        bridge.press('wf:0')
        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Which branch?'})
        bot._typing.calls.clear()
        bridge.say('main')
        self.assertEqual(bot._typing.calls, [])

    def test_the_hint_goes_to_the_chat_that_spoke(self):
        bot, bridge, _, _ = _build()
        bridge.say('hello there', chat_id=1234)
        self.assertIn(('start', 1234), bot._typing.calls)


class CancelAndStatusTest(_BotTestCase):

    def test_cancel_stops_the_running_workflow(self):
        bot, bridge, client, _ = _build()
        bridge.press('wf:0')
        result = bridge.press('app.cancel')

        self.assertIn(('stop_workflow', 'wf-0001'), client.calls)
        self.assertIn('Stopping', result)

    def test_cancel_with_nothing_running(self):
        bot, bridge, client, _ = _build()
        result = bridge.press('app.cancel')
        self.assertIn('Nothing is running', result)
        self.assertEqual(client.calls, [])

    def test_status_reports_idle_then_running_then_waiting(self):
        bot, bridge, _, subscriber = _build()
        self.assertIn('Idle', bridge.press('app.status'))

        bridge.press('wf:0')
        self.assertIn('running', bridge.press('app.status'))

        subscriber.emit({'event': 'prompt', 'id': 'wf-0001',
                         'prompt_id': 'q1', 'text': 'Which branch?'})
        self.assertIn('waiting', bridge.press('app.status'))


class LifecycleTest(unittest.TestCase):

    def test_nothing_is_live_before_start(self):
        bot, bridge, _, subscriber = _build(start=False)
        self.assertFalse(bridge.started)
        self.assertFalse(subscriber.started)

    def test_start_brings_up_bridge_and_subscriber(self):
        bot, bridge, _, subscriber = _build(start=False)
        bot.start()
        self.assertTrue(bridge.started)
        self.assertTrue(subscriber.started)

    def test_start_registers_the_event_callback(self):
        """Without this, daemon prompts never reach the chat."""
        bot, _, _, subscriber = _build(start=False)
        bot.start()
        self.assertEqual(subscriber.callbacks, [bot._on_event])

    def test_stop_shuts_both_down(self):
        bot, bridge, _, subscriber = _build(start=False)
        bot.start()
        bot.stop()
        self.assertTrue(bridge.stopped)
        self.assertTrue(subscriber.stopped)


if __name__ == '__main__':
    unittest.main()
