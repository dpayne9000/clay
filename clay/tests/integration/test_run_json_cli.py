"""Integration tests for the run_json CLI function (cli.run_json).

run_json() is the entry point used by the NestJS API:
  - Reads workflow JSON from --file PATH (freeing stdin for interactive responses)
    or from stdin when no --file is given
  - auto=True by default; --no-auto sets auto=False (prompt routing is decided
    by whether an events socket is attached, not by any env var)
  - Delegates to engine.run_from_data() with no config seed — actions that
    need app config (e.g. scramda2 model resolution) read it directly from
    clay.lib.config instead of the workflow context
"""

import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import clay.actions.human_decision as hd_mod
from clay.cli import run_json
from clay.run.failure import WorkflowFailure


def _make_args(file=None, no_auto=False):
    ns = argparse.Namespace()
    ns.file = file
    ns.no_auto = no_auto
    return ns


def _simple_wf():
    return {
        "name": "test-run",
        "workflow": {"steps": ["run"]},
        "actionSets": {"run": [
            {"id": "v", "type": "python", "code": "42"},
        ]},
    }


class TestRunJsonReadsFile(unittest.TestCase):

    def test_reads_workflow_from_file(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(_simple_wf(), f)
            path = f.name
        try:
            with patch('clay.run.engine.run_from_data') as mock_run:
                mock_run.return_value = {}
                run_json(_make_args(file=path))
            called_data = mock_run.call_args[0][0]
            self.assertEqual(called_data["name"], "test-run")
        finally:
            os.unlink(path)

    def test_reads_workflow_from_stdin_when_no_file(self):
        payload = json.dumps(_simple_wf())
        with patch('sys.stdin', io.StringIO(payload)), \
             patch('clay.run.engine.run_from_data') as mock_run:
            mock_run.return_value = {}
            run_json(_make_args())
        mock_run.assert_called_once()

    def test_label_taken_from_name_field(self):
        wf = dict(_simple_wf(), name="my-workflow")
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(wf, f)
            path = f.name
        try:
            with patch('clay.run.engine.run_from_data') as mock_run:
                mock_run.return_value = {}
                run_json(_make_args(file=path))
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs.get('label') or mock_run.call_args[1].get('label'), 'my-workflow')
        finally:
            os.unlink(path)

    def test_label_defaults_to_api_run_when_no_name(self):
        wf = dict(_simple_wf())
        del wf["name"]
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(wf, f)
            path = f.name
        try:
            with patch('clay.run.engine.run_from_data') as mock_run:
                mock_run.return_value = {}
                run_json(_make_args(file=path))
            _, kwargs = mock_run.call_args
            self.assertEqual(kwargs.get('label', mock_run.call_args[1].get('label')), 'api-run')
        finally:
            os.unlink(path)


class TestRunJsonAutoMode(unittest.TestCase):

    def _run(self, no_auto=False):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(_simple_wf(), f)
            path = f.name
        try:
            with patch('clay.run.engine.run_from_data') as mock_run:
                mock_run.return_value = {}
                run_json(_make_args(file=path, no_auto=no_auto))
            return mock_run.call_args
        finally:
            os.unlink(path)

    def test_default_auto_is_true(self):
        call_args = self._run(no_auto=False)
        _, kwargs = call_args
        self.assertTrue(kwargs.get('auto', call_args[1].get('auto')))

    def test_no_auto_sets_auto_false(self):
        call_args = self._run(no_auto=True)
        _, kwargs = call_args
        self.assertFalse(kwargs.get('auto', call_args[1].get('auto')))

    def test_no_auto_sets_no_env_flags(self):
        """Prompt routing follows the events socket, not an env var."""
        before = dict(os.environ)
        self._run(no_auto=True)
        self.assertEqual(dict(os.environ), before)


class TestRunJsonFailureStatus(unittest.TestCase):

    def test_known_workflow_failure_returns_nonzero(self):
        payload = json.dumps(_simple_wf())
        with patch('sys.stdin', io.StringIO(payload)), \
                patch('clay.run.engine.run_from_data',
                      side_effect=WorkflowFailure('invalid action')):
            self.assertEqual(run_json(_make_args()), 1)


if __name__ == '__main__':
    unittest.main()
