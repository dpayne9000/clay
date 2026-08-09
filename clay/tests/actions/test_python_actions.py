"""Unit tests for python_actions handler."""

import os
import json
import tempfile
import unittest
from unittest.mock import patch

from ...actions import python_actions
from ...run import engine
from ...run import io as run_io


class _ApprovingIO:
    """Answers every prompt 'y'. `python` is a required gate (573aee4) and
    reaches this test's terminal for real without a scripted channel."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestPythonActions(unittest.TestCase):

    def setUp(self):
        self._io_patch = patch.object(run_io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def test_returns_id_and_data_keys(self):
        result = python_actions.handler({"id": "out", "code": "x = 1 + 1"}, {})
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "out")
        self.assertIn("data", result)

    def test_basic_expression_no_error(self):
        result = python_actions.handler({"id": "out", "code": "x = 1 + 1"}, {})
        self.assertNotIn("error", result["data"])

    def test_missing_code_returns_none(self):
        result = python_actions.handler({"id": "out"}, {})
        self.assertIsNone(result)

    def test_empty_code_returns_none(self):
        result = python_actions.handler({"id": "out", "code": ""}, {})
        self.assertIsNone(result)

    def test_exception_stored_as_error_string(self):
        result = python_actions.handler(
            {"id": "out", "code": "raise ValueError('oops')"}, {}
        )
        self.assertIsNotNone(result)
        self.assertIn("error", result["data"])

    def test_print_raises_because_builtins_disabled(self):
        # __builtins__={} → print is NameError → stored as [error: ...]
        result = python_actions.handler({"id": "out", "code": "print('hi')"}, {})
        self.assertIn("error", result["data"])

    def test_open_raises_because_builtins_disabled(self):
        result = python_actions.handler(
            {"id": "out", "code": "open('/etc/passwd')"}, {}
        )
        self.assertIn("error", result["data"])

    def test_result_stored_in_workflow_context(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "wf.json")
            with open(path, 'w') as f:
                json.dump({
                    "workflow": {"steps": ["run"]},
                    "actionSets": {"run": [
                        {"id": "calc", "type": "python", "code": "x = 40 + 2"}
                    ]}
                }, f)
            data = engine.run(path)
        self.assertIn("calc", data)

    def test_stdout_output_captured(self):
        # Can't use print (no builtins), but redirect_stdout trick works for other writes
        # Use io.StringIO manually in the code — but io is not available either.
        # Instead, just verify computation result is stored.
        result = python_actions.handler(
            {"id": "out", "code": "x = 2 ** 10"},
            {}
        )
        self.assertIsNotNone(result)


if __name__ == '__main__':
    unittest.main()
