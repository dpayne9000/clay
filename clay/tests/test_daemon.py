"""Tests for the clayd daemon — multi-process management, event streaming, stop/kill."""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

# Ensure clay is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from clay.daemon.server import ClayDaemon, ClientHandler, SOCKET_PATH
from clay.daemon.client import DaemonClient, EventSubscriber
from clay.daemon import protocol, client as daemon_client
from clay.lib import config, paths


def _test_socket_path():
    # Never let the daemon chmod the shared temp root.
    runtime_dir = os.path.join(tempfile.gettempdir(), f'clayd-test-{os.getpid()}')
    os.makedirs(runtime_dir, mode=0o700, exist_ok=True)
    return os.path.join(runtime_dir, 'clayd.sock')


class TestProtocol(unittest.TestCase):
    def test_encode_decode(self):
        msg = {'cmd': 'ping', 'data': [1, 2]}
        encoded = protocol.encode(msg)
        self.assertIsInstance(encoded, bytes)
        self.assertTrue(encoded.endswith(b'\n'))
        decoded = protocol.decode_line(encoded.decode())
        self.assertEqual(decoded, msg)

    def test_decode_empty(self):
        self.assertIsNone(protocol.decode_line(''))
        self.assertIsNone(protocol.decode_line('   '))

    def test_decode_bad_json(self):
        self.assertIsNone(protocol.decode_line('not json'))


class TestProjectDirValidation(unittest.TestCase):
    """ClientHandler._project_dir — a pure (msg) -> (path, error) function."""

    def test_a_real_directory_is_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(ClientHandler._project_dir({'project_dir': d}),
                             (d, None))

    def _isolated_clay_home(self):
        """A $CLAY_HOME of this test's own, so the default lands inside it."""
        home = tempfile.mkdtemp(prefix='clay-home-')
        self.addCleanup(shutil.rmtree, home, True)
        patcher = mock.patch.object(config, 'clay_dir', home)
        patcher.start()
        self.addCleanup(patcher.stop)
        return home

    def test_missing_falls_back_to_the_clay_workspaces_dir(self):
        """Not required — but the fallback is never the daemon's own cwd."""
        home = self._isolated_clay_home()
        path, error = ClientHandler._project_dir({})
        self.assertIsNone(error)
        self.assertEqual(path, os.path.join(home, 'workspaces'))
        self.assertTrue(os.path.isdir(path), 'the default is created')

    def test_blank_falls_back_the_same_way(self):
        home = self._isolated_clay_home()
        path, error = ClientHandler._project_dir({'project_dir': '   '})
        self.assertIsNone(error)
        self.assertEqual(path, os.path.join(home, 'workspaces'))

    def test_an_uncreatable_default_is_an_error_not_a_crash(self):
        blocker = tempfile.NamedTemporaryFile(delete=False)
        blocker.close()
        self.addCleanup(os.unlink, blocker.name)
        # clay_dir is a *file*, so makedirs under it cannot succeed.
        with mock.patch.object(config, 'clay_dir', blocker.name):
            path, error = ClientHandler._project_dir({})
        self.assertIsNone(path)
        self.assertIn('could not be created', error)

    def test_a_path_that_is_not_a_directory_is_refused(self):
        with tempfile.NamedTemporaryFile() as f:
            path, error = ClientHandler._project_dir({'project_dir': f.name})
        self.assertIsNone(path)
        self.assertIn('not a directory', error)

    def test_server_rechecks_unattended_workspace_authority(self):
        check = mock.Mock(allowed=False, path='/project',
                          missing={'commands', 'fileWrites'})
        with mock.patch('clay.run.workspaces.daemon_access', return_value=check):
            error = ClientHandler._daemon_access_error(
                '/project', auto=True)
        self.assertIn('/project', error)
        self.assertIn('commands', error)

    def test_server_does_not_require_advance_access_for_attended_work(self):
        with mock.patch('clay.run.workspaces.daemon_access') as access:
            error = ClientHandler._daemon_access_error(
                '/project', auto=False, daemon_mode=False)
        self.assertIsNone(error)
        access.assert_not_called()


