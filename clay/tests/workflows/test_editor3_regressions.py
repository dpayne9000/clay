import json
import unittest
from pathlib import Path


EDITOR = (Path(__file__).resolve().parents[2]
          / 'data' / 'workflows' / 'system' / 'editor3')


def _load(name):
    return json.loads((EDITOR / name).read_text(encoding='utf-8'))


def _action(document, action_id):
    return next(
        action
        for actions in document['actionSets'].values()
        for action in actions
        if action.get('id') == action_id
    )


class Editor3ObservedFailureRegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.iteration = _load('iteration.json')
        cls.file_iteration = _load('file-iteration.json')
        cls.training = _load('training.json')

    def test_design_has_contracts_and_no_workspace_listing(self):
        design = _action(self.iteration, 'design_contract')
        self.assertIn('action_contracts', design['includedData'])
        self.assertNotIn('workspace_files', design['includedData'])
        self.assertNotIn('listWorkspace', {
            action['type']
            for actions in self.iteration['actionSets'].values()
            for action in actions
        })

    def test_file_plan_requires_exact_read_marker(self):
        prompt = _action(self.file_iteration, 'file_plan')['prompt']
        self.assertIn('<read_file><path>the filename</path></read_file>', prompt)
        self.assertIn('replacing `the filename` with the PATH value', prompt)

    def test_generator_teaches_path_bearing_fence(self):
        generator = _action(self.file_iteration, 'file_reply')
        self.assertEqual(generator['examples']['override'],
                         'file_generation_examples')
        examples = self.training['file_generation_examples']
        self.assertGreaterEqual(len(examples), 3)
        for example in examples:
            path = example['question'].split('PATH: ', 1)[1].splitlines()[0]
            self.assertTrue(example['answer'].startswith(f'```json {path}\n'))
            self.assertNotIn('workflow =', example['answer'])
            self.assertNotIn('<<<<<<<', example['answer'])
            self.assertNotIn('>>>>>>>', example['answer'])

    def test_apply_error_is_consumed_by_review(self):
        review = _action(self.file_iteration, 'construction_review')
        self.assertIn('{files_written_error}', review['prompt'])
        self.assertIn('files_written_error', review['includedData'])

    def test_only_exact_done_stops_construction(self):
        review = _action(self.file_iteration, 'construction_review')
        self.assertIn('{build_progress}', review['prompt'])
        decision = _action(self.file_iteration, 'construction_decision')
        self.assertEqual(decision['type'], 'matchText')
        self.assertEqual(decision['source'], 'construction_review')
        self.assertEqual(decision['values'], ['DONE'])
        self.assertEqual(decision['onMatch'], 'no')
        self.assertEqual(decision['onMiss'], 'yes')

    def test_failed_reply_and_write_error_enter_progress(self):
        progress = _action(self.file_iteration, 'build_progress')
        self.assertIn('Reply=file_reply', progress['entries'])
        self.assertIn('WriteError=files_written_error', progress['entries'])

    def test_outer_turn_has_visible_model_summary(self):
        summary = _action(self.iteration, 'turn_summary')
        self.assertEqual(summary['type'], 'scramda2')
        self.assertIn('build_progress', summary['includedData'])
