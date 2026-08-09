"""Tests for default-command startup workflow configuration."""

import io
import unittest
from unittest.mock import patch

from clay.cli import _resolve_startup_workflow


class StartupWorkflowConfigurationTest(unittest.TestCase):

    def test_missing_empty_and_malformed_configuration_is_rejected(self):
        invalid = ({}, {'user': []}, {'user': 'coding2'},
                   {'user': [None]}, {'user': ['   ']})

        for startup in invalid:
            with self.subTest(startup=startup), \
                    patch('sys.stderr', new_callable=io.StringIO) as stderr, \
                    patch('clay.lib.paths.workflow_file') as workflow_file, \
                    patch('clay.lib.paths.find_workflow') as find_workflow:
                self.assertIsNone(_resolve_startup_workflow(startup))
                self.assertIn('No startup workflow configured', stderr.getvalue())
                workflow_file.assert_not_called()
                find_workflow.assert_not_called()

    @patch('clay.lib.paths.find_workflow')
    @patch('clay.lib.paths.workflow_file')
    def test_first_configured_workflow_is_resolved(self, workflow_file,
                                                   find_workflow):
        workflow_file.return_value = '/workflows/coding2/main.json'

        result = _resolve_startup_workflow({'user': ['  coding2  ', 'other']})

        self.assertEqual(result, '/workflows/coding2/main.json')
        workflow_file.assert_called_once_with('coding2')
        find_workflow.assert_not_called()

    @patch('clay.lib.paths.find_workflow', return_value=None)
    @patch('clay.lib.paths.workflow_file', return_value=None)
    def test_unknown_configured_workflow_is_rejected(self, workflow_file,
                                                     find_workflow):
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            result = _resolve_startup_workflow({'user': ['missing']})

        self.assertIsNone(result)
        self.assertIn('No workflow matching "missing"', stderr.getvalue())
        workflow_file.assert_called_once_with('missing')
        find_workflow.assert_called_once_with('missing')


if __name__ == '__main__':
    unittest.main()