class TestCallerProjectDir(unittest.TestCase):
    """The client sends its own project directory, not its cwd."""

    def test_reports_the_project_dir_not_the_cwd(self):
        with tempfile.TemporaryDirectory() as project:
            with mock.patch.object(paths, 'project_dir', return_value=project):
                self.assertEqual(daemon_client._caller_project_dir(), project)

    def test_both_start_calls_carry_it(self):
        c = DaemonClient.__new__(DaemonClient)
        sent = []
        with mock.patch.object(DaemonClient, '_request',
                               side_effect=lambda msg: sent.append(msg) or {}):
            with mock.patch.object(daemon_client, '_caller_project_dir',
                                   return_value='/somewhere'), \
                    mock.patch.object(daemon_client, 'require_daemon_workspace'):
                c.start_workflow('wf.json')
                c.start_workflow_json({'workflow': {}})
        self.assertEqual([m['project_dir'] for m in sent],
                         ['/somewhere', '/somewhere'])


class TestStartWorkflowPreflightAuthorization(unittest.TestCase):
    """Both daemon submission protocols fail closed on missing authority."""

    def _client(self):
        return DaemonClient.__new__(DaemonClient)

    def test_neither_flag_never_asks_about_the_directory(self):
        with mock.patch.object(daemon_client, '_caller_project_dir',
                               return_value='/somewhere'), \
                mock.patch.object(daemon_client, 'require_daemon_workspace') as authorize, \
                mock.patch.object(DaemonClient, '_request', return_value={}):
            self._client().start_workflow('wf.json')
        authorize.assert_not_called()

    def test_auto_requires_advance_access_before_sending_the_request(self):
        with mock.patch.object(daemon_client, '_caller_project_dir',
                               return_value='/somewhere'), \
                mock.patch.object(daemon_client, 'require_daemon_workspace') as authorize, \
                mock.patch.object(DaemonClient, '_request', return_value={}):
            self._client().start_workflow('wf.json', auto=True)
        authorize.assert_called_once_with('/somewhere')

    def test_daemon_mode_authorizes_even_without_auto(self):
        with mock.patch.object(daemon_client, '_caller_project_dir',
                               return_value='/somewhere'), \
                mock.patch.object(daemon_client, 'require_daemon_workspace') as authorize, \
                mock.patch.object(DaemonClient, '_request', return_value={}):
            self._client().start_workflow('wf.json', daemon_mode=True)
        authorize.assert_called_once_with('/somewhere')

    def test_a_denial_propagates_and_never_reaches_the_socket(self):
        with mock.patch.object(daemon_client, '_caller_project_dir',
                               return_value='/somewhere'), \
                mock.patch.object(
                    daemon_client, 'require_daemon_workspace',
                    side_effect=daemon_client.DaemonPermissionDenied('nope')), \
                mock.patch.object(DaemonClient, '_request') as request:
            c = DaemonClient.__new__(DaemonClient)
            with self.assertRaises(daemon_client.DaemonPermissionDenied):
                c.start_workflow('wf.json', auto=True)
        request.assert_not_called()

    def test_start_workflow_json_has_the_same_fail_closed_check(self):
        with mock.patch.object(daemon_client, '_caller_project_dir',
                               return_value='/somewhere'), \
                mock.patch.object(daemon_client, 'require_daemon_workspace') as authorize, \
                mock.patch.object(DaemonClient, '_request', return_value={}):
            self._client().start_workflow_json({'workflow': {}}, auto=True)
        authorize.assert_called_once_with('/somewhere')


class TestRequireDaemonWorkspace(unittest.TestCase):

    def test_allowed_policy_returns_the_resolved_check(self):
        check = mock.Mock(allowed=True, path=Path('/project'),
                          missing=frozenset())
        with mock.patch('clay.run.workspaces.daemon_access',
                        return_value=check) as access:
            result = daemon_client.require_daemon_workspace(
                '/project', {'commands'})
        self.assertIs(result, check)
        access.assert_called_once_with('/project', {'commands'})

    def test_denied_policy_names_the_directory_and_missing_permissions(self):
        check = mock.Mock(
            allowed=False,
            path=Path('/project'),
            missing=frozenset({'fileWrites', 'commands'}),
        )
        with mock.patch('clay.run.workspaces.daemon_access', return_value=check):
            with self.assertRaisesRegex(
                    daemon_client.DaemonPermissionDenied,
                    r'/project.*commands, fileWrites'):
                daemon_client.require_daemon_workspace('/project')


