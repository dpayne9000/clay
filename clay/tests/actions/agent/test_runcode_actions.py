"""Unit and workflow-layer tests for runcode_actions."""

import glob as _glob
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import runcode_actions
from ....run import engine, io
from ..fixtures import write_workflow, simple_workflow


class _ApprovingIO:
    """Answers every prompt 'y'. runCode reaches approval.confirm()
    (required=True, 573aee4) for any real source, handler call or workflow."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestRunCodeActions(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_inline_python_runs(self):
        result = runcode_actions.handler(
            {"id": "out", "language": "python", "source": "print('hello')"},
            {}
        )
        self.assertEqual(result["data"].strip(), "hello")

    def test_source_key_resolved_from_context(self):
        result = runcode_actions.handler(
            {"id": "out", "language": "python", "sourceKey": "code"},
            {"code": "print(42)"}
        )
        self.assertEqual(result["data"].strip(), "42")

    def test_missing_source_returns_none(self):
        with patch('builtins.print'):
            result = runcode_actions.handler(
                {"id": "out", "language": "python"}, {}
            )
        self.assertIsNone(result)

    def test_missing_source_key_value_returns_none(self):
        with patch('builtins.print'):
            result = runcode_actions.handler(
                {"id": "out", "language": "python", "sourceKey": "nonexistent"}, {}
            )
        self.assertIsNone(result)

    def test_unsupported_language_returns_none(self):
        with patch('builtins.print'):
            result = runcode_actions.handler(
                {"id": "out", "language": "ruby", "source": "puts 'hi'"}, {}
            )
        self.assertIsNone(result)

    def test_stdin_piped_to_process(self):
        result = runcode_actions.handler(
            {
                "id": "out",
                "language": "python",
                "source": "import sys; print(sys.stdin.read().strip().upper())",
                "stdin": "input_data",
            },
            {"input_data": "hello"},
        )
        self.assertEqual(result["data"].strip(), "HELLO")

    def test_nonzero_exit_appended_to_output(self):
        result = runcode_actions.handler(
            {"id": "out", "language": "python",
             "source": "import sys; sys.exit(1)"},
            {}
        )
        self.assertIn("exit code", result["data"])

    def test_temp_file_cleaned_up(self):
        before = set(_glob.glob("/tmp/tmp*.py"))
        runcode_actions.handler(
            {"id": "out", "language": "python", "source": "print('x')"},
            {}
        )
        after = set(_glob.glob("/tmp/tmp*.py"))
        self.assertEqual(before, after)

    def test_bash_language_runs(self):
        result = runcode_actions.handler(
            {"id": "out", "language": "bash", "source": "echo bash_works"},
            {}
        )
        self.assertIsNotNone(result)
        self.assertIn("bash_works", result["data"])

    def test_id_preserved_in_result(self):
        result = runcode_actions.handler(
            {"id": "my_result", "language": "python", "source": "print('ok')"},
            {}
        )
        self.assertEqual(result["id"], "my_result")


class TestRunCodeWorkflowLayer(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_output_stored_by_action_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "result", "type": "runCode", "language": "python",
                 "source": "print('workflow_output')"}
            ]}))
            data = engine.run(path)
        self.assertIn("result", data)
        self.assertIn("workflow_output", data["result"])

    def test_reads_previous_data_via_source_key(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "output", "type": "runCode", "language": "python",
                 "sourceKey": "script"}
            ]}))
            data = engine.run(path, initial_data={"script": "print('from_key')"})
        self.assertIn("from_key", data["output"])

    def test_stdin_from_previous_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "out", "type": "runCode", "language": "python",
                 "source": "import sys; print(sys.stdin.read().strip().upper())",
                 "stdin": "raw_input"}
            ]}))
            data = engine.run(path, initial_data={"raw_input": "hello"})
        self.assertIn("HELLO", data["out"])

    def test_nonzero_exit_includes_exit_code_marker(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "out", "type": "runCode", "language": "python",
                 "source": "import sys; print('partial'); sys.exit(2)"}
            ]}))
            data = engine.run(path)
        self.assertIn("exit code", data["out"])
        self.assertIn("partial", data["out"])

    def test_timeout_stored_as_timeout_message(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "out", "type": "runCode", "language": "python",
                 "source": "import time; time.sleep(999)", "timeout": 1}
            ]}))
            data = engine.run(path)
        self.assertIn("timeout", data["out"])

    def test_output_flows_to_next_step(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, {
                "workflow": {"steps": ["step1", "step2"]},
                "actionSets": {
                    "step1": [{"id": "code_output", "type": "runCode", "language": "python",
                                "source": "print('42')"}],
                    "step2": [{"id": "doubled", "type": "runCode", "language": "python",
                                "source": "import sys; n=int(sys.stdin.read().strip()); print(n*2)",
                                "stdin": "code_output"}]
                }
            })
            data = engine.run(path)
        self.assertIn("84", data["doubled"])


if __name__ == '__main__':
    unittest.main()
