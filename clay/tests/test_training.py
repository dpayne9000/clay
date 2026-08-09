"""
Training example system tests.

Covers:
  training.json structure    — all 13 keys present, each a non-empty list of
                               {"question", "answer"} few-shot examples
  loadContext handler        — loads file, returns merge=True, all keys unpacked into previous_data
  examples wiring            — scramda2 actions receive the example lists via
                               {"override": "training_key"} resolved by the dispatcher
  pipeline file structure    — research.json, draft-document.json, review.json each load training
                               at the first step and wire examples in every mapped scramda2 action
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ..actions.agent import context_actions
from ..lib import config
from ..run import engine, io
from ..run.dispatcher import _resolve_action_fields


# The packaged copy, not $CLAY_HOME's. templates/ is seeded into the user
# directory, and seeding copies once and never overwrites — so the user's copy
# is whatever shipped the day they first ran clay, and asserting on it would
# test their install rather than this checkout.
_RESEARCH = config.data_path('workflows', 'templates', 'research')

TRAINING_PATH = os.path.join(_RESEARCH, 'training.json')
PIPELINE_DIR  = os.path.join(_RESEARCH, 'pipelines')

EXPECTED_KEYS = {
    'training_generate_queries',
    'training_simulate_sources',
    'training_extract_facts',
    'training_extract_themes',
    'training_synthesise',
    'training_outline',
    'training_exec_summary',
    'training_background',
    'training_findings',
    'training_recommendations',
    'training_assemble',
    'training_critique',
    'training_apply_feedback',
}

# Maps each pipeline filename → {action_id: training_key} for all scramda2 actions
PIPELINE_KEY_MAP = {
    'research.json': {
        'search_queries': 'training_generate_queries',
        'source_content': 'training_simulate_sources',
        'key_facts':      'training_extract_facts',
        'key_themes':     'training_extract_themes',
        'final':          'training_synthesise',
    },
    'draft-document.json': {
        'outline':          'training_outline',
        'exec_summary':     'training_exec_summary',
        'background':       'training_background',
        'findings':         'training_findings',
        'recommendations':  'training_recommendations',
        'final':            'training_assemble',
    },
    'review.json': {
        'critique': 'training_critique',
        'final':    'training_apply_feedback',
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_training():
    with open(TRAINING_PATH) as f:
        return json.load(f)


def _load_pipeline(filename):
    with open(os.path.join(PIPELINE_DIR, filename)) as f:
        return json.load(f)


def _find_actions_by_id(pipeline, action_id):
    """Return all actions with the given id across all steps."""
    results = []
    for actions in pipeline.get('actionSets', {}).values():
        for action in actions:
            if action.get('id') == action_id:
                results.append(action)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# training.json structure
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingJsonStructure(unittest.TestCase):

    def setUp(self):
        self.data = _load_training()

    def test_file_exists(self):
        self.assertTrue(os.path.exists(TRAINING_PATH),
                        f"training.json not found at {TRAINING_PATH}")

    def test_is_valid_json_object(self):
        self.assertIsInstance(self.data, dict)

    def test_all_13_expected_keys_present(self):
        missing = EXPECTED_KEYS - set(self.data.keys())
        self.assertEqual(missing, set(), f"Missing training keys: {missing}")

    def test_no_unexpected_keys(self):
        extra = set(self.data.keys()) - EXPECTED_KEYS
        self.assertEqual(extra, set(), f"Unexpected training keys: {extra}")

    def test_all_values_are_nonempty_example_lists(self):
        for key, val in self.data.items():
            self.assertIsInstance(val, list,
                                  f"Key '{key}' has non-list value: {type(val)}")
            self.assertTrue(val, f"Key '{key}' has an empty example list")

    def test_all_examples_have_question_and_answer_strings(self):
        for key, val in self.data.items():
            for i, example in enumerate(val):
                self.assertIsInstance(example, dict, f"{key}[{i}] is not a dict")
                for field in ('question', 'answer'):
                    self.assertIsInstance(example.get(field), str,
                                          f"{key}[{i}].{field} missing or non-string")
                    self.assertTrue(example[field].strip(),
                                    f"{key}[{i}].{field} is empty")

    def test_no_duplicate_values(self):
        values = [json.dumps(v, sort_keys=True) for v in self.data.values()]
        self.assertEqual(len(values), len(set(values)),
                         "Duplicate training values found across keys")

    def test_all_key_names_follow_training_prefix_convention(self):
        for key in self.data:
            self.assertTrue(key.startswith('training_'),
                            f"Key '{key}' does not follow training_* convention")

    def test_all_key_names_are_lowercase(self):
        for key in self.data:
            self.assertEqual(key, key.lower(),
                             f"Key '{key}' contains uppercase characters")


# ─────────────────────────────────────────────────────────────────────────────
# loadContext handler
# ─────────────────────────────────────────────────────────────────────────────

class _ApprovingIO:
    """Answers every prompt 'y'. `shell` reaches approval.confirm()
    (required=True, 573aee4) even for a plain 'echo hello'."""

    def prompt(self, prompt_id, text):
        return 'y'


class TestLoadContextHandler(unittest.TestCase):

    def test_loads_training_json_returns_merge_true(self):
        action = {"id": "_training", "type": "loadContext", "file": TRAINING_PATH}
        result = context_actions.load_handler(action, {})
        self.assertIsNotNone(result)
        self.assertTrue(result.get("merge"),
                        "loadContext must return merge=True so keys unpack into previous_data")

    def test_returned_data_is_dict(self):
        action = {"id": "_training", "type": "loadContext", "file": TRAINING_PATH}
        result = context_actions.load_handler(action, {})
        self.assertIsInstance(result["data"], dict)

    def test_all_training_keys_in_returned_data(self):
        action = {"id": "_training", "type": "loadContext", "file": TRAINING_PATH}
        result = context_actions.load_handler(action, {})
        returned_keys = set(result["data"].keys())
        self.assertEqual(returned_keys, EXPECTED_KEYS,
                         f"Missing: {EXPECTED_KEYS - returned_keys}, Extra: {returned_keys - EXPECTED_KEYS}")

    def test_process_steps_unpacks_all_training_keys(self):
        steps = ["load_training"]
        actions = {
            "load_training": [{"id": "_training", "type": "loadContext", "file": TRAINING_PATH}]
        }
        result = engine.process_steps(steps, actions)
        for key in EXPECTED_KEYS:
            self.assertIn(key, result,
                          f"Key '{key}' was not unpacked into previous_data after loadContext")

    def test_training_values_preserved_after_unpack(self):
        steps = ["load_training"]
        actions = {
            "load_training": [{"id": "_training", "type": "loadContext", "file": TRAINING_PATH}]
        }
        result = engine.process_steps(steps, actions)
        training = _load_training()
        for key in EXPECTED_KEYS:
            self.assertEqual(result[key], training[key],
                             f"Value mismatch for '{key}' after unpack")

    def test_merge_does_not_store_under_action_id(self):
        steps = ["load_training"]
        actions = {
            "load_training": [{"id": "_training", "type": "loadContext", "file": TRAINING_PATH}]
        }
        result = engine.process_steps(steps, actions)
        # The action id "_training" must NOT appear as a key — merge unpacks contents
        self.assertNotIn("_training", result,
                         "loadContext action id should not appear as a key when merge=True")

    def test_missing_file_returns_none(self):
        action = {"id": "t", "type": "loadContext", "file": "/nonexistent/path/training.json"}
        result = context_actions.load_handler(action, {})
        self.assertIsNone(result)

    def test_missing_file_field_returns_none(self):
        action = {"id": "t", "type": "loadContext"}
        result = context_actions.load_handler(action, {})
        self.assertIsNone(result)

    def test_non_object_json_returns_none(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(["a", "b", "c"], f)
            path = f.name
        try:
            result = context_actions.load_handler({"id": "t", "type": "loadContext", "file": path}, {})
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_unparseable_json_loads_as_text_under_the_action_id(self):
        """Training files are JSON, but loadContext also carries prose.

        A file that does not parse takes the text path and lands under the
        action's id — which is why the merge tests above assert on `merge`
        rather than just on the data: text loads without it.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{broken json")
            path = f.name
        try:
            result = context_actions.load_handler({"id": "t", "type": "loadContext", "file": path}, {})
            self.assertEqual(result, {"id": "t", "data": "{broken json"})
        finally:
            os.unlink(path)

    def test_existing_previous_data_not_clobbered(self):
        """loadContext must not erase keys that were in previous_data before it ran."""
        steps = ["setup", "load_training"]
        actions = {
            "setup": [{"id": "pre_existing", "type": "shell",
                       "command": "echo hello", "timeout": 5}],
            "load_training": [{"id": "_training", "type": "loadContext", "file": TRAINING_PATH}]
        }
        with patch.object(io, 'get', return_value=_ApprovingIO()):
            result = engine.process_steps(steps, actions)
        self.assertIn("pre_existing", result,
                      "pre-existing key 'pre_existing' was lost after loadContext merge")


# ─────────────────────────────────────────────────────────────────────────────
# Template substitution
# ─────────────────────────────────────────────────────────────────────────────

class TestTrainingExamplesWiring(unittest.TestCase):
    """
    Pipelines feed training examples to scramda2 through
    {"override": "training_key"} on the examples field, which the dispatcher
    resolves against the loaded training context (_resolve_action_fields).
    """

    def setUp(self):
        self._training = _load_training()

    def test_examples_override_resolves_to_training_list(self):
        for filename, key_map in PIPELINE_KEY_MAP.items():
            p = _load_pipeline(filename)
            for action_id, training_key in key_map.items():
                for action in [a for a in _find_actions_by_id(p, action_id)
                               if a.get('type') == 'scramda2']:
                    resolved = _resolve_action_fields(action, self._training)
                    self.assertEqual(resolved.get('examples'),
                                     self._training[training_key],
                                     f"{filename} action '{action_id}': examples did not "
                                     f"resolve to training['{training_key}']")

    def test_unknown_override_key_left_unresolved(self):
        resolved = _resolve_action_fields(
            {"id": "x", "type": "scramda2", "prompt": "p",
             "examples": {"override": "training_nonexistent"}},
            self._training)
        self.assertEqual(resolved["examples"], {"override": "training_nonexistent"},
                         "Unknown override key should be left in place, not blanked")

    def test_process_steps_makes_training_usable_in_shell(self):
        """
        After loadContext, a shell echo referencing a training key should
        have the value substituted (shell _SafeMap strips injection chars,
        but the key is accessible).
        """
        steps = ["load_training", "echo_key"]
        actions = {
            "load_training": [{"id": "_training", "type": "loadContext", "file": TRAINING_PATH}],
            "echo_key": [{"id": "echo_result", "type": "shell",
                          "command": "echo present",
                          "includedData": ["training_generate_queries"],
                          "timeout": 5}],
        }
        with patch.object(io, 'get', return_value=_ApprovingIO()):
            result = engine.process_steps(steps, actions)
        self.assertIn("echo_result", result,
                      "Shell step after loadContext failed — training key not available")


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline file structure
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineFiles(unittest.TestCase):

    def test_each_pipeline_file_exists(self):
        for filename in PIPELINE_KEY_MAP:
            path = os.path.join(PIPELINE_DIR, filename)
            self.assertTrue(os.path.exists(path), f"Pipeline file not found: {path}")

    def test_each_pipeline_is_valid_json(self):
        for filename in PIPELINE_KEY_MAP:
            path = os.path.join(PIPELINE_DIR, filename)
            with open(path) as f:
                data = json.load(f)
            self.assertIsInstance(data, dict, f"{filename} is not a JSON object")

    def test_each_pipeline_has_load_training_step(self):
        for filename in PIPELINE_KEY_MAP:
            p = _load_pipeline(filename)
            self.assertIn('load_training', p['workflow']['steps'],
                          f"{filename}: 'load_training' step missing from workflow.steps")

    def test_load_training_is_first_step(self):
        for filename in PIPELINE_KEY_MAP:
            p = _load_pipeline(filename)
            steps = p['workflow']['steps']
            self.assertEqual(steps[0], 'load_training',
                             f"{filename}: 'load_training' must be first step, got '{steps[0]}'")

    def test_load_training_action_is_loadContext_type(self):
        for filename in PIPELINE_KEY_MAP:
            p = _load_pipeline(filename)
            action = p['actionSets']['load_training'][0]
            self.assertEqual(action.get('type'), 'loadContext',
                             f"{filename}: load_training action must be type 'loadContext'")

    def test_load_training_action_points_to_training_json(self):
        for filename in PIPELINE_KEY_MAP:
            p = _load_pipeline(filename)
            action = p['actionSets']['load_training'][0]
            # Pipelines reference training.json relative to their own directory;
            # paths.workflow_asset resolves it against the running workflow.
            self.assertEqual(action.get('file'), '../training.json',
                             f"{filename}: loadContext file path mismatch")

    def test_each_scramda2_action_has_examples_override(self):
        for filename, key_map in PIPELINE_KEY_MAP.items():
            p = _load_pipeline(filename)
            for action_id, training_key in key_map.items():
                matches = [a for a in _find_actions_by_id(p, action_id)
                           if a.get('type') == 'scramda2']
                for action in matches:
                    self.assertEqual(action.get('examples'),
                                     {"override": training_key},
                                     f"{filename} action '{action_id}': examples must be "
                                     f"{{'override': '{training_key}'}}")

    def test_each_scramda2_action_receives_its_training_examples(self):
        """End-to-end check that the examples actually arrive.

        Training data reaches the model through the examples field, not the
        prompt: loadContext merges training.json into previous_data, then
        dispatch() calls _resolve_action_fields, which swaps
        {"override": "training_key"} for the real list before the handler
        passes it to the model as examples=.

        This runs the pipelines' own load_training step to build the context,
        so it covers the whole chain rather than a hand-built dict the way
        TestTrainingExamplesWiring does.
        """
        context = engine.process_steps(
            ["load_training"],
            {"load_training": [{"id": "_training", "type": "loadContext",
                                "file": TRAINING_PATH}]})
        training = _load_training()

        for filename, key_map in PIPELINE_KEY_MAP.items():
            p = _load_pipeline(filename)
            for action_id, training_key in key_map.items():
                matches = [a for a in _find_actions_by_id(p, action_id)
                           if a.get('type') == 'scramda2']
                self.assertTrue(matches,
                                f"{filename}: no scramda2 action with id '{action_id}' "
                                f"— PIPELINE_KEY_MAP and the pipeline disagree")
                for action in matches:
                    resolved = _resolve_action_fields(action, context)
                    self.assertEqual(resolved.get('examples'), training[training_key],
                                     f"{filename} action '{action_id}': examples did not "
                                     f"resolve to training['{training_key}'] after loadContext")
                    self.assertTrue(resolved.get('examples'),
                                    f"{filename} action '{action_id}': resolved examples "
                                    f"are empty — the model would get no few-shot data")

    def test_load_training_actionset_has_exactly_one_action(self):
        for filename in PIPELINE_KEY_MAP:
            p = _load_pipeline(filename)
            count = len(p['actionSets']['load_training'])
            self.assertEqual(count, 1,
                             f"{filename}: 'load_training' actionSet should have 1 action, got {count}")


if __name__ == '__main__':
    unittest.main()
