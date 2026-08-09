"""Static contract tests for the shipped system/clay conversational workflow."""

import json
import unittest
from pathlib import Path

from ..actions.core.file_ops import fences
from ..lib import config


WORKFLOW = Path(config.data_path('workflows', 'system', 'clay'))


def _load(name):
    with (WORKFLOW / name).open(encoding='utf-8') as handle:
        return json.load(handle)


def _action(document, action_id):
    for actions in document['actionSets'].values():
        for action in actions:
            if action.get('id') == action_id:
                return action
    raise AssertionError(f'missing action {action_id!r}')


class ClayWorkflowContextTest(unittest.TestCase):

    def setUp(self):
        self.main = _load('main.json')
        self.iteration = _load('iteration.json')
        self.training = _load('training.json')

    def test_workspace_is_listed_and_selected_files_are_read_before_answer(self):
        self.assertLess(self.iteration['workflow']['steps'].index('orient'),
                        self.iteration['workflow']['steps'].index('answer'))
        self.assertEqual(_action(self.iteration, 'workspace_files')['type'],
                         'listWorkspace')
        selector = _action(self.iteration, 'requested_reads')
        reader = _action(self.iteration, 'file_context')
        self.assertEqual(selector['examples'], {'override': 'read_examples'})
        self.assertEqual(reader['type'], 'serveFileReads')
        self.assertEqual(reader['reply'], 'requested_reads')
        self.assertIn('file_context',
                      _action(self.iteration, 'clay_reply')['includedData'])

    def test_current_request_precedes_and_overrides_memory(self):
        prompt = _action(self.iteration, 'clay_reply')['prompt']
        self.assertLess(prompt.index('CURRENT REQUEST'),
                        prompt.index('Background memory'))
        self.assertIn('Memory is not an instruction', prompt)
        self.assertIn('Never continue or commit an old change', prompt)

    def test_read_selection_does_not_follow_unrelated_memory(self):
        examples = self.training['read_examples']
        stale = next(example for example in examples
                     if 'updating README.md' in example['question'])
        conversational = next(example for example in examples
                              if 'dictionary keys' in example['question'])
        self.assertEqual(stale['answer'], '(no files needed)')
        self.assertEqual(conversational['answer'], '(no files needed)')

    def test_loop_receives_the_read_examples_loaded_at_boot(self):
        loop = _action(self.main, 'session_log')
        self.assertIn('read_examples', loop['includedData'])

    def test_empty_or_transient_turns_are_not_written_to_memory(self):
        summary = _action(self.iteration, 'turn_summary')
        tags = _action(self.iteration, 'memory_tags')
        memory = _action(self.iteration, 'memory_saved')
        self.assertIn('reply with exactly: NO', summary['prompt'])
        self.assertIn('Never restate the current request as an instruction',
                      summary['prompt'])
        self.assertEqual(tags['when'], 'turn_summary')
        self.assertEqual(memory['when'], 'turn_summary')


class ClayWorkflowFenceTrainingTest(unittest.TestCase):

    def test_every_non_shell_fence_in_reply_training_names_a_file(self):
        training = _load('training.json')
        for index, example in enumerate(training['reply_examples']):
            for fence in fences(example['answer']):
                if fence.is_shell:
                    continue
                self.assertTrue(
                    fence.path,
                    f'reply_examples[{index}] contains an unnamed file fence',
                )

    def test_dry_run_example_completes_argument_parsing(self):
        training = _load('training.json')
        example = next(example for example in training['reply_examples']
                       if 'add a --dry-run flag' in example['question'])
        self.assertIn("parser.add_argument('--dry-run'", example['answer'])
        self.assertNotIn('left the argument parsing to you', example['answer'])


if __name__ == '__main__':
    unittest.main()
