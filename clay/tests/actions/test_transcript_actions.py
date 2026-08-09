"""Unit tests for appendTranscript — the conversational loop's rolling memory."""

import unittest

from ...actions.agent.transcript_actions import handler


def _run(entries, ctx, **extra):
    action = {"id": "transcript", "type": "appendTranscript",
              "entries": entries, **extra}
    return handler(action, ctx)


class AppendTranscriptTest(unittest.TestCase):

    def test_first_turn_starts_the_transcript(self):
        result = _run(["User=user_request", "Assistant=reply"],
                      {"user_request": "hello", "reply": "hi there"})
        self.assertEqual(result["data"], "User: hello\nAssistant: hi there")

    def test_turns_accumulate_with_a_blank_line_between(self):
        first = _run(["User=user_request"], {"user_request": "one"})
        second = _run(["User=user_request"],
                      {"transcript": first["data"], "user_request": "two"})
        self.assertEqual(second["data"], "User: one\n\nUser: two")

    def test_empty_values_are_skipped(self):
        result = _run(["User=user_request", "Files=files_written"],
                      {"user_request": "hello", "files_written": ""})
        self.assertEqual(result["data"], "User: hello")

    def test_all_empty_returns_prior_unchanged(self):
        result = _run(["Files=files_written"],
                      {"transcript": "User: old", "files_written": None})
        self.assertEqual(result["data"], "User: old")

    def test_bare_key_uses_the_key_as_label(self):
        result = _run(["user_request"], {"user_request": "hello"})
        self.assertEqual(result["data"], "user_request: hello")

    def test_transcript_key_override(self):
        result = _run(["User=user_request"],
                      {"history": "User: earlier", "user_request": "now"},
                      transcriptKey="history")
        self.assertEqual(result["data"], "User: earlier\n\nUser: now")

    def test_trim_drops_oldest_turns_at_turn_boundaries(self):
        old_turn = "User: " + "x" * 100
        result = _run(["User=user_request"],
                      {"transcript": old_turn, "user_request": "y" * 50},
                      maxChars=80)
        self.assertLessEqual(len(result["data"]), 80)
        # The surviving text is the new turn, whole — not a sliced old one.
        self.assertEqual(result["data"], "User: " + "y" * 50)

    def test_no_trim_when_under_the_cap(self):
        result = _run(["User=user_request"],
                      {"transcript": "User: old", "user_request": "new"},
                      maxChars=8000)
        self.assertEqual(result["data"], "User: old\n\nUser: new")

    def test_result_id_matches_action_id(self):
        result = _run(["User=user_request"], {"user_request": "hello"})
        self.assertEqual(result["id"], "transcript")


if __name__ == '__main__':
    unittest.main()
