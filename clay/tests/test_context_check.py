import json
import tempfile
import unittest
from pathlib import Path

from clay.context_check import inspect_workflow


class ContextCheckTest(unittest.TestCase):
    def test_reports_exact_resolved_prompt_sent_by_scramda_handler(self):
        workflow = {
            'defaults': {'audience': 'developers'},
            'workflow': {'steps': ['ask']},
            'actionSets': {'ask': [{
                'id': 'answer',
                'type': 'scramda2',
                'prompt': 'Explain {topic} to {audience}.',
                'includedData': ['topic', 'audience'],
            }]},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'main.json'
            path.write_text(json.dumps(workflow), encoding='utf-8')
            rows = inspect_workflow(str(path), {'topic': 'loops'})

        self.assertEqual(rows[0].characters, len('Explain loops to developers.'))
        self.assertEqual(rows[0].unresolved, ())

    def test_marks_runtime_action_output_as_unresolved(self):
        workflow = {
            'workflow': {'steps': ['run']},
            'actionSets': {'run': [
                {'id': 'question', 'type': 'humanDecision', 'prompt': '> '},
                {'id': 'answer', 'type': 'scramda2',
                 'prompt': 'Answer {question}', 'includedData': ['question']},
            ]},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'main.json'
            path.write_text(json.dumps(workflow), encoding='utf-8')
            rows = inspect_workflow(str(path))

        self.assertEqual(rows[0].characters, len('Answer {question}'))
        self.assertEqual(rows[0].unresolved, ('question',))

    def test_context_fixture_supplies_runtime_action_output(self):
        workflow = {
            'workflow': {'steps': ['run']},
            'actionSets': {'run': [
                {'id': 'question', 'type': 'humanDecision', 'prompt': '> '},
                {'id': 'answer', 'type': 'scramda2',
                 'prompt': 'Answer {question}', 'includedData': ['question']},
            ]},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'main.json'
            path.write_text(json.dumps(workflow), encoding='utf-8')
            rows = inspect_workflow(str(path), {'question': 'carefully'})

        self.assertEqual(rows[0].characters, len('Answer carefully'))
        self.assertEqual(rows[0].unresolved, ())
