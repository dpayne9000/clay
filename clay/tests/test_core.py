"""
Core test suite for clayCLI workflow engine.

Covers:
  - engine.process_steps (data accumulation, initial_data)
  - engine.run (defaults, override priority, file errors)
  - Integration: two-level and three-level nested workflows

Action handler unit tests live in clay/tests/actions/:
  - test_human_decision.py   — SafeMap, human_decision handler
  - test_scramda2_actions.py — scramda2 handler
  - test_workflow_actions.py — workflow_actions handler
  - test_python_actions.py   — python_actions handler
  - test_file_actions.py     — file_actions (writeFile)
  - test_api_actions.py      — api_actions (API)
  - test_transform_data_actions.py
  - test_mongo_actions.py
  - test_report_actions.py
  - agent/test_shell_actions.py
  - agent/test_runcode_actions.py
  - agent/test_skill_actions.py
  - agent/test_web_actions.py
  - agent/test_loop_actions.py
  - agent/test_memory_actions.py
  - agent/test_human_shell_actions.py
  - agent/test_create_action.py
  - agent/test_context_actions.py
  - agent/test_tag_actions.py
  - agent/test_writecode_actions.py
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from ..actions import scramda2_actions, workflow_actions
from ..run import engine
from ..run import events as run_events
from ..run import io as run_io
from ..run import logger as run_logger
from ..run.failure import WorkflowFailure


class _EventLog:
    """Collects bus events for assertions; use as a context manager."""

    def __init__(self):
        self.events = []

    def __enter__(self):
        run_logger.add_listener(self.events.append)
        return self

    def __exit__(self, *exc):
        run_logger.remove_listener(self.events.append)
        return False

    def messages(self, event_type):
        return [e.get('message', '') for e in self.events
                if e.get('type') == event_type]

    def outputs(self, kind=None):
        """action.output payloads, joined as a front-end would draw them.

        Filter by `kind` ('prompt', 'file', 'command', 'read') to assert on one
        handler's payloads without matching on message text — which is the
        whole reason these are not log events.
        """
        drawn = []
        for e in self.events:
            if e.get('type') != run_events.ACTION_OUTPUT:
                continue
            if kind is not None and e.get('kind') != kind:
                continue
            label, text = e.get('label', ''), e.get('text', '')
            drawn.append(f'{label}\n{text}' if text else label)
        return drawn


# ─────────────────────────────────────────────────────────────────────────────
# engine.process_steps
# ─────────────────────────────────────────────────────────────────────────────

class TestProcessSteps(unittest.TestCase):

    def _make_human_action(self, action_id, prompt, included=None):
        a = {"id": action_id, "type": "humanDecision", "prompt": prompt}
        if included:
            a["includedData"] = included
        return a

    def _make_scramda_action(self, action_id, prompt, included=None):
        a = {"id": action_id, "type": "scramda2", "prompt": prompt, "examples": []}
        if included:
            a["includedData"] = included
        return a

    @patch('builtins.input', return_value="test value")
    def test_step_result_stored_in_previous_data(self, _):
        steps = ["s1"]
        actions = {"s1": [self._make_human_action("key1", "Enter:")]}
        result = engine.process_steps(steps, actions)
        self.assertEqual(result["key1"], "test value")

    @patch('builtins.input', side_effect=["first", "second"])
    def test_multiple_steps_accumulate(self, _):
        steps = ["s1", "s2"]
        actions = {
            "s1": [self._make_human_action("a", "A:")],
            "s2": [self._make_human_action("b", "B:")]
        }
        result = engine.process_steps(steps, actions)
        self.assertEqual(result["a"], "first")
        self.assertEqual(result["b"], "second")

    def test_initial_data_seeds_previous_data(self):
        steps = []
        result = engine.process_steps(steps, {}, initial_data={"topic": "AI"})
        self.assertEqual(result["topic"], "AI")

    @patch('builtins.input', return_value="override")
    def test_step_output_overrides_initial_data(self, _):
        steps = ["s1"]
        actions = {"s1": [self._make_human_action("topic", "Enter topic:")]}
        result = engine.process_steps(
            steps, actions, initial_data={"topic": "original"}
        )
        self.assertEqual(result["topic"], "override")

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_included_data_filters_correctly(self, mock_fire):
        steps = ["s1"]
        actions = {"s1": [self._make_scramda_action("out", "About {topic}", ["topic"])]}
        engine.process_steps(
            steps, actions,
            initial_data={"topic": "AI", "secret": "hidden"}
        )
        # secret should not appear in the prompt because it wasn't in includedData
        self.assertNotIn("hidden", mock_fire.call_args[0][0])

    @patch('builtins.input', return_value="x")
    def test_unknown_action_type_stops_processing(self, _):
        steps = ["s1"]
        actions = {"s1": [{"id": "out", "type": "unknownType", "prompt": "x"}]}
        with _EventLog() as bus:
            with self.assertRaises(WorkflowFailure):
                engine.process_steps(steps, actions)
        errors = " ".join(bus.messages('action.error'))
        self.assertIn("unknownType", errors)

    @patch('builtins.input', return_value="x")
    def test_step_with_no_actions_skipped(self, _):
        steps = ["empty_step", "real_step"]
        actions = {
            "empty_step": [],
            "real_step": [self._make_human_action("k", "Enter:")]
        }
        result = engine.process_steps(steps, actions)
        self.assertEqual(result["k"], "x")

    @patch('builtins.input', return_value="x")
    def test_missing_step_skipped(self, _):
        steps = ["defined", "not_in_actionsets"]
        actions = {"defined": [self._make_human_action("k", "Enter:")]}
        result = engine.process_steps(steps, actions)
        self.assertEqual(result["k"], "x")


# ─────────────────────────────────────────────────────────────────────────────
# engine.run
# ─────────────────────────────────────────────────────────────────────────────

class TestRun(unittest.TestCase):

    def _write_workflow(self, d, tmpdir, name="workflow.json"):
        path = os.path.join(tmpdir, name)
        with open(path, 'w') as f:
            json.dump(d, f)
        return path

    def test_file_not_found_returns_none(self):
        result = engine.run("/nonexistent/path/workflow.json")
        self.assertIsNone(result)

    def test_invalid_json_returns_none(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{not valid json")
            path = f.name
        try:
            result = engine.run(path)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    @patch('builtins.input', return_value="typed")
    def test_defaults_applied(self, _):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_workflow({
                "defaults": {"preset": "default_value"},
                "workflow": {"steps": ["s1"]},
                "actionSets": {
                    "s1": [{"id": "out", "type": "humanDecision",
                            "prompt": "Enter:", "includedData": ["preset"]}]
                }
            }, d)
            result = engine.run(path)
        self.assertEqual(result["preset"], "default_value")

    @patch('builtins.input', return_value="typed")
    def test_initial_data_overrides_defaults(self, _):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_workflow({
                "defaults": {"depth": "comprehensive"},
                "workflow": {"steps": []},
                "actionSets": {}
            }, d)
            result = engine.run(path, initial_data={"depth": "quick"})
        self.assertEqual(result["depth"], "quick")

    @patch('builtins.input', return_value="answer")
    def test_returns_accumulated_results(self, _):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_workflow({
                "workflow": {"steps": ["s1"]},
                "actionSets": {
                    "s1": [{"id": "reply", "type": "humanDecision", "prompt": "Q:"}]
                }
            }, d)
            result = engine.run(path)
        self.assertEqual(result["reply"], "answer")

    def test_empty_workflow_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_workflow({
                "workflow": {"steps": []},
                "actionSets": {}
            }, d)
            result = engine.run(path)
        self.assertEqual(result, {})


# ─────────────────────────────────────────────────────────────────────────────
# Integration — nested workflows via temp JSON files
# ─────────────────────────────────────────────────────────────────────────────

class TestNestedWorkflowsIntegration(unittest.TestCase):

    def _write(self, d, tmpdir, name):
        path = os.path.join(tmpdir, name)
        with open(path, 'w') as f:
            json.dump(d, f)
        return path

    def setUp(self):
        workflow_actions._running.clear()

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_parent_auto_context_reaches_child_auto_decision(self, mock_fire):
        with tempfile.TemporaryDirectory() as d:
            child = self._write({
                "workflow": {"steps": ["ask"]},
                "actionSets": {"ask": [
                    {"id": "answer", "type": "humanDecision", "prompt": "Child question"}
                ]},
            }, d, "child.json")
            parent = self._write({
                "autoContext": "Parent instructions",
                "workflow": {"steps": ["child"]},
                "actionSets": {"child": [
                    {"id": "child_result", "type": "workflow", "file": child,
                     "includedData": []}
                ]},
            }, d, "parent.json")

            engine.run(parent, auto=True)

        self.assertIn("Parent instructions", mock_fire.call_args[0][0])

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_child_auto_context_layers_after_parent(self, mock_fire):
        with tempfile.TemporaryDirectory() as d:
            child = self._write({
                "autoContext": "Child instructions",
                "workflow": {"steps": ["ask"]},
                "actionSets": {"ask": [
                    {"id": "answer", "type": "humanDecision", "prompt": "Question"}
                ]},
            }, d, "child.json")
            parent = self._write({
                "autoContext": "Parent instructions",
                "workflow": {"steps": ["child"]},
                "actionSets": {"child": [
                    {"id": "child_result", "type": "workflow", "file": child}
                ]},
            }, d, "parent.json")

            engine.run(parent, auto=True)

        prompt = mock_fire.call_args[0][0]
        self.assertLess(prompt.index("Parent instructions"),
                        prompt.index("Child instructions"))

    def test_engine_globals_reseed_filtered_child(self):
        with tempfile.TemporaryDirectory() as d:
            child = self._write({
                "workflow": {"steps": []},
                "actionSets": {},
            }, d, "child.json")
            parent = self._write({
                "workflow": {"steps": ["child"]},
                "actionSets": {"child": [
                    {"id": "child_result", "type": "workflow", "file": child,
                     "includedData": []}
                ]},
            }, d, "parent.json")

            result = engine.run(
                parent,
                initial_data={"__config__": {"mode": "test"},
                              "__schema__": "schema",
                              "ordinary": "filtered"},
            )

        child_result = result["child_result"]
        self.assertEqual(child_result["__config__"], {"mode": "test"})
        self.assertEqual(child_result["__schema__"], "schema")
        self.assertNotIn("ordinary", child_result)

    @patch('builtins.input', side_effect=["AI ethics", "APPROVE"])
    def test_two_level_workflow_data_flows(self, mock_input):
        """
        L1 collects topic via human step, calls L2 which collects approval.
        L2's final (the approval) is returned to L1 as sub_result.
        """
        with tempfile.TemporaryDirectory() as d:
            l2 = self._write({
                "workflow": {"steps": ["gate"]},
                "actionSets": {
                    "gate": [{"id": "final", "type": "humanDecision",
                               "prompt": "Approve?"}]
                }
            }, d, "l2.json")

            l1 = self._write({
                "workflow": {"steps": ["collect", "sub"]},
                "actionSets": {
                    "collect": [{"id": "topic", "type": "humanDecision",
                                  "prompt": "Topic:"}],
                    "sub": [{"id": "sub_result", "type": "workflow",
                              "file": l2, "outputKey": "final"}]
                }
            }, d, "l1.json")

            result = engine.run(l1)

        self.assertEqual(result["topic"], "AI ethics")
        self.assertIsInstance(result["sub_result"], dict)
        self.assertEqual(result["sub_result"]["final"], "APPROVE")

    @patch('builtins.input', side_effect=["deep topic", "mid answer", "bottom answer"])
    def test_three_level_nested_data_flows(self, mock_input):
        """
        L1 → L2 → L3 each collecting one human input.
        Each level's output is returned up the chain.
        """
        with tempfile.TemporaryDirectory() as d:
            l3 = self._write({
                "workflow": {"steps": ["step"]},
                "actionSets": {
                    "step": [{"id": "final", "type": "humanDecision",
                               "prompt": "L3 input:"}]
                }
            }, d, "l3.json")

            l2 = self._write({
                "workflow": {"steps": ["step", "call_l3"]},
                "actionSets": {
                    "step": [{"id": "mid", "type": "humanDecision",
                               "prompt": "L2 input:"}],
                    "call_l3": [{"id": "final", "type": "workflow",
                                  "file": l3, "outputKey": "final"}]
                }
            }, d, "l2.json")

            l1 = self._write({
                "workflow": {"steps": ["step", "call_l2"]},
                "actionSets": {
                    "step": [{"id": "top", "type": "humanDecision",
                               "prompt": "L1 input:"}],
                    "call_l2": [{"id": "l2_result", "type": "workflow",
                                  "file": l2, "outputKey": "final"}]
                }
            }, d, "l1.json")

            result = engine.run(l1)

        self.assertEqual(result["top"], "deep topic")
        # l2_result is l2's full step_output; l2's "final" is l3's full step_output
        self.assertIsInstance(result["l2_result"], dict)
        self.assertEqual(result["l2_result"]["final"]["final"], "bottom answer")

    @patch('builtins.input', side_effect=["seed overrides this", "collected"])
    def test_seed_data_available_in_sub_workflow(self, mock_input):
        """
        Parent passes topic via includedData. Sub-workflow receives it
        as seed and it's available in its previous_data from the start.
        """
        with tempfile.TemporaryDirectory() as d:
            l2 = self._write({
                "workflow": {"steps": ["step"]},
                "actionSets": {
                    "step": [{"id": "final", "type": "humanDecision",
                               "prompt": "Confirm:"}]
                }
            }, d, "l2.json")

            l1 = self._write({
                "workflow": {"steps": ["collect", "call_l2"]},
                "actionSets": {
                    "collect": [{"id": "topic", "type": "humanDecision",
                                  "prompt": "Topic:"}],
                    "call_l2": [{"id": "result", "type": "workflow",
                                  "file": l2, "outputKey": "final",
                                  "includedData": ["topic"]}]
                }
            }, d, "l1.json")

            result = engine.run(l1)

        # L2's full step_output is stored under "result"; extract "final" key
        self.assertIsInstance(result["result"], dict)
        self.assertEqual(result["result"]["final"], "collected")

    @patch('builtins.input', return_value="x")
    def test_defaults_flow_into_sub_workflow(self, mock_input):
        """
        L1 defaults set depth=quick. Sub-workflow inherits it via seed.
        """
        with tempfile.TemporaryDirectory() as d:
            l2 = self._write({
                "defaults": {"depth": "comprehensive"},
                "workflow": {"steps": []},
                "actionSets": {}
            }, d, "l2.json")

            l1 = self._write({
                "defaults": {"depth": "quick"},
                "workflow": {"steps": ["call_l2"]},
                "actionSets": {
                    "call_l2": [{"id": "result", "type": "workflow",
                                  "file": l2, "outputKey": "depth",
                                  "includedData": ["depth"]}]
                }
            }, d, "l1.json")

            result = engine.run(l1)

        # L1 default "quick" is in step_output and overrides L2 default
        self.assertEqual(result["depth"], "quick")
        # The sub-workflow result dict is stored under "result"; depth key = "quick"
        self.assertIsInstance(result["result"], dict)
        self.assertEqual(result["result"]["depth"], "quick")

    @patch('builtins.input', side_effect=["a1", "a2"])
    def test_same_sub_workflow_called_twice_independently(self, mock_input):
        """
        Calling the same workflow file twice produces two independent runs,
        each with their own inputs stored under different ids.
        """
        with tempfile.TemporaryDirectory() as d:
            sub = self._write({
                "workflow": {"steps": ["step"]},
                "actionSets": {
                    "step": [{"id": "final", "type": "humanDecision",
                               "prompt": "Enter:"}]
                }
            }, d, "sub.json")

            l1 = self._write({
                "workflow": {"steps": ["first", "second"]},
                "actionSets": {
                    "first":  [{"id": "result_a", "type": "workflow",
                                 "file": sub, "outputKey": "final"}],
                    "second": [{"id": "result_b", "type": "workflow",
                                 "file": sub, "outputKey": "final"}]
                }
            }, d, "l1.json")

            result = engine.run(l1)

        self.assertIsInstance(result["result_a"], dict)
        self.assertIsInstance(result["result_b"], dict)
        self.assertEqual(result["result_a"]["final"], "a1")
        self.assertEqual(result["result_b"]["final"], "a2")

    @patch('builtins.input', return_value="x")
    def test_cycle_warning_on_self_reference(self, mock_input):
        """
        A workflow that calls itself prints a cycle warning.
        We mock engine.run on the recursive call to prevent infinite recursion.
        """
        with tempfile.TemporaryDirectory() as d:
            loop_path = os.path.join(d, "loop.json")
            with open(loop_path, 'w') as f:
                json.dump({
                    "workflow": {"steps": ["recurse"]},
                    "actionSets": {
                        "recurse": [{"id": "out", "type": "workflow",
                                      "file": loop_path, "outputKey": "final"}]
                    }
                }, f)

            workflow_actions._running.add(loop_path)
            with _EventLog() as bus:
                with patch.object(engine, 'run', return_value={"final": "stopped"}):
                    workflow_actions.handler(
                        {"id": "out", "file": loop_path},
                        {}
                    )

            warning = " ".join(bus.messages('log'))
            self.assertIn("cycle", warning)

    @patch('builtins.input', side_effect=["topic value", "APPROVE"])
    def test_research_doc_generator_shape(self, mock_input):
        """
        Simulates the shape of research-doc-generator: two sub-workflows,
        where the second receives output from the first as seed.
        The second sub-workflow's output becomes the final result.
        """
        with tempfile.TemporaryDirectory() as d:
            research = self._write({
                "workflow": {"steps": []},
                "actionSets": {},
                "defaults": {"final": "research brief content"}
            }, d, "research.json")

            review = self._write({
                "workflow": {"steps": ["gate"]},
                "actionSets": {
                    "gate": [{"id": "final", "type": "humanDecision",
                               "prompt": "Approve?"}]
                }
            }, d, "review.json")

            orchestrator = self._write({
                "workflow": {"steps": ["intake", "runResearch", "runReview"]},
                "actionSets": {
                    "intake": [{"id": "topic", "type": "humanDecision",
                                 "prompt": "Topic:"}],
                    "runResearch": [{"id": "research_brief", "type": "workflow",
                                      "file": research, "outputKey": "final",
                                      "includedData": ["topic"]}],
                    "runReview": [{"id": "final_document", "type": "workflow",
                                    "file": review, "outputKey": "final",
                                    "includedData": ["research_brief"]}]
                }
            }, d, "orchestrator.json")

            result = engine.run(orchestrator)

        self.assertEqual(result["topic"], "topic value")
        # research_brief is the full sub-workflow result dict
        self.assertIsInstance(result["research_brief"], dict)
        self.assertEqual(result["research_brief"]["final"], "research brief content")
        # final_document is the full review sub-workflow result dict
        self.assertIsInstance(result["final_document"], dict)
        self.assertEqual(result["final_document"]["final"], "APPROVE")


class _ApprovingIO:
    """Answers every prompt 'y'. shell/runCode reach approval.confirm()
    (required=True, 573aee4) even inside a loop iteration."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestLoopResultContextFlow(unittest.TestCase):
    """Integration tests: loop result stored as full dict + dot-notation extraction."""

    def setUp(self):
        self._io_patch = patch.object(run_io, 'get', return_value=_ApprovingIO())
        self._io_patch.start()
        self.addCleanup(self._io_patch.stop)

    def _write(self, d, tmpdir, name):
        path = os.path.join(tmpdir, name)
        with open(path, 'w') as f:
            json.dump(d, f)
        return path

    def test_loop_result_stored_as_full_dict(self):
        """
        After a loop, step_output[loop_id] is the full result dict from the
        last iteration — not a scalar extracted via outputKey.
        """
        with tempfile.TemporaryDirectory() as d:
            iteration = self._write({
                "workflow": {"steps": ["work"]},
                "actionSets": {
                    "work": [{"id": "answer", "type": "shell",
                              "command": "echo loop-output", "timeout": 5}]
                }
            }, d, "iteration.json")

            parent = self._write({
                "workflow": {"steps": ["run_loop"]},
                "actionSets": {
                    "run_loop": [{"id": "loop_data", "type": "loop",
                                  "file": iteration, "iterations": 2,
                                  "outputKey": "answer"}]
                }
            }, d, "parent.json")

            result = engine.run(parent)

        self.assertIsInstance(result["loop_data"], dict)
        self.assertIn("answer", result["loop_data"])
        self.assertIn("loop-output", result["loop_data"]["answer"])

    def test_dot_notation_extracts_key_from_loop_result(self):
        """
        A downstream action can extract a specific key from a loop result
        using dot-notation in includedData: "alias=loop_id.key".
        The extracted scalar is available in ctx under the alias name.
        """
        with tempfile.TemporaryDirectory() as d:
            iteration = self._write({
                "workflow": {"steps": ["work"]},
                "actionSets": {
                    "work": [{"id": "answer", "type": "shell",
                              "command": "echo loop-output", "timeout": 5}]
                }
            }, d, "iteration.json")

            parent = self._write({
                "workflow": {"steps": ["run_loop", "post_loop"]},
                "actionSets": {
                    "run_loop": [{"id": "loop_data", "type": "loop",
                                  "file": iteration, "iterations": 2,
                                  "outputKey": "answer"}],
                    "post_loop": [{"id": "extracted", "type": "runCode",
                                   "language": "python",
                                   "source": "import sys; print(sys.stdin.read().strip())",
                                   "stdin": "answer",
                                   "includedData": ["answer=loop_data.answer"]}]
                }
            }, d, "parent.json")

            result = engine.run(parent)

        # runCode received "answer" in ctx via dot-notation and piped it to stdout
        self.assertIn("loop-output", result["extracted"])


if __name__ == '__main__':
    unittest.main()
