"""Unit and workflow-layer tests for scramda2_actions."""

import tempfile
import unittest
from unittest.mock import patch

from ...actions import scramda2_actions
from ...actions.scramda2_actions import _SafeMap
from ...run import engine, io
from .fixtures import write_workflow, simple_workflow


class _ApprovingIO:
    """Answers every prompt 'y'. `runCode` is a required gate (573aee4) and
    reaches this test's terminal for real without a scripted channel."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestScranda2SafeMap(unittest.TestCase):
    """scramda2 has its own _SafeMap — same contract as human_decision's."""

    def test_known_key_substituted(self):
        m = _SafeMap({"topic": "AI"})
        result = "Write about {topic} for {audience}".format_map(m)
        self.assertEqual(result, "Write about AI for {audience}")

    def test_unknown_key_preserved(self):
        m = _SafeMap({})
        self.assertEqual("{placeholder} text".format_map(m), "{placeholder} text")

    def test_multiple_keys(self):
        m = _SafeMap({"a": "1", "b": "2"})
        self.assertEqual("{a}-{b}".format_map(m), "1-2")


class TestScramda2Handler(unittest.TestCase):

    @patch.object(scramda2_actions.gopher, 'fire', return_value="result")
    def test_substitutes_variables_in_prompt(self, mock_fire):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Write about {topic} for {audience}", "examples": []},
            {"topic": "AI", "audience": "developers"},
        )
        self.assertEqual(mock_fire.call_args[0][0], "Write about AI for developers")

    @patch.object(scramda2_actions.gopher, 'fire', return_value="result")
    def test_missing_variable_preserved_in_sent_prompt(self, mock_fire):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Write about {topic} for {audience}", "examples": []},
            {"topic": "AI"},
        )
        self.assertIn("{audience}", mock_fire.call_args[0][0])

    @patch.object(scramda2_actions.gopher, 'fire', return_value="the answer")
    def test_returns_body_from_response_envelope(self, mock_fire):
        result = scramda2_actions.handler(
            {"id": "result", "prompt": "Summarise this", "examples": []},
            {}
        )
        self.assertEqual(result["id"], "result")
        self.assertEqual(result["data"], "the answer")

    @patch.object(scramda2_actions.gopher, 'fire', return_value="")
    def test_examples_forwarded_to_adapter(self, mock_fire):
        examples = [{"question": "q", "answer": "a"}]
        scramda2_actions.handler(
            {"id": "out", "prompt": "Do something", "examples": examples},
            {}
        )
        self.assertEqual(mock_fire.call_args.kwargs["examples"], examples)

    def test_no_prompt_returns_none(self):
        result = scramda2_actions.handler({"id": "out"}, {})
        self.assertIsNone(result)

    def test_empty_prompt_returns_none(self):
        result = scramda2_actions.handler({"id": "out", "prompt": ""}, {})
        self.assertIsNone(result)

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_model_field_forwarded(self, mock_fire):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Go", "examples": [], "model": "my-model"},
            {}
        )
        self.assertEqual(mock_fire.call_args.kwargs["model"], "my-model")

    @patch.object(scramda2_actions.app_config, 'get_models', return_value={})
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_no_model_field_and_no_config_default_sends_none(self, mock_fire, _):
        scramda2_actions.handler({"id": "out", "prompt": "Go", "examples": []}, {})
        self.assertIsNone(mock_fire.call_args.kwargs["model"])

    @patch.object(scramda2_actions.app_config, 'get_models',
                  return_value={"default": "config-default"})
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_no_model_field_falls_back_to_config_default(self, mock_fire, _):
        scramda2_actions.handler({"id": "out", "prompt": "Go", "examples": []}, {})
        self.assertEqual(mock_fire.call_args.kwargs["model"], "config-default")

    @patch.object(scramda2_actions.app_config, 'get_models',
                  return_value={"fast": "llama-3-8b", "default": "config-default"})
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_config_models_profile_resolved(self, mock_fire, _):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Go", "examples": [], "modelProfile": "fast"}, {}
        )
        self.assertEqual(mock_fire.call_args.kwargs["model"], "llama-3-8b")

    def test_config_models_none_does_not_crash(self):
        """Null safety: __config__.get('models') may return None."""
        # Should not raise AttributeError when models key is absent.
        with patch.object(scramda2_actions.gopher, 'fire', return_value="ok"):
            result = scramda2_actions.handler(
                {"id": "out", "prompt": "Go", "examples": [], "modelProfile": "fast"},
                {"__config__": {}}   # models key absent → __config__.get('models') = None
            )
        self.assertIsNotNone(result)

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_max_tokens_forwarded(self, mock_fire):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Go", "examples": [], "max_tokens": 512},
            {}
        )
        self.assertEqual(mock_fire.call_args.kwargs["max_tokens"], 512)

    @patch.object(scramda2_actions.app_config, 'get_max_tokens', return_value=4096)
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_config_max_tokens_is_the_action_default(self, mock_fire, _):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Go", "examples": []},
            {}
        )
        self.assertEqual(mock_fire.call_args.kwargs["max_tokens"], 4096)

    @patch.object(scramda2_actions.app_config, 'get_max_tokens', return_value=4096)
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_action_max_tokens_overrides_config_default(self, mock_fire, _):
        scramda2_actions.handler(
            {"id": "out", "prompt": "Go", "examples": [], "max_tokens": 512},
            {}
        )
        self.assertEqual(mock_fire.call_args.kwargs["max_tokens"], 512)


class TestScramda2WorkflowLayer(unittest.TestCase):

    @patch.object(scramda2_actions.gopher, 'fire', return_value="the_answer")
    def test_result_stored_by_action_id(self, mock_fire):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "answer", "type": "scramda2", "prompt": "What?", "examples": []}
            ]}))
            data = engine.run(path)
        self.assertEqual(data["answer"], "the_answer")

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_prompt_substitution_from_initial_data(self, mock_fire):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "out", "type": "scramda2",
                 "prompt": "Summarise: {topic}", "examples": []}
            ]}))
            engine.run(path, initial_data={"topic": "AI research"})
        self.assertIn("AI research", mock_fire.call_args[0][0])

    @patch.object(scramda2_actions.gopher, 'fire', return_value="ok")
    def test_action_model_overrides_workflow_model(self, mock_fire):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, {
                "model": "workflow-model",
                "workflow": {"steps": ["run"]},
                "actionSets": {"run": [
                    {"id": "out", "type": "scramda2",
                     "prompt": "Go", "examples": [], "model": "action-model"}
                ]}
            })
            engine.run(path)
        self.assertEqual(mock_fire.call_args.kwargs["model"], "action-model")

    @patch.object(scramda2_actions.gopher, 'fire', return_value="summarised_content")
    def test_result_flows_to_next_action(self, mock_fire):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, {
                "workflow": {"steps": ["s1", "s2"]},
                "actionSets": {
                    "s1": [{"id": "summary", "type": "scramda2",
                             "prompt": "Summarise", "examples": []}],
                    "s2": [{"id": "result", "type": "runCode", "language": "python",
                             "source": "import sys; print(sys.stdin.read().upper())",
                             "stdin": "summary"}]
                }
            })
            with patch.object(io, 'get', return_value=_ApprovingIO()):
                data = engine.run(path)
        self.assertIn("SUMMARISED_CONTENT", data["result"])


if __name__ == '__main__':
    unittest.main()
