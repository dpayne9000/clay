"""Integration tests for terminal stdout formatting.

The engine emits events; a TerminalRenderer attached in _capture draws them.
Tests the visual output for engine._execute(), engine.process_steps(), and
dispatcher.dispatch():
  - ═══ dividers at start/end of a run
  - Workflow label and [auto] flag
  - log path line
  - ── step ─── step-separator lines
  - ▸ type → id action lines
  - Result preview lines (short content printed below the action line)
  - Silent-result types (humanDecision, loop, workflow) skip the preview
"""

import io
import sys
import unittest
from unittest.mock import patch

from ...run import engine
from ...run import termui
from ...run.renderers.terminal import TerminalRenderer

_prev_plain = termui.PLAIN


def setUpModule():
    # Force plain-mode output so assertions don't depend on whether the test
    # run happens in a TTY (rich mode uses themed banners with different chars).
    termui.set_plain(True)


def tearDownModule():
    termui.set_plain(_prev_plain)


def _capture(fn, *args, **kwargs):
    """Call fn with a terminal renderer attached; return captured stdout.

    The engine no longer prints — the renderer subscribed to the event bus
    does — so every capture goes through the same path the CLI uses.
    """
    renderer = TerminalRenderer()
    renderer.attach()
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
        renderer.detach()
    return buf.getvalue()


def _wf(action_sets, steps=None):
    return {
        "workflow": {"steps": steps or list(action_sets.keys())},
        "actionSets": action_sets,
    }


class TestRunDividers(unittest.TestCase):

    def test_opening_divider_printed(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("═" * 56, out)

    def test_closing_divider_printed(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        lines_with_dividers = [l for l in out.splitlines() if "═" * 10 in l]
        # at least opening + closing
        self.assertGreaterEqual(len(lines_with_dividers), 2)

    def test_label_appears_in_output(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, label="my-test-label", auto=True)
        self.assertIn("my-test-label", out)

    def test_auto_flag_shown_in_auto_mode(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("[auto]", out)

    def test_auto_flag_absent_when_not_auto(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        with patch('builtins.input', return_value=""):
            out = _capture(engine.run_from_data, wf, auto=False)
        self.assertNotIn("[auto]", out)

    def test_log_path_shown_in_output(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("log →", out)


class TestStepSeparator(unittest.TestCase):

    def test_step_name_printed(self):
        wf = _wf({"alpha": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("alpha", out)

    def test_step_separator_dashes(self):
        wf = _wf({"alpha": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("──", out)

    def test_multiple_steps_both_printed(self):
        wf = _wf({
            "step1": [{"id": "a", "type": "python", "code": "1"}],
            "step2": [{"id": "b", "type": "python", "code": "2"}],
        }, steps=["step1", "step2"])
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("step1", out)
        self.assertIn("step2", out)


class TestActionLine(unittest.TestCase):

    def test_action_type_printed(self):
        wf = _wf({"run": [{"id": "myid", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("python", out)

    def test_action_id_printed_after_arrow(self):
        wf = _wf({"run": [{"id": "myid", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("→ myid", out)

    def test_bullet_marker_present(self):
        wf = _wf({"run": [{"id": "v", "type": "python", "code": "1"}]})
        out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("▸", out)


class TestResultPreview(unittest.TestCase):

    def test_short_result_printed_below_action(self):
        # scramda2 result is printed below the action line
        from ...actions import scramda2_actions
        wf = _wf({"run": [{"id": "v", "type": "scramda2",
                            "prompt": "Say hello", "examples": []}]})
        with patch.object(scramda2_actions.gopher, 'fire', return_value="hello"):
            out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("hello", out)

    def test_human_decision_result_not_previewed(self):
        """humanDecision is a _SILENT_RESULT_TYPE — no preview line."""
        wf = _wf({"run": [{"id": "ans", "type": "humanDecision", "prompt": "Q?"}]})
        with patch('builtins.input', return_value="secret-answer"):
            out = _capture(engine.run_from_data, wf, auto=False)
        self.assertNotIn("secret-answer", out)

    def test_human_decision_auto_answer_is_rendered(self):
        """In auto mode the model call is a real scramda2 dispatch — the
        answer is drawn like any other model output."""
        from ...actions import scramda2_actions
        wf = _wf({"run": [{"id": "ans", "type": "humanDecision", "prompt": "Q?"}]})
        with patch.object(scramda2_actions.gopher, 'fire', return_value="ai-answer"):
            out = _capture(engine.run_from_data, wf, auto=True)
        self.assertIn("ai-answer", out)


if __name__ == '__main__':
    unittest.main()
