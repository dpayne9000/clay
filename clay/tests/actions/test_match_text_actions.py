"""Unit tests for match_text_actions handler.

The behaviour worth pinning down is what the action refuses to do. It exists
because a model was answering exact-match questions and getting them wrong in
ways a literal comparison cannot, so a test suite that only checked the happy
path would miss the whole point of it.
"""

import unittest
from unittest.mock import patch

from ...actions import match_text_actions
from ...lib.flags import is_truthy


def _run(ctx, **fields):
    action = {"id": "out", "source": "text", **fields}
    return match_text_actions.handler(action, ctx)


class MatchTest(unittest.TestCase):

    VALUES = ["quit", "exit", "bye"]

    def test_an_exact_value_matches(self):
        self.assertEqual(
            "yes", _run({"text": "quit"}, values=self.VALUES)["data"])

    def test_matching_ignores_case_and_surrounding_space(self):
        self.assertEqual(
            "yes", _run({"text": "  QUIT \n"}, values=self.VALUES)["data"])

    def test_anything_else_misses(self):
        self.assertEqual(
            "no", _run({"text": "carry on"}, values=self.VALUES)["data"])

    def test_a_value_inside_a_longer_string_is_not_a_match(self):
        """Whole-string only, and deliberately.

        Substring matching would make a values list holding 'no' fire on
        'no, make it blue' — a gate that guesses is worse than one that asks.
        """
        self.assertEqual(
            "no", _run({"text": "quit stalling"}, values=self.VALUES)["data"])
        self.assertEqual(
            "no", _run({"text": "please quit"}, values=self.VALUES)["data"])


class MissingInputTest(unittest.TestCase):

    def test_a_key_nothing_produced_is_a_miss_not_a_failure(self):
        # A gate on an action that has not run is a workflow error the
        # dispatcher already warns about. Failing here too would turn a soft
        # branch into a dead run.
        self.assertEqual("no", _run({}, values=["quit"])["data"])

    def test_none_and_empty_are_misses(self):
        self.assertEqual("no", _run({"text": None}, values=["quit"])["data"])
        self.assertEqual("no", _run({"text": "   "}, values=["quit"])["data"])

    def test_an_empty_value_matches_an_empty_source(self):
        self.assertEqual("yes", _run({"text": ""}, values=[""])["data"])


class BadContractTest(unittest.TestCase):

    def test_no_source_returns_none(self):
        with patch("builtins.print"):
            result = match_text_actions.handler(
                {"id": "out", "values": ["quit"]}, {"text": "quit"})
        self.assertIsNone(result)

    def test_values_must_be_a_non_empty_list(self):
        with patch("builtins.print"):
            self.assertIsNone(_run({"text": "quit"}))
            self.assertIsNone(_run({"text": "quit"}, values=[]))
            self.assertIsNone(_run({"text": "quit"}, values="quit"))


class OutputStringTest(unittest.TestCase):

    def test_the_two_outputs_can_be_named(self):
        result = _run({"text": "quit"}, values=["quit"],
                      onMatch="STOP", onMiss="GO")
        self.assertEqual("STOP", result["data"])

    def test_an_empty_string_is_kept_rather_than_defaulted(self):
        """'' is how is_truthy spells no, so a gate needs to be able to emit it.

        Reading it through .get(key, default) would have replaced a deliberate
        '' with 'yes' and inverted the branch.
        """
        result = _run({"text": "quit"}, values=["quit"], onMatch="", onMiss="on")
        self.assertEqual("", result["data"])
        self.assertFalse(is_truthy(result["data"]))

    def test_the_output_key_is_the_action_id(self):
        self.assertEqual("out", _run({"text": "x"}, values=["quit"])["id"])


class ContinueGateTest(unittest.TestCase):
    """The case it was written for: system/coding3's keep_going.

    A loop's continueKey reads its value through is_truthy, so what matters is
    not the string but which side of that function it lands on.
    """

    WORDS = ["quit", "exit", "bye", "done", "stop", "q"]

    def _keep_going(self, said):
        return _run({"text": said}, values=self.WORDS,
                    onMatch="no", onMiss="yes")["data"]

    def test_a_quit_word_ends_the_session(self):
        for word in self.WORDS:
            self.assertFalse(is_truthy(self._keep_going(word)), word)

    def test_a_quit_word_with_punctuation_or_case_still_ends_it(self):
        self.assertFalse(is_truthy(self._keep_going("QUIT")))
        self.assertFalse(is_truthy(self._keep_going(" bye ")))

    def test_a_real_request_continues(self):
        for said in ("add a test for the parser", "what does store.py do?",
                     "no, use a tuple instead", "done with that, now do the CLI"):
            self.assertTrue(is_truthy(self._keep_going(said)), said)

    def test_the_answer_can_no_longer_be_phrased_wrong(self):
        """The failure this action replaces.

        keep_going was a model answering YES or NO, and FALSY_WORDS holds 'no'
        but not 'no.' — so a model replying "NO.", meaning do not continue, was
        read as truthy and the session carried on after the user asked to end
        it. That class of failure is gone because the two outputs are fixed
        strings this action chooses between, not text a model composes.
        """
        self.assertEqual("no", self._keep_going("quit"))
        self.assertEqual("yes", self._keep_going("add a test"))

    def test_a_trailing_full_stop_on_the_users_own_word_is_a_miss(self):
        """The limitation, stated rather than hidden.

        'quit.' is not 'quit', so the session continues. That is the safe
        direction — a session that should have ended is one keypress from
        ending, where one that ends early has thrown away the context — and the
        fix when it matters is to name the variant in `values`, not to teach
        this action to guess at punctuation.
        """
        self.assertEqual("yes", self._keep_going("quit."))
        self.assertEqual("no", _run({"text": "quit."},
                                    values=self.WORDS + ["quit."],
                                    onMatch="no", onMiss="yes")["data"])


if __name__ == "__main__":
    unittest.main()
