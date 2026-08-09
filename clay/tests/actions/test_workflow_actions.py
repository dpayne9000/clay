"""Unit tests for workflow_actions handler."""

import contextlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ...actions import workflow_actions
from ...lib import paths
from ...run import engine
from ..test_core import _EventLog


def _write_stub(directory, name):
    """An empty but valid workflow, so `file` has something real to resolve to."""
    path = os.path.join(directory, name)
    with open(path, 'w') as f:
        json.dump({"workflow": {"steps": []}, "actionSets": {}}, f)
    return path


class TestWorkflowActionsHandler(unittest.TestCase):
    """Resolution and call-stack bookkeeping, with the engine mocked out.

    Every test runs inside a workflow frame with real files on disk, because
    that is the only state in which the handler has a question it can answer:
    `file` names a path *beside the calling workflow*, and outside a running
    workflow there is no such place. engine.run is mocked because what is under
    test is the resolution and the _running set, not the engine.
    """

    _FILES = ('sub.json', 'clean.json', 'boom.json', 'loop.json')

    def setUp(self):
        workflow_actions._running.clear()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.dir = stack.enter_context(tempfile.TemporaryDirectory())
        for name in self._FILES:
            _write_stub(self.dir, name)
        stack.enter_context(paths.in_workflow(self.dir))

    def resolved(self, name):
        """The absolute path the handler resolves `name` to.

        The same string reaches engine.run and the _running set, so the tests
        that assert on either have to name it this way rather than as the bare
        reference the action carries.
        """
        return os.path.join(self.dir, name)

    # ── the result ───────────────────────────────────────────────────────────

    @patch.object(engine, 'run', return_value={"final": "sub result"})
    def test_returns_full_result_dict(self, mock_run):
        result = workflow_actions.handler({"id": "out", "file": "sub.json"}, {})
        self.assertEqual(result, {"id": "out", "data": {"final": "sub result"}})

    @patch.object(engine, 'run', return_value={"final": "result"})
    def test_data_is_full_sub_workflow_output(self, mock_run):
        result = workflow_actions.handler({"id": "out", "file": "sub.json"}, {})
        self.assertEqual(result["data"], {"final": "result"})

    @patch.object(engine, 'run', return_value={"summary": "brief text"})
    def test_full_dict_stored_regardless_of_keys(self, mock_run):
        result = workflow_actions.handler({"id": "out", "file": "sub.json"}, {})
        self.assertEqual(result["data"], {"summary": "brief text"})

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_no_action_id_returns_none(self, mock_run):
        result = workflow_actions.handler({"file": "sub.json"}, {})
        self.assertIsNone(result)

    # ── what reaches the engine ──────────────────────────────────────────────

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_passes_resolved_path_and_ctx_as_initial_data(self, mock_run):
        """engine.run is handed the resolved file, not the reference.

        engine.run no longer resolves anything — it requires a file it can open
        and pushes that file's directory onto the stack. Passing "sub.json"
        through would make the sub-workflow's own assets resolve against
        whatever directory the process happened to be in.
        """
        workflow_actions.handler(
            {"id": "out", "file": "sub.json"},
            {"topic": "AI", "depth": "quick"}
        )
        mock_run.assert_called_once_with(
            self.resolved("sub.json"),
            initial_data={"topic": "AI", "depth": "quick"},
            auto=False
        )

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_ctx_passed_directly_as_initial_data(self, mock_run):
        """Handler passes ctx as-is; build_ctx handles filtering before handler runs."""
        workflow_actions.handler(
            {"id": "out", "file": "sub.json"},
            {"topic": "AI", "secret": "also-passed"}
        )
        _, kwargs = mock_run.call_args
        self.assertIn("topic", kwargs["initial_data"])
        self.assertIn("secret", kwargs["initial_data"])

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_includeddata_absent_passes_all(self, mock_run):
        workflow_actions.handler({"id": "out", "file": "sub.json"}, {"a": 1, "b": 2})
        _, kwargs = mock_run.call_args
        self.assertIn("a", kwargs["initial_data"])
        self.assertIn("b", kwargs["initial_data"])

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_engine_globals_are_reseeded_with_filtered_input(self, mock_run):
        workflow_actions.handler(
            {"id": "out", "file": "sub.json"},
            {"ordinary": "selected"},
            engine_globals={"__config__": {"mode": "test"},
                            "__schema__": "schema"},
        )
        seed = mock_run.call_args.kwargs["initial_data"]
        self.assertEqual(seed["__config__"], {"mode": "test"})
        self.assertEqual(seed["__schema__"], "schema")
        self.assertEqual(seed["ordinary"], "selected")

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_auto_context_is_forwarded_to_child(self, mock_run):
        workflow_actions.handler(
            {"id": "out", "file": "sub.json"},
            {},
            auto=True,
            auto_context="Parent instructions",
        )
        self.assertEqual(
            mock_run.call_args.kwargs["inherited_auto_context"],
            "Parent instructions",
        )

    # ── refusals ─────────────────────────────────────────────────────────────

    def test_missing_file_field_returns_none(self):
        with patch('builtins.print'):
            result = workflow_actions.handler({"id": "out"}, {})
        self.assertIsNone(result)

    @patch.object(engine, 'run')
    def test_unresolvable_file_returns_none_without_running_anything(self, mock_run):
        """A name with no file beside the workflow is an error, not a search.

        The engine must not be reached: resolving elsewhere is exactly what
        would let a stray file in the process directory stand in for the one
        the workflow shipped with.
        """
        with patch('builtins.print'):
            result = workflow_actions.handler(
                {"id": "out", "file": "not-here.json"}, {})
        self.assertIsNone(result)
        mock_run.assert_not_called()

    # ── the call stack ───────────────────────────────────────────────────────

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_cycle_warning_emitted(self, mock_run):
        # The warning goes on the event bus, not to stdout, so every front-end
        # attached to the run sees it. _running holds resolved paths, so the
        # same workflow reached by two different references is still one entry.
        workflow_actions._running.add(self.resolved("loop.json"))
        with _EventLog() as log:
            workflow_actions.handler({"id": "out", "file": "loop.json"}, {})
        warning = " ".join(log.messages('log'))
        self.assertIn("cycle", warning)
        self.assertIn("loop.json", warning)

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_running_set_cleaned_up_after_success(self, mock_run):
        workflow_actions.handler({"id": "out", "file": "clean.json"}, {})
        # Asserted first: without it this test passes just as well when the
        # handler bails before _running is ever touched.
        mock_run.assert_called_once()
        self.assertNotIn(self.resolved("clean.json"), workflow_actions._running)

    @patch.object(engine, 'run', side_effect=Exception("exploded"))
    def test_running_set_cleaned_up_on_exception(self, mock_run):
        with self.assertRaises(Exception):
            workflow_actions.handler({"id": "out", "file": "boom.json"}, {})
        self.assertNotIn(self.resolved("boom.json"), workflow_actions._running)


class TestWorkflowActionsOutsideAWorkflow(unittest.TestCase):
    """No frame on the stack — the case run_from_data produces."""

    def setUp(self):
        workflow_actions._running.clear()

    @patch.object(engine, 'run')
    def test_relative_file_returns_none(self, mock_run):
        self.assertIsNone(paths.current_workflow())
        with patch('builtins.print'):
            result = workflow_actions.handler({"id": "out", "file": "sub.json"}, {})
        self.assertIsNone(result)
        mock_run.assert_not_called()

    @patch.object(engine, 'run', return_value={"final": "x"})
    def test_absolute_file_still_runs(self, mock_run):
        """An absolute reference named one exact file and asked for no search."""
        with tempfile.TemporaryDirectory() as d:
            target = _write_stub(d, 'sub.json')
            result = workflow_actions.handler({"id": "out", "file": target}, {})
        self.assertEqual(result, {"id": "out", "data": {"final": "x"}})
        mock_run.assert_called_once_with(target, initial_data={}, auto=False)


if __name__ == '__main__':
    unittest.main()