class TestAuthorizeDaemonWorkspace(unittest.TestCase):
    """The visible answer is persisted and verified before daemon startup."""

    def setUp(self):
        from clay.run import approval, workspaces
        self.workspaces = workspaces
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.realpath(self.tmp.name)
        register = mock.patch.object(
            workspaces, 'REGISTER_PATH', os.path.join(self.project, 'workspaces.json'))
        register.start()
        self.addCleanup(register.stop)
        approval.reset()
        workspaces.reset_session()
        self.addCleanup(approval.reset)
        self.addCleanup(workspaces.reset_session)

    def test_sufficient_grant_never_prompts(self):
        self.workspaces.grant_daemon_access(self.project)
        check = daemon_client.authorize_daemon_workspace(
            self.project, lambda request: self.fail('should not prompt'))
        self.assertTrue(check.allowed)

    def test_approval_is_persisted_and_verified(self):
        seen = []
        check = daemon_client.authorize_daemon_workspace(
            self.project, lambda request: seen.append(request) or True)
        self.assertEqual(1, len(seen))
        self.assertTrue(check.allowed)
        self.assertTrue(self.workspaces.daemon_access(self.project).allowed)

    def test_refusal_changes_nothing(self):
        with self.assertRaises(daemon_client.DaemonPermissionDenied):
            daemon_client.authorize_daemon_workspace(
                self.project, lambda request: False)
        self.assertIsNone(self.workspaces.find(self.project))

    def test_failed_post_write_verification_is_reported(self):
        initial = mock.Mock(allowed=False, path=Path(self.project),
                            required=frozenset({'commands'}),
                            missing=frozenset({'commands'}))
        failed = mock.Mock(allowed=False, path=Path(self.project),
                           required=frozenset({'commands'}),
                           missing=frozenset({'commands'}))
        with mock.patch.object(self.workspaces, 'daemon_access',
                               side_effect=[initial, failed]), \
                mock.patch.object(self.workspaces, 'grant_daemon_access') as grant:
            with self.assertRaisesRegex(
                    daemon_client.DaemonPermissionDenied,
                    'still lacks daemon permissions: commands'):
                daemon_client.authorize_daemon_workspace(
                    self.project, lambda request: True,
                    required={'commands'})
        grant.assert_called_once_with(Path(self.project),
                                      frozenset({'commands'}))

class TestChildProcessInvocation(unittest.TestCase):
    """Verify child arguments and cwd without starting a process."""

    def setUp(self):
        self.daemon = ClayDaemon()

        popen = mock.patch('subprocess.Popen')
        self.popen = popen.start()
        self.addCleanup(popen.stop)
        self.popen.return_value.pid = 4242

        # Do not start reader threads for the mocked child.
        for name in ('_read_stdout', '_read_stderr', '_read_events', '_wait_proc'):
            patcher = mock.patch.object(ClayDaemon, name, lambda *a, **k: None)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.project = tempfile.mkdtemp(prefix='clay-project-')
        self.addCleanup(shutil.rmtree, self.project, True)

    def _argv_and_cwd(self, **kwargs):
        wf = self.daemon.start_workflow(project_dir=self.project, **kwargs)
        # Clean up the event socket created by start_workflow.
        self.addCleanup(self.daemon._cleanup_wf_socket, wf)
        args, kwargs_used = self.popen.call_args
        return args[0], kwargs_used['cwd']

    def test_named_workflow_child_gets_the_flag_and_the_cwd(self):
        argv, cwd = self._argv_and_cwd(filename='wf.json', auto=True)
        self.assertIn('--project-dir', argv)
        self.assertEqual(argv[argv.index('--project-dir') + 1], self.project)
        self.assertEqual(cwd, self.project)

    def test_run_json_child_gets_the_flag_and_the_cwd(self):
        argv, cwd = self._argv_and_cwd(
            filename=None, from_data={'workflow': {'steps': []}})
        self.assertIn('--project-dir', argv)
        self.assertEqual(argv[argv.index('--project-dir') + 1], self.project)
        self.assertEqual(cwd, self.project)

    def test_the_flag_precedes_the_subcommand(self):
        """argparse only accepts a global optional before the subcommand."""
        argv, _ = self._argv_and_cwd(filename='wf.json', auto=True)
        self.assertLess(argv.index('--project-dir'), argv.index('run'))

    def test_child_uses_the_installed_clay_console_script(self):
        argv, _ = self._argv_and_cwd(filename='wf.json', auto=True)
        expected = os.path.join(os.path.dirname(sys.executable), 'clay')
        self.assertEqual(expected, argv[0])
        self.assertFalse(any(argument.endswith('clay.py') for argument in argv))


