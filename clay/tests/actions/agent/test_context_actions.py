"""Unit and workflow-layer tests for context_actions (loadContext)."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import context_actions
from ....run import engine
from ..fixtures import write_workflow, simple_workflow


class TestContextActionsUnit(unittest.TestCase):

    def _write_json(self, d, payload, name="ctx.json"):
        path = os.path.join(d, name)
        with open(path, 'w') as f:
            json.dump(payload, f)
        return path

    def test_loads_json_and_returns_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_json(d, {"goal": "build api", "model": "gpt4"})
            with patch('builtins.print'):
                result = context_actions.load_handler({"id": "ctx", "file": path}, {})
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "ctx")
        self.assertIsInstance(result["data"], dict)
        self.assertEqual(result["data"]["goal"], "build api")

    def test_merge_flag_is_true(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_json(d, {"key": "val"})
            with patch('builtins.print'):
                result = context_actions.load_handler({"id": "ctx", "file": path}, {})
        self.assertTrue(result.get("merge"))

    def test_all_keys_present_in_data(self):
        payload = {"goal": "test", "tech_preferences": "python", "output_dir": "/tmp/out"}
        with tempfile.TemporaryDirectory() as d:
            path = self._write_json(d, payload)
            with patch('builtins.print'):
                result = context_actions.load_handler({"id": "ctx", "file": path}, {})
        for k, v in payload.items():
            self.assertEqual(result["data"][k], v)

    def test_missing_file_returns_none(self):
        with patch('builtins.print'):
            result = context_actions.load_handler(
                {"id": "ctx", "file": "/nonexistent/path/ctx.json"}, {}
            )
        self.assertIsNone(result)

    def test_missing_file_field_returns_none(self):
        with patch('builtins.print'):
            result = context_actions.load_handler({"id": "ctx"}, {})
        self.assertIsNone(result)

    def _write_text(self, d, body, name="notes.md"):
        path = os.path.join(d, name)
        with open(path, 'w') as f:
            f.write(body)
        return path

    def test_text_file_loads_under_action_id(self):
        """The other half of loadContext: prose, prompts, training text.

        A JSON object names its own keys and merges them. Text has no names, so
        it loads under the action's id and that is the workflow's only handle on
        it — hence merge is absent here where the JSON path sets it.
        """
        with tempfile.TemporaryDirectory() as d:
            path = self._write_text(d, "the brief:\n  ship it\n")
            with patch('builtins.print'):
                result = context_actions.load_handler({"id": "brief", "file": path}, {})
        self.assertEqual(result["id"], "brief")
        self.assertEqual(result["data"], "the brief:\n  ship it\n")
        self.assertNotIn("merge", result)

    def test_unparseable_json_loads_as_text(self):
        """A .json extension does not decide this — parsing does.

        Nothing inspects the suffix, so a file named .json that does not parse
        takes the same path a .md would. That is what lets a workflow keep a
        prompt template beside its context files without a second action type.
        """
        with tempfile.TemporaryDirectory() as d:
            path = self._write_text(d, "{not: valid json,,,}", name="ctx.json")
            with patch('builtins.print'):
                result = context_actions.load_handler({"id": "ctx", "file": path}, {})
        self.assertEqual(result["data"], "{not: valid json,,,}")

    def test_text_without_action_id_returns_none(self):
        """`id` is optional for JSON and required for text — see _as_text."""
        with tempfile.TemporaryDirectory() as d:
            path = self._write_text(d, "some prose")
            with patch('builtins.print'):
                result = context_actions.load_handler({"file": path}, {})
        self.assertIsNone(result)

    def test_json_array_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "arr.json")
            with open(path, 'w') as f:
                json.dump(["not", "a", "dict"], f)
            with patch('builtins.print'):
                result = context_actions.load_handler({"id": "ctx", "file": path}, {})
        self.assertIsNone(result)


class TestLoadContextWorkflowLayer(unittest.TestCase):

    def test_all_json_keys_merged_into_context(self):
        payload = {"goal": "build a REST API", "tech_preferences": "python+flask",
                   "output_dir": "/tmp/project"}
        with tempfile.TemporaryDirectory() as d:
            ctx_path = os.path.join(d, "goal.json")
            with open(ctx_path, 'w') as f:
                json.dump(payload, f)
            path = write_workflow(d, simple_workflow({
                "load": [{"id": "ctx", "type": "loadContext", "file": ctx_path}]
            }))
            with patch('builtins.print'):
                data = engine.run(path)
        self.assertEqual(data["goal"], "build a REST API")
        self.assertEqual(data["tech_preferences"], "python+flask")
        self.assertEqual(data["output_dir"], "/tmp/project")

    def test_merged_keys_available_in_subsequent_step(self):
        payload = {"project_name": "my-api", "stack": "flask"}
        with tempfile.TemporaryDirectory() as d:
            ctx_path = os.path.join(d, "ctx.json")
            with open(ctx_path, 'w') as f:
                json.dump(payload, f)
            path = write_workflow(d, {
                "workflow": {"steps": ["load", "use"]},
                "actionSets": {
                    "load": [{"id": "ctx", "type": "loadContext", "file": ctx_path}],
                    "use":  [{"id": "result", "type": "runCode", "language": "python",
                               "source": "import sys; print(sys.stdin.read().strip())",
                               "stdin": "project_name"}]
                }
            })
            with patch('builtins.print'):
                data = engine.run(path)
        self.assertIn("my-api", data["result"])

    def test_missing_context_file_step_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({
                "load": [{"id": "ctx", "type": "loadContext",
                           "file": "/nonexistent/ctx.json"}]
            }))
            with patch('builtins.print'):
                data = engine.run(path)
        self.assertNotIn("goal", data)

    def test_loadcontext_does_not_store_under_action_id(self):
        """merge=True unpacks keys directly — "ctx" key should not appear."""
        payload = {"my_key": "my_value"}
        with tempfile.TemporaryDirectory() as d:
            ctx_path = os.path.join(d, "ctx.json")
            with open(ctx_path, 'w') as f:
                json.dump(payload, f)
            path = write_workflow(d, simple_workflow({
                "load": [{"id": "ctx", "type": "loadContext", "file": ctx_path}]
            }))
            with patch('builtins.print'):
                data = engine.run(path)
        # "ctx" key should NOT appear (it's the action id, but merge=True bypasses that)
        self.assertNotIn("ctx", data)
        # The payload key IS present
        self.assertIn("my_key", data)


if __name__ == '__main__':
    unittest.main()
