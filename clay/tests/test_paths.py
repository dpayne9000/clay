"""Tests for lib.paths — the two bases and the one resolution rule.

Two things are being asserted here, and they are different:

  - a workflow's assets resolve against *that workflow's* directory, including
    when the workflow is nested one or two levels down
  - the project directory is fixed once and does not follow cwd around
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ..lib import paths
from ..run import engine


class TestProjectDir(unittest.TestCase):
    """The project directory is set once and read directly."""

    def setUp(self):
        self._saved = paths._project_dir

    def tearDown(self):
        paths._project_dir = self._saved

    def test_set_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            paths.set_project_dir(d)
            self.assertEqual(paths.project_dir(), os.path.realpath(d))

    def test_stored_absolute(self):
        paths.set_project_dir('.')
        self.assertTrue(os.path.isabs(paths.project_dir()))

    def test_does_not_follow_cwd(self):
        """The whole point: a later chdir must not move it.

        This is the daemon bug — clayd runs its children with cwd set to clay's
        own checkout, so anything reading cwd at call time wrote into the
        program instead of the caller's project.
        """
        with tempfile.TemporaryDirectory() as d:
            paths.set_project_dir(d)
            fixed = paths.project_dir()
            with patch('os.getcwd', return_value='/somewhere/else'):
                self.assertEqual(paths.project_dir(), fixed)

    def test_freezes_on_first_read_when_unset(self):
        paths._project_dir = None
        with tempfile.TemporaryDirectory() as d:
            with patch('os.getcwd', return_value=d):
                first = paths.project_dir()
            with patch('os.getcwd', return_value='/somewhere/else'):
                self.assertEqual(paths.project_dir(), first)


class TestWorkflowFile(unittest.TestCase):
    """The one tolerance rule: file, directory entry, or bare name."""

    def test_file_itself(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'thing.json')
            with open(target, 'w') as f:
                json.dump({}, f)
            self.assertEqual(paths.workflow_file(target), os.path.abspath(target))

    def test_directory_means_its_entry(self):
        with tempfile.TemporaryDirectory() as d:
            entry = os.path.join(d, paths.ENTRY_FILE)
            with open(entry, 'w') as f:
                json.dump({}, f)
            self.assertEqual(paths.workflow_file(d), os.path.abspath(entry))

    def test_bare_name_finds_json(self):
        """What keeps `clay workflows` honest — it prints names without .json."""
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'quick-explainer.json')
            with open(target, 'w') as f:
                json.dump({}, f)
            bare = os.path.join(d, 'quick-explainer')
            self.assertEqual(paths.workflow_file(bare), os.path.abspath(target))

    def test_missing_is_none(self):
        self.assertIsNone(paths.workflow_file('/nonexistent/nope.json'))


class TestWorkflowAsset(unittest.TestCase):
    """A workflow's assets are found beside it, or not at all."""

    def test_relative_to_the_running_workflow(self):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, 'sub.json')
            with open(target, 'w') as f:
                json.dump({}, f)
            with paths.in_workflow(d):
                self.assertEqual(paths.workflow_asset('sub.json'),
                                 os.path.abspath(target))

    def test_dotdot(self):
        with tempfile.TemporaryDirectory() as d:
            child = os.path.join(d, 'child')
            os.makedirs(child)
            target = os.path.join(d, 'sibling.json')
            with open(target, 'w') as f:
                json.dump({}, f)
            with paths.in_workflow(child):
                self.assertEqual(paths.workflow_asset('../sibling.json'),
                                 os.path.abspath(target))

    def test_no_cwd_fallback(self):
        """A file in the process directory must not shadow the workflow's own.

        This is the behaviour the old resolve_file had: a `goal.json` sitting in
        whatever directory clay happened to be launched from would be picked up
        instead of the one the workflow shipped with, producing a run that could
        not be reproduced anywhere else.
        """
        with tempfile.TemporaryDirectory() as launched_from:
            decoy = os.path.join(launched_from, 'goal.json')
            with open(decoy, 'w') as f:
                json.dump({"decoy": True}, f)
            with tempfile.TemporaryDirectory() as workflow_dir:
                with patch('os.getcwd', return_value=launched_from):
                    with paths.in_workflow(workflow_dir):
                        self.assertIsNone(paths.workflow_asset('goal.json'))

    def test_absolute_passes_through(self):
        with tempfile.TemporaryDirectory() as d:
            with paths.in_workflow(d):
                self.assertEqual(paths.workflow_asset('/tmp/x.json'), '/tmp/x.json')

    def test_none_without_a_running_workflow(self):
        self.assertIsNone(paths.current_workflow())
        self.assertIsNone(paths.workflow_asset('anything.json'))

    def test_stack_pops_on_exception(self):
        depth = len(paths._stack)
        with self.assertRaises(RuntimeError):
            with paths.in_workflow('/tmp'):
                raise RuntimeError('boom')
        self.assertEqual(len(paths._stack), depth)

    def test_nesting(self):
        with tempfile.TemporaryDirectory() as outer:
            inner = os.path.join(outer, 'inner')
            os.makedirs(inner)
            with paths.in_workflow(outer):
                with paths.in_workflow(inner):
                    self.assertEqual(paths.current_workflow(),
                                     os.path.abspath(inner))
                self.assertEqual(paths.current_workflow(),
                                 os.path.abspath(outer))


