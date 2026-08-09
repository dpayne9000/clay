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
from unittest import mock

# Ensure clay is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from clay.daemon.server import ClayDaemon, ClientHandler, SOCKET_PATH
from clay.daemon.client import DaemonClient, EventSubscriber
from clay.daemon import protocol, client as daemon_client
from clay.lib import config, paths


def _test_socket_path():
    return os.path.join(tempfile.gettempdir(), f'clayd-test-{os.getpid()}.sock')


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
                                   return_value='/somewhere'):
                c.start_workflow('wf.json')
                c.start_workflow_json({'workflow': {}})
        self.assertEqual([m['project_dir'] for m in sent],
                         ['/somewhere', '/somewhere'])


class TestChildProcessInvocation(unittest.TestCase):
    """What clayd actually spawns. Popen is mocked — no child runs.

    The regression: clayd ran its children with cwd set to clay's own install,
    so a workflow whose writeFile had no explicit `root` resolved '.' there and
    wrote into the program.
    """

    def setUp(self):
        # __init__ is pure — two dicts, a counter and a lock. No I/O.
        self.daemon = ClayDaemon()

        popen = mock.patch('subprocess.Popen')
        self.popen = popen.start()
        self.addCleanup(popen.stop)
        self.popen.return_value.pid = 4242

        # start_workflow spawns four reader threads against the child's pipes.
        # There is no child, and they are not what this test is about.
        for name in ('_read_stdout', '_read_stderr', '_read_events', '_wait_proc'):
            patcher = mock.patch.object(ClayDaemon, name, lambda *a, **k: None)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.project = tempfile.mkdtemp(prefix='clay-project-')
        self.addCleanup(shutil.rmtree, self.project, True)

    def _argv_and_cwd(self, **kwargs):
        wf = self.daemon.start_workflow(project_dir=self.project, **kwargs)
        # The event socket is the one real resource start_workflow takes.
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
