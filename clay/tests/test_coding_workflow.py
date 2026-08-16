"""Static contract tests for the shipped system/coding project builder."""

import json
import unittest
from pathlib import Path

from ..lib import config


WORKFLOW = Path(config.data_path("workflows", "system", "coding"))


def _load(name):
    with (WORKFLOW / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _action(document, action_id):
    for actions in document["actionSets"].values():
        for action in actions:
            if action.get("id") == action_id:
                return action
    raise AssertionError(f"missing action {action_id!r}")


class CodingWorkflowTest(unittest.TestCase):

    def setUp(self):
        self.main = _load("main.json")
        self.iteration = _load("iteration.json")
        self.file_iteration = _load("file-iteration.json")
        self.training = _load("training.json")

    def test_uses_editor_style_plan_and_construction_loops(self):
        self.assertEqual(self.iteration["workflow"]["steps"], [
            "context", "request", "route", "design", "write_plan",
            "construct", "settle",
        ])
        construct = _action(self.iteration, "construction_result")
        self.assertEqual(construct["type"], "loop")
        self.assertEqual(construct["file"], "./file-iteration.json")
        self.assertEqual(construct["continueKey"], "construction_decision")
        self.assertTrue(construct["merge"])

    def test_design_creates_a_project_plan(self):
        design = _action(self.iteration, "design_contract")
        self.assertIn("```markdown PLAN.md", design["prompt"])
        self.assertIn("source, tests, configuration", design["prompt"])
        self.assertEqual(design["examples"],
                         {"override": "plan_file_examples"})
        self.assertEqual(_action(self.iteration, "plan_file_written")["reply"],
                         "design_contract")

    def test_each_file_is_written_verified_read_back_and_reviewed(self):
        steps = self.file_iteration["workflow"]["steps"]
        for earlier, later in (("generate", "apply"), ("apply", "verify"),
                               ("verify", "inspect"), ("inspect", "review"),
                               ("review", "update_plan")):
            self.assertLess(steps.index(earlier), steps.index(later))
        self.assertEqual(_action(self.file_iteration, "files_written")["maxFiles"], 1)
        self.assertEqual(_action(self.file_iteration, "verification_output")["type"],
                         "runReplyCommands")
        self.assertEqual(_action(self.file_iteration, "written_file_context")["type"],
                         "serveFileReads")
        review = _action(self.file_iteration, "construction_review")
        self.assertIn("{files_written_error}", review["prompt"])
        self.assertIn("{verification_output}", review["prompt"])

    def test_generation_uses_the_editor_file_fence_contract(self):
        generation = _action(self.file_iteration, "file_reply")
        prompt = generation["prompt"]
        self.assertIn("actual filename from the PATH line", prompt)
        self.assertIn("```python src/main.py", prompt)
        self.assertIn("not the example filename and not the word PATH", prompt)
        self.assertIn("Use no other fences or edit markers", prompt)

    def test_training_covers_multiple_project_ecosystems_and_file_types(self):
        plan_text = json.dumps(self.training["plan_file_examples"])
        generation_text = json.dumps(self.training["file_generation_examples"])
        for expected in ("Python", "browser", "Go"):
            self.assertIn(expected, plan_text)
        for expected in ("```python", "```javascript", "```rust",
                         "```json", "```html"):
            self.assertIn(expected, generation_text)

    def test_user_facing_summary_is_visible(self):
        summary = _action(self.iteration, "turn_summary")
        self.assertIs(summary["visible"], True)
        self.assertIn("BUILD RECORD", summary["prompt"])


if __name__ == "__main__":
    unittest.main()