class TestDaemonServer(unittest.TestCase):
    """Integration tests: start a daemon, connect clients, run workflows."""

    @classmethod
    def setUpClass(cls):
        cls._client_access_patch = mock.patch.object(
            daemon_client, 'require_daemon_workspace')
        cls._server_access_patch = mock.patch(
            'clay.run.workspaces.daemon_access',
            return_value=mock.Mock(allowed=True, missing=frozenset()))
        cls._client_access_patch.start()
        cls._server_access_patch.start()
        cls._sock_path = _test_socket_path()
        # Monkey-patch paths so we don't clobber a real daemon
        import clay.daemon.server as srv
        cls._orig_sock = srv.SOCKET_PATH
        cls._orig_pid = srv.PID_FILE
        srv.SOCKET_PATH = cls._sock_path
        srv.PID_FILE = cls._sock_path + '.pid'

        cls.daemon = ClayDaemon()
        cls._thread = threading.Thread(target=cls.daemon.run, daemon=True)
        cls._thread.start()
        # Wait for it to be ready
        for _ in range(50):
            time.sleep(0.1)
            if os.path.exists(cls._sock_path):
                try:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.connect(cls._sock_path)
                    s.close()
                    break
                except (ConnectionRefusedError, OSError):
                    pass
        else:
            raise RuntimeError('Daemon did not start')

    @classmethod
    def tearDownClass(cls):
        cls.daemon._running = False
        cls._thread.join(timeout=5)
        # Restore
        import clay.daemon.server as srv
        srv.SOCKET_PATH = cls._orig_sock
        srv.PID_FILE = cls._orig_pid
        for f in [cls._sock_path, cls._sock_path + '.pid']:
            if os.path.exists(f):
                os.unlink(f)
        shutil.rmtree(os.path.dirname(cls._sock_path), ignore_errors=True)
        cls._server_access_patch.stop()
        cls._client_access_patch.stop()

    def _client(self):
        return DaemonClient(socket_path=self._sock_path)

    def test_ping(self):
        with self._client() as c:
            resp = c.ping()
        self.assertTrue(resp['ok'])
        self.assertTrue(resp['pong'])

    def test_list_empty(self):
        with self._client() as c:
            wfs = c.list_workflows()
        self.assertIsInstance(wfs, list)

    def test_start_and_list(self):
        """Start a simple workflow and verify it appears in the list."""
        # Create a minimal workflow file
        wf_data = {
            'workflow': {'steps': ['s1']},
            'actionSets': {
                's1': [{'type': 'humanDecision', 'id': 'q', 'prompt': 'test?'}]
            }
        }
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', prefix='test-wf-', delete=False)
        json.dump(wf_data, tmp)
        tmp.close()

        try:
            with self._client() as c:
                resp = c.start_workflow(tmp.name, auto=True, daemon_mode=True)
            self.assertTrue(resp['ok'])
            wf_id = resp['id']
            self.assertTrue(wf_id.startswith('wf-'))
            self.assertGreater(resp['pid'], 0)

            # Give it a moment to register
            time.sleep(0.5)

            with self._client() as c:
                wfs = c.list_workflows()
            ids = [w['id'] for w in wfs]
            self.assertIn(wf_id, ids)
        finally:
            os.unlink(tmp.name)

    def test_start_multiple_and_stop(self):
        """Start 3 workflows, verify all listed, stop them all."""
        tmpfiles = []
        wf_ids = []
        wf_data = {
            'workflow': {'steps': ['s1']},
            'actionSets': {
                's1': [{'type': 'humanDecision', 'id': 'q', 'prompt': 'test?'}]
            }
        }
        try:
            for i in range(3):
                tmp = tempfile.NamedTemporaryFile(
                    mode='w', suffix='.json', prefix=f'test-multi-{i}-', delete=False)
                json.dump(wf_data, tmp)
                tmp.close()
                tmpfiles.append(tmp.name)

                with self._client() as c:
                    resp = c.start_workflow(tmp.name, auto=True, daemon_mode=True)
                self.assertTrue(resp['ok'], f'Failed to start workflow {i}: {resp}')
                wf_ids.append(resp['id'])

            time.sleep(0.5)

            # All should be listed
            with self._client() as c:
                wfs = c.list_workflows()
            listed_ids = [w['id'] for w in wfs]
            for wf_id in wf_ids:
                self.assertIn(wf_id, listed_ids)

            # Stop all
            for wf_id in wf_ids:
                with self._client() as c:
                    resp = c.stop_workflow(wf_id)
                self.assertTrue(resp['ok'], f'Failed to stop {wf_id}: {resp}')

            time.sleep(1)

            # Verify stopped
            with self._client() as c:
                wfs = c.list_workflows()
            for wf in wfs:
                if wf['id'] in wf_ids:
                    self.assertIn(wf['status'], ('stopped', 'done', 'error'))

        finally:
            for f in tmpfiles:
                if os.path.exists(f):
                    os.unlink(f)

    def test_event_subscription(self):
        """Start a workflow and verify events arrive over subscription."""
        wf_data = {
            'workflow': {'steps': ['s1']},
            'actionSets': {
                's1': [{'type': 'humanDecision', 'id': 'q', 'prompt': 'test?'}]
            }
        }
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', prefix='test-events-', delete=False)
        json.dump(wf_data, tmp)
        tmp.close()

        events_received = []

        try:
            # Subscribe first
            sub = EventSubscriber(socket_path=self._sock_path)
            sub.on_event(lambda e: events_received.append(e))
            sub.start()
            time.sleep(0.2)

            # Now start a workflow
            with self._client() as c:
                resp = c.start_workflow(tmp.name, auto=True, daemon_mode=True)
            wf_id = resp['id']

            # Wait for some events
            time.sleep(2)
            sub.stop()

            # Should have received at least a 'started' event
            event_types = [e.get('event') for e in events_received]
            self.assertIn('started', event_types,
                          f'Expected "started" event, got: {event_types}')

            # Clean up
            with self._client() as c:
                c.stop_workflow(wf_id)

        finally:
            os.unlink(tmp.name)

    def test_tail(self):
        """Verify tail returns recent stdout lines."""
        wf_data = {
            'workflow': {'steps': ['s1']},
            'actionSets': {
                's1': [{'type': 'humanDecision', 'id': 'q', 'prompt': 'test?'}]
            }
        }
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', prefix='test-tail-', delete=False)
        json.dump(wf_data, tmp)
        tmp.close()

        try:
            with self._client() as c:
                resp = c.start_workflow(tmp.name, auto=True, daemon_mode=True)
            wf_id = resp['id']
            time.sleep(1)

            with self._client() as c:
                lines = c.tail(wf_id, lines=20)
            self.assertIsInstance(lines, list)

            with self._client() as c:
                c.stop_workflow(wf_id)
        finally:
            os.unlink(tmp.name)

    def test_info_not_found(self):
        with self._client() as c:
            resp = c.info('wf-9999')
        self.assertFalse(resp['ok'])


if __name__ == '__main__':
    unittest.main()