class TestNestedWorkflowResolution(unittest.TestCase):
    """Integration: each nested workflow resolves against its own directory."""

    @patch('builtins.input', return_value='test')
    def test_run_leaves_no_engine_keys_in_the_result(self, _input):
        with tempfile.TemporaryDirectory() as d:
            wf = os.path.join(d, 'main.json')
            with open(wf, 'w') as f:
                json.dump({
                    "workflow": {"steps": ["s1"]},
                    "actionSets": {"s1": [
                        {"id": "out", "type": "humanDecision", "prompt": "Go:"}
                    ]}
                }, f)
            result = engine.run(wf)
            self.assertIn('out', result)
            self.assertNotIn('__workflow_dir__', result)

    @patch('builtins.input', return_value='test')
    def test_sub_workflow_loads_its_own_asset(self, _input):
        with tempfile.TemporaryDirectory() as d:
            sub_dir = os.path.join(d, 'sub')
            os.makedirs(sub_dir)

            with open(os.path.join(sub_dir, 'data.json'), 'w') as f:
                json.dump({"loaded_key": "loaded_value"}, f)

            with open(os.path.join(sub_dir, 'child.json'), 'w') as f:
                json.dump({
                    "workflow": {"steps": ["load"]},
                    "actionSets": {"load": [
                        {"id": "ctx", "type": "loadContext", "file": "./data.json"}
                    ]}
                }, f)

            parent_wf = os.path.join(d, 'parent.json')
            with open(parent_wf, 'w') as f:
                json.dump({
                    "workflow": {"steps": ["run_sub"]},
                    "actionSets": {"run_sub": [
                        {"id": "result", "type": "workflow", "file": "./sub/child.json"}
                    ]}
                }, f)

            result = engine.run(parent_wf)
            self.assertEqual(result.get('result', {}).get('loaded_key'),
                             'loaded_value')

    @patch('builtins.input', return_value='test')
    def test_stack_unwinds_after_a_sub_workflow(self, _input):
        """The parent's directory is back on top once the child returns."""
        with tempfile.TemporaryDirectory() as d:
            sub_dir = os.path.join(d, 'sub')
            os.makedirs(sub_dir)
            with open(os.path.join(sub_dir, 'child.json'), 'w') as f:
                json.dump({"workflow": {"steps": []}, "actionSets": {}}, f)
            parent_wf = os.path.join(d, 'parent.json')
            with open(parent_wf, 'w') as f:
                json.dump({
                    "workflow": {"steps": ["run_sub"]},
                    "actionSets": {"run_sub": [
                        {"id": "result", "type": "workflow", "file": "./sub/child.json"}
                    ]}
                }, f)
            engine.run(parent_wf)
            self.assertEqual(paths._stack, [])

    @patch('builtins.input', return_value='test')
    def test_loop_resolves_iteration_file_relative(self, _input):
        with tempfile.TemporaryDirectory() as d:
            sub_dir = os.path.join(d, 'loops')
            os.makedirs(sub_dir)

            with open(os.path.join(sub_dir, 'iter.json'), 'w') as f:
                json.dump({
                    "workflow": {"steps": ["work"]},
                    "actionSets": {"work": [
                        {"id": "answer", "type": "shell",
                         "command": "echo iteration-ok", "timeout": 5}
                    ]}
                }, f)

            parent = os.path.join(d, 'main.json')
            with open(parent, 'w') as f:
                json.dump({
                    "workflow": {"steps": ["run_loop"]},
                    "actionSets": {"run_loop": [
                        {"id": "loop_out", "type": "loop",
                         "file": "./loops/iter.json",
                         "iterations": 1, "outputKey": "answer"}
                    ]}
                }, f)

            result = engine.run(parent)
            self.assertIn('answer', result.get('loop_out', {}))

    def test_run_from_data_has_no_workflow_directory(self):
        """JSON off the wire has no directory, and loadContext says so.

        Previously this fell back to the process directory, so an API-submitted
        workflow read files out of whatever directory clayd was started in.
        """
        result = engine.run_from_data({
            "workflow": {"steps": ["load"]},
            "actionSets": {"load": [
                {"id": "ctx", "type": "loadContext", "file": "./data.json"}
            ]}
        })
        self.assertNotIn('ctx', result)
        self.assertNotIn('__workflow_dir__', result)


if __name__ == '__main__':
    unittest.main()
