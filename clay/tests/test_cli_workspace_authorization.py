"""CLI workspace authorization tests for attended and daemon runs."""

import argparse
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from clay import cli
from clay.run import workspaces


def _args(**overrides):
    base = dict(theme=None, plain_stdout=False, daemon=False, auto=False)
    base.update(overrides)
    return argparse.Namespace(**base)


class RunPreflightAuthorizationTest(unittest.TestCase):
    """Authorize unattended runs before setup begins."""

    def test_a_plain_attended_run_never_asks_about_the_directory(self):
        # Attended runs authorize directories only when an action needs one.
        with patch('clay.cli._authorize_project_dir',
                   side_effect=AssertionError('should not be called')), \
                patch('clay.cli._resolve_workflow_arg', return_value='/wf.json'), \
                patch('clay.cli._attach_terminal', return_value=None), \
                patch('clay.cli._start_event_socket'), \
                patch('clay.cli._load_config', return_value={}), \
                patch('clay.cli.engine.run') as run, \
                patch('clay.run.logger.stop_socket_bridge'):
            result = cli.run(_args())
        self.assertIsNone(result)
        run.assert_called_once()

    def test_auto_refused_stops_before_anything_is_set_up(self):
        with patch('clay.cli._authorize_project_dir', return_value=False), \
                patch('clay.cli._resolve_workflow_arg', return_value='/wf.json'), \
                patch('clay.cli._attach_terminal') as attach, \
                patch('clay.cli._start_event_socket') as socket_start, \
                patch('clay.cli.engine.run') as run:
            result = cli.run(_args(auto=True))
        self.assertEqual(1, result)
        attach.assert_not_called()
        socket_start.assert_not_called()
        run.assert_not_called()

    def test_auto_approved_runs_normally(self):
        with patch('clay.cli._authorize_project_dir', return_value=True), \
                patch('clay.cli._resolve_workflow_arg', return_value='/wf.json'), \
                patch('clay.cli._attach_terminal', return_value=None), \
                patch('clay.cli._start_event_socket'), \
                patch('clay.cli._load_config', return_value={}), \
                patch('clay.cli.engine.run') as run, \
                patch('clay.run.logger.stop_socket_bridge'):
            result = cli.run(_args(auto=True))
        self.assertIsNone(result)
        run.assert_called_once()

    def test_the_daemon_flag_alone_triggers_the_same_check(self):
        # --daemon needs persisted read/write/command authority, not merely a
        # directory grant, before the run becomes unattended.
        with patch('clay.cli._authorize_daemon_project_dir', return_value=False) as authorize, \
                patch('clay.cli._resolve_workflow_arg', return_value='/wf.json'), \
                patch('clay.cli.engine.run') as run:
            result = cli.run(_args(daemon=True))
        self.assertEqual(1, result)
        authorize.assert_called_once()
        run.assert_not_called()


class AuthorizeProjectDirTest(unittest.TestCase):
    """Translate WorkspaceDenied into a CLI result."""

    def test_an_approved_directory_returns_true_and_prints_nothing(self):
        with patch('clay.lib.paths.project_dir', return_value='/approved'), \
                patch('clay.run.workspaces.authorize') as authorize, \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertTrue(cli._authorize_project_dir())
        authorize.assert_called_once_with('/approved')
        self.assertEqual('', stderr.getvalue())

    def test_a_denied_directory_prints_the_reason_and_returns_false(self):
        with patch('clay.lib.paths.project_dir', return_value='/nope'), \
                patch('clay.run.workspaces.authorize',
                     side_effect=workspaces.WorkspaceDenied('/nope is not approved')), \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            self.assertFalse(cli._authorize_project_dir())
        self.assertIn('/nope is not approved', stderr.getvalue())


class EnsureDaemonPermissionOrderTest(unittest.TestCase):

    def test_terminal_question_names_the_directory_being_enabled(self):
        check = SimpleNamespace(
            path=Path('/project/client'),
            missing=frozenset({'fileReads', 'fileWrites', 'commands'}),
        )
        with patch('builtins.input', return_value='n') as prompt:
            self.assertFalse(cli._terminal_daemon_permission_prompt(check))
        text = prompt.call_args.args[0]
        self.assertIn('Grant these permissions for /project/client', text)
        self.assertIn('/workspaces.json', text)

    def test_terminal_question_accepts_yes_and_fails_closed_on_eof(self):
        check = SimpleNamespace(
            path=Path('/project/client'),
            missing=frozenset({'commands'}),
        )
        with patch('builtins.input', return_value=' YES '):
            self.assertTrue(cli._terminal_daemon_permission_prompt(check))
        with patch('builtins.input', side_effect=EOFError):
            self.assertFalse(cli._terminal_daemon_permission_prompt(check))

    def test_permissions_are_verified_before_daemon_spawn(self):
        order = []
        with patch('clay.lib.paths.project_dir', return_value='/project'), \
                patch('clay.daemon.client.authorize_daemon_workspace',
                      side_effect=lambda *args: order.append('authorize')), \
                patch('clay.daemon.client.ensure_daemon',
                      side_effect=lambda: order.append('spawn') or True):
            self.assertTrue(cli._ensure_daemon(lambda check: True))
        self.assertEqual(['authorize', 'spawn'], order)

    def test_refusal_never_spawns_clayd(self):
        from clay.daemon.client import DaemonPermissionDenied
        with patch('clay.lib.paths.project_dir', return_value='/project'), \
                patch('clay.daemon.client.authorize_daemon_workspace',
                      side_effect=DaemonPermissionDenied('refused')), \
                patch('clay.daemon.client.ensure_daemon') as spawn, \
                patch('sys.stderr', new_callable=io.StringIO):
            self.assertFalse(cli._ensure_daemon(lambda check: False))
        spawn.assert_not_called()


class DaemonRunSubcommandWorkspaceDenialTest(unittest.TestCase):
    """Report daemon workspace denial instead of crashing."""

    def test_a_denied_directory_is_reported_and_exits_1(self):
        fake_client = MagicMock()
        fake_client.__enter__.return_value = fake_client
        fake_client.__exit__.return_value = False  # must not swallow the raise
        fake_client.start_workflow.side_effect = workspaces.WorkspaceDenied(
            '/nope is not approved')

        args = argparse.Namespace(daemon_sub='run', workflow_name=['wf'],
                                  file=None, auto=False, daemon_mode=True)
        with patch('clay.cli._resolve_workflow_arg', return_value='/wf.json'), \
                patch('clay.cli._ensure_daemon'), \
                patch('clay.daemon.client.DaemonClient', return_value=fake_client), \
                patch('sys.stderr', new_callable=io.StringIO) as stderr:
            result = cli.daemon_cmd(args)
        self.assertEqual(1, result)
        self.assertIn('/nope is not approved', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
