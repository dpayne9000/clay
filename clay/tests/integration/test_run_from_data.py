"""Integration tests for engine.run_from_data().

run_from_data() takes a pre-parsed workflow dict (no file I/O), runs it
end-to-end, and returns the accumulated step_output.  It is the execution
path used by the API and by run-json CLI.

Notes on python_actions:
  - exec() is called with empty builtins — no 'ctx' variable, no imports
  - Only captured stdout is returned (print() calls), not expression values
  - Use transformData or scramda2 (mocked) to test context flows
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from ...actions import scramda2_actions
from ...run import engine, io


class _ApprovingIO:
    """Answers every prompt 'y'. `runCode` is a required gate (573aee4) and
    reaches this test's terminal for real without a scripted channel."""

    def prompt(self, prompt_id, text):
        return 'y'


def _wf(action_sets, steps=None):
    """Minimal valid workflow dict."""
    return {
        "workflow": {"steps": steps or list(action_sets.keys())},
        "actionSets": action_sets,
    }


def _make_scramda2_response(body_text):
    # OpenAI-compatible chat-completion shape — gopher's extract_text reads
    # choices[0].message.content.
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": body_text}}]}
    ).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestRunFromDataBasic(unittest.TestCase):

    def test_returns_accumulated_data(self):
        # Use scramda2 (mocked) to produce a deterministic result
        with patch('urllib.request.urlopen',
                   return_value=_make_scramda2_response("hello world")):
            wf = _wf({"run": [
                {"id": "greeting", "type": "scramda2",
                 "prompt": "Say hello", "examples": []},
            ]})
            result = engine.run_from_data(wf, auto=True)
        self.assertEqual(result["greeting"], "hello world")

    def test_initial_data_flows_into_first_action_via_scramda2(self):
        """Context keys flow into action handlers — verified via prompt substitution."""
        with patch('urllib.request.urlopen',
                   return_value=_make_scramda2_response("ok")) as mock_open:
            wf = _wf({"run": [
                {"id": "out", "type": "scramda2",
                 "prompt": "Write about {topic}", "examples": []},
            ]})
            engine.run_from_data(wf, initial_data={"topic": "AI"}, auto=True)
        body = json.loads(mock_open.call_args[0][0].data.decode())
        contents = " ".join(m.get("content", "") for m in body["messages"])
        self.assertIn("AI", contents)

    def test_defaults_merged_below_initial_data(self):
        """Workflow defaults are overridden by initial_data."""
        with patch('urllib.request.urlopen',
                   return_value=_make_scramda2_response("ok")) as mock_open:
            wf = {
                "workflow": {"steps": ["run"]},
                "defaults": {"topic": "default-topic"},
                "actionSets": {"run": [
                    {"id": "out", "type": "scramda2",
                     "prompt": "Write about {topic}", "examples": []},
                ]},
            }
            engine.run_from_data(wf, initial_data={"topic": "override-topic"}, auto=True)
        body = json.loads(mock_open.call_args[0][0].data.decode())
        contents = " ".join(m.get("content", "") for m in body["messages"])
        self.assertIn("override-topic", contents)
        self.assertNotIn("default-topic", contents)

    def test_defaults_used_when_no_initial_data(self):
        with patch('urllib.request.urlopen',
                   return_value=_make_scramda2_response("ok")) as mock_open:
            wf = {
                "workflow": {"steps": ["run"]},
                "defaults": {"topic": "default-topic"},
                "actionSets": {"run": [
                    {"id": "out", "type": "scramda2",
                     "prompt": "Write about {topic}", "examples": []},
                ]},
            }
            engine.run_from_data(wf, auto=True)
        body = json.loads(mock_open.call_args[0][0].data.decode())
        contents = " ".join(m.get("content", "") for m in body["messages"])
        self.assertIn("default-topic", contents)

    def test_multi_step_result_flows_forward(self):
        """Result from step 1 is available to step 2."""
        with patch('urllib.request.urlopen',
                   return_value=_make_scramda2_response("summarised_content")), \
                patch.object(io, 'get', return_value=_ApprovingIO()):
            wf = _wf({
                "s1": [{"id": "summary", "type": "scramda2",
                        "prompt": "Summarise", "examples": []}],
                "s2": [{"id": "result", "type": "runCode", "language": "python",
                        "source": "import sys; print(sys.stdin.read().upper())",
                        "stdin": "summary"}],
            }, steps=["s1", "s2"])
            result = engine.run_from_data(wf, auto=True)
        self.assertIn("SUMMARISED_CONTENT", result["result"])

    def test_schema_key_forwarded_to_handler(self):
        """__schema__ is no longer RESERVED — transformData can find it as a source key."""
        # With no includedData, all keys pass through including __schema__.
        # transformData finds the source and returns a result under "checker".
        wf = _wf({"run": [
            {"id": "checker", "type": "transformData",
             "source": "__schema__", "method": "parseLines"},
        ]})
        result = engine.run_from_data(
            wf, initial_data={"__schema__": "line1\nline2"}, auto=True
        )
        self.assertIn("checker", result)

    def test_empty_workflow_returns_initial_data(self):
        wf = _wf({"run": []})
        result = engine.run_from_data(wf, initial_data={"x": 1}, auto=True)
        self.assertEqual(result["x"], 1)

    def test_label_does_not_crash(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "print(1)"}]})
        # Should not raise regardless of label value
        with patch.object(io, 'get', return_value=_ApprovingIO()):
            engine.run_from_data(wf, label="my-run-label", auto=True)


class TestRunFromDataAutoContext(unittest.TestCase):

    # In auto mode humanDecision dispatches a real scramda2 action so the model
    # call rides the bus, so the seam is the connector, not a private helper.
    @patch.object(scramda2_actions.gopher, 'fire', return_value="ai-decided")
    def test_auto_context_forwarded_to_human_decision(self, mock_s):
        wf = {
            "workflow": {"steps": ["ask"]},
            "autoContext": "You are a test assistant",
            "actionSets": {"ask": [
                {"id": "ans", "type": "humanDecision", "prompt": "What to do?"},
            ]},
        }
        result = engine.run_from_data(wf, auto=True)
        self.assertEqual(result["ans"], "ai-decided")
        sent_prompt = mock_s.call_args[0][0]
        self.assertIn("You are a test assistant", sent_prompt)


if __name__ == '__main__':
    unittest.main()
