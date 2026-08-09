"""Unit and integration tests for loop_actions handler."""

import contextlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import loop_actions
from ....lib import paths
from ....run import engine
from ..fixtures import write_workflow


class TestLoopActions(unittest.TestCase):

    def setUp(self):
        """A workflow frame with `any.json` in it.

        The handler resolves `file` beside the calling workflow, so the tests
        below that mock engine.run and pass a bare "any.json" need both a frame
        on the stack and a real file for it to find — a loop's sub-workflow is
        an asset of the workflow that runs it, not something searched for.
        """
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.dir = stack.enter_context(tempfile.TemporaryDirectory())
        self._write_sub(self.dir, name="any.json")
        stack.enter_context(paths.in_workflow(self.dir))

    def _write_sub(self, d, name="sub.json"):
        return write_workflow(d, {
            "workflow": {"steps": ["step"]},
            "actionSets": {
                "step": [{"id": "final", "type": "humanDecision", "prompt": "Enter:"}]
            }
        }, name=name)

    @patch('builtins.input', side_effect=["iter1", "iter2", "iter3"])
    def test_runs_n_iterations(self, _):
        with tempfile.TemporaryDirectory() as d:
            sub = self._write_sub(d)
            result = loop_actions.handler(
                {"id": "log", "file": sub, "iterations": 3, "outputKey": "final"},
                {}
            )
        self.assertIsInstance(result["data"], dict)
        self.assertEqual(result["data"]["final"], "iter3")

    @patch('builtins.input', return_value="NO")
    def test_stops_on_continue_key_falsy(self, _):
        with tempfile.TemporaryDirectory() as d:
            sub = self._write_sub(d)
            result = loop_actions.handler(
                {"id": "log", "file": sub, "iterations": 10,
                 "continueKey": "final", "outputKey": "final"},
                {}
            )
        # "NO" maps to falsy → stops after first iteration
        self.assertIsNotNone(result)

    def test_runs_exact_iteration_count(self):
        with patch('clay.run.engine.run', return_value={"final": "x"}) as mock_run:
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 5, "outputKey": "final"},
                {}
            )
            self.assertEqual(mock_run.call_count, 5)

    def test_infinite_without_continue_key_caps_at_1000(self):
        with patch('clay.run.engine.run', return_value={"final": "x"}) as mock_run, \
             patch('builtins.print'):
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 0, "outputKey": "final"},
                {}
            )
            self.assertEqual(mock_run.call_count, 1000)

    def test_ctx_passed_as_parent_seed(self):
        """Loop passes its full ctx directly to the sub-workflow as parent_seed.
        includedData filtering is done by build_ctx before the handler runs."""
        seeds = []

        def capture_run(filename, initial_data=None, auto=False):
            seeds.append(dict(initial_data or {}))
            return {"final": "done"}

        with patch('clay.run.engine.run', side_effect=capture_run):
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 1, "outputKey": "final"},
                {"__config__": {"key": "val"}, "other": "also-here"}
            )

        self.assertIn("__config__", seeds[0])
        self.assertIn("other", seeds[0])

    def test_includeddata_absent_passes_all_context(self):
        seeds = []

        def capture_run(filename, initial_data=None, auto=False):
            seeds.append(dict(initial_data or {}))
            return {"final": "done"}

        with patch('clay.run.engine.run', side_effect=capture_run):
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 1, "outputKey": "final"},
                {"a": 1, "b": 2}
            )

        self.assertIn("a", seeds[0])
        self.assertIn("b", seeds[0])

    def test_engine_globals_are_reseeded_with_filtered_loop_input(self):
        with patch('clay.run.engine.run', return_value={"final": "done"}) as mock_run:
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 1},
                {"ordinary": "selected"},
                engine_globals={"__config__": {"mode": "test"},
                                "__schema__": "schema"},
            )

        seed = mock_run.call_args.kwargs["initial_data"]
        self.assertEqual(seed["__config__"], {"mode": "test"})
        self.assertEqual(seed["__schema__"], "schema")
        self.assertEqual(seed["ordinary"], "selected")

    def test_auto_context_is_forwarded_to_iteration(self):
        with patch('clay.run.engine.run', return_value={"final": "done"}) as mock_run:
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 1},
                {},
                auto=True,
                auto_context="Parent instructions",
            )

        self.assertEqual(
            mock_run.call_args.kwargs["inherited_auto_context"],
            "Parent instructions",
        )

    def test_prev_iteration_outputs_available_in_next_seed(self):
        """Each iteration's result_data is carried forward so action IDs overwrite."""
        seeds = []

        def capture_run(filename, initial_data=None, auto=False):
            seeds.append(dict(initial_data or {}))
            return {"final": "x", "analysis": f"result-{len(seeds)}"}

        with patch('clay.run.engine.run', side_effect=capture_run):
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 3, "outputKey": "final"},
                {}
            )

        # iteration 2 should see iteration 1's analysis output
        self.assertEqual(seeds[1].get("analysis"), "result-1")
        # iteration 3 should see iteration 2's (not iteration 1's — overwritten)
        self.assertEqual(seeds[2].get("analysis"), "result-2")

    def test_loop_history_not_in_seed(self):
        """loop_history is logged to file only — never injected into iteration seed."""
        seeds = []

        def capture_run(filename, initial_data=None, auto=False):
            seeds.append(dict(initial_data or {}))
            return {"final": "x"}

        with patch('clay.run.engine.run', side_effect=capture_run):
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 3, "outputKey": "final"},
                {}
            )

        for seed in seeds:
            self.assertNotIn("loop_history", seed)

    def test_missing_file_returns_none(self):
        with patch('builtins.print'):
            result = loop_actions.handler({"id": "log", "iterations": 1}, {})
        self.assertIsNone(result)

    def test_iteration_number_passed_to_sub_workflow(self):
        seeds = []

        def capture_run(filename, initial_data=None, auto=False):
            seeds.append(dict(initial_data or {}))
            return {"final": "x"}

        with patch('clay.run.engine.run', side_effect=capture_run):
            loop_actions.handler(
                {"id": "log", "file": "any.json", "iterations": 2, "outputKey": "final"},
                {}
            )

        self.assertEqual(seeds[0]["iteration"], "1")
        self.assertEqual(seeds[1]["iteration"], "2")


if __name__ == '__main__':
    unittest.main()
