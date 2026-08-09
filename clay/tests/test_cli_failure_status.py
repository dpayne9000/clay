"""CLI boundaries return nonzero for known workflow failures."""

import argparse
import unittest
from unittest.mock import patch

from clay import cli
from clay.run.failure import WorkflowFailure


class RunFailureStatusTest(unittest.TestCase):

    def test_run_returns_one_for_known_workflow_failure(self):
        args = argparse.Namespace(theme=None, plain_stdout=False,
                                  daemon=False, auto=False)
        with patch('clay.cli._resolve_workflow_arg',
                   return_value='/workflows/bad.json'), \
                patch('clay.cli._attach_terminal', return_value=None), \
                patch('clay.cli._start_event_socket'), \
                patch('clay.cli._load_config', return_value={}), \
                patch('clay.cli.engine.run',
                      side_effect=WorkflowFailure('invalid action')), \
                patch('clay.run.logger.stop_socket_bridge'):
            self.assertEqual(cli.run(args), 1)

    def test_run_does_not_swallow_unexpected_exception(self):
        args = argparse.Namespace(theme=None, plain_stdout=False,
                                  daemon=False, auto=False)
        with patch('clay.cli._resolve_workflow_arg',
                   return_value='/workflows/bad.json'), \
                patch('clay.cli._attach_terminal', return_value=None), \
                patch('clay.cli._start_event_socket'), \
                patch('clay.cli._load_config', return_value={}), \
                patch('clay.cli.engine.run', side_effect=RuntimeError('bug')), \
                patch('clay.run.logger.stop_socket_bridge'):
            with self.assertRaisesRegex(RuntimeError, 'bug'):
                cli.run(args)


if __name__ == '__main__':
    unittest.main()
