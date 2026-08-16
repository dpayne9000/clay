"""Tests for selecting the workflow started by bare `clay`."""

import argparse
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from clay import cli


class DefaultWorkflowCommandTest(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.startup = os.path.join(self.directory.name, 'startup.json')
        self.shipped = os.path.join(self.directory.name, 'shipped.json')
        with open(self.shipped, 'w', encoding='utf-8') as output:
            json.dump({'_startupVersion': 2, '_defaultManaged': True,
                       'user': ['workflows/system/chat/main.json']}, output)
        patcher = patch.multiple(
            cli.app_config,
            _STARTUP_PATH=self.startup,
            _BASE_STARTUP_PATH=self.shipped,
            clay_dir=self.directory.name,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_set_marks_the_selection_as_user_owned(self):
        workflow = os.path.join(self.directory.name, 'workflows', 'mine',
                                'main.json')
        os.makedirs(os.path.dirname(workflow))
        with open(workflow, 'w', encoding='utf-8') as output:
            output.write('{}')
        args = argparse.Namespace(default_operation='set', file=workflow,
                                  workflow_name=[])

        with patch.object(cli.app_config, 'load_startup', return_value={}), \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertIsNone(cli.default_cmd(args))

        with open(self.startup, encoding='utf-8') as source:
            saved = json.load(source)
        self.assertEqual(['workflows/mine/main.json'], saved['user'])
        self.assertFalse(saved['_defaultManaged'])

    def test_reset_restores_managed_shipped_default(self):
        args = argparse.Namespace(default_operation='reset')
        current = {'user': ['custom.json'], 'daemon': ['keep-me.json']}
        with patch.object(cli.app_config, 'load_startup', return_value=current), \
                patch('sys.stdout', new_callable=io.StringIO):
            self.assertIsNone(cli.default_cmd(args))
        with open(self.startup, encoding='utf-8') as source:
            saved = json.load(source)
        self.assertTrue(saved['_defaultManaged'])
        self.assertEqual(['keep-me.json'], saved['daemon'])


if __name__ == '__main__':
    unittest.main()
