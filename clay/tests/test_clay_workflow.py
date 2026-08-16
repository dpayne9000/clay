"""Static contract tests for the shipped system/clay help chatbot."""

import json
import unittest
from pathlib import Path

from ..lib import config


WORKFLOW = Path(config.data_path("workflows", "system", "clay"))


def _load(name):
    with (WORKFLOW / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _action(document, action_id):
    for actions in document["actionSets"].values():
        for action in actions:
            if action.get("id") == action_id:
                return action
    raise AssertionError(f"missing action {action_id!r}")


class ClayWorkflowTest(unittest.TestCase):

    def setUp(self):
        self.main = _load("main.json")
        self.iteration = _load("iteration.json")
        self.context = _load("clay-context.json")

    def test_main_starts_a_self_contained_chat_loop(self):
        self.assertEqual(self.main["workflow"]["steps"], ["chat"])
        loop = _action(self.main, "chat_session")
        self.assertEqual(loop["file"], "./iteration.json")
        self.assertEqual(loop["continueKey"], "keep_going")
        self.assertEqual(loop["includedData"], [])
        self.assertEqual(_action(self.iteration, "clay_context")["file"],
                         "./clay-context.json")

    def test_reply_is_visible_and_grounded_in_clay_information(self):
        reply = _action(self.iteration, "clay_reply")
        self.assertIs(reply["visible"], True)
        self.assertEqual(reply["modelProfile"], "chat")
        self.assertIn("{clay_program}", reply["prompt"])
        self.assertIn("{transcript}", reply["prompt"])
        self.assertIn("{user_message}", reply["prompt"])
        self.assertIn("clay_program", reply["includedData"])

    def test_chat_has_transcript_continuity_and_literal_exit(self):
        transcript = _action(self.iteration, "transcript")
        self.assertEqual(transcript["type"], "appendTranscript")
        keep_going = _action(self.iteration, "keep_going")
        self.assertEqual(keep_going["type"], "matchText")
        self.assertIn("exit", keep_going["values"])
        self.assertEqual(keep_going["onMatch"], "no")

    def test_context_covers_core_clay_help_topics(self):
        guide = self.context["clay_program"]
        for topic in ("workflow.steps", "actionSets", "includedData",
                      "clay configure", "clay workflows", "clay lint",
                      "clay dryrun", "approval gates"):
            self.assertIn(topic, guide)


if __name__ == "__main__":
    unittest.main()
