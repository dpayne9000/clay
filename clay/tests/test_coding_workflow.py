"""Static contract tests for the shipped system/coding workflow."""

import json
import unittest
from pathlib import Path

from ..lib import config


WORKFLOW = Path(config.data_path('workflows', 'system', 'coding'))


def _load(name):
    with (WORKFLOW / name).open(encoding='utf-8') as handle:
        return json.load(handle)


def _action(document, action_id):
    for actions in document['actionSets'].values():
        for action in actions:
            if action.get('id') == action_id:
                return action
    raise AssertionError(f'missing action {action_id!r}')


class CodingFileContextTest(unittest.TestCase):
    """serveFileReads returns '' when the evidence pass emitted NO_ACTION,
    and process_steps stores that empty string over the declared default."""

    def setUp(self):
        self.iteration = _load('iteration.json')

    def test_no_files_default_is_restored_after_the_read(self):
        gate = _action(self.iteration, 'files_read')
        self.assertEqual(gate['type'], 'matchText')
        self.assertEqual(gate['source'], 'file_context')
        self.assertEqual(gate['values'], [''])
        self.assertEqual(gate['onMatch'], 'no')

        restore = _action(self.iteration, 'no_files')
        self.assertEqual(restore['whenNot'], 'files_read')
        self.assertEqual(restore['file'], './no-files.json')

    def test_restored_value_matches_the_declared_default(self):
        self.assertEqual(_load('no-files.json')['file_context'],
                         self.iteration['defaults']['file_context'])

    def test_the_gate_runs_after_the_read(self):
        order = [action['id'] for action in
                 self.iteration['actionSets']['read']]
        self.assertEqual(order, ['file_context', 'files_read', 'no_files'])
        steps = self.iteration['workflow']['steps']
        self.assertLess(steps.index('read'), steps.index('act'))

    def test_the_no_evidence_training_shape_is_now_reachable(self):
        """agent_examples taught a CURRENT FILES block the workflow could not
        produce until the default was restored."""
        restored = _load('no-files.json')['file_context']
        examples = _load('training.json')['agent_examples']
        self.assertTrue(
            any(restored in example['input'] for example in examples),
            'no agent example uses the restored no-evidence text',
        )


class CodingDeadDefaultTest(unittest.TestCase):

    def test_command_output_carries_no_unreachable_default(self):
        """runReplyCommands is ungated and returns '' with no bash fence, and
        appendTranscript skips an empty entry, so the old default was never
        read by anything."""
        iteration = _load('iteration.json')
        self.assertNotIn('command_output', iteration['defaults'])
        self.assertIsNone(_action(iteration, 'command_output').get('when'))


if __name__ == '__main__':
    unittest.main()
