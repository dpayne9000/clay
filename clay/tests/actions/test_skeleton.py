"""Tests for clay/actions/skeleton.py — the registry tree generator.

Covers the full pipeline: action() (one instrumented action, unit-level),
build() (document assembly + determinism), write() (file I/O), and the
generated tree (registry.validate(), lint's unknown-field and includedData
scope checks — see clay/lint.py). Asserts the committed tree matches a fresh
build() so staleness is a test failure rather than silent rot.
"""

import json
import os
import tempfile
import unittest

from ...actions import registry
from ...actions.registry import action as _action_decorator, req, opt
from ...actions.skeleton import WorkflowSkeleton
from ...lib import config
from ... import lint as clay_lint

#: The one committed copy, the same path clay/cli.py:build writes.
_REGISTRY_DIR = config.data_path('workflows', 'system', 'registry')


class TestWorkflowSkeletonStaleness(unittest.TestCase):
    """The committed tree is output of build() — must not drift.

    Run `clay build` and re-commit if this fails.
    """

    def setUp(self):
        registry.discover()

    def test_committed_tree_matches_fresh_build(self):
        fresh = WorkflowSkeleton().build()
        for name, doc in fresh.items():
            path = os.path.join(_REGISTRY_DIR, name)
            with open(path) as f:
                committed = json.load(f)
            self.assertEqual(committed, doc, f"{name} is stale — run `clay build`")

    def test_no_extra_or_missing_committed_files(self):
        committed_names = {f for f in os.listdir(_REGISTRY_DIR) if f.endswith('.json')}
        self.assertEqual(committed_names, set(WorkflowSkeleton().build()))


class TestWorkflowSkeletonValidation(unittest.TestCase):
    """The generated tree must pass the same checks real workflow JSON does."""

    def setUp(self):
        registry.discover()
        self.built = WorkflowSkeleton().build()

    def test_every_action_type_is_registered(self):
        for name, doc in self.built.items():
            for actions in doc.get('actionSets', {}).values():
                for action in actions:
                    self.assertIn(action['type'], registry._REGISTRY,
                                  f"{name}: unknown action type '{action['type']}'")

    def test_every_action_passes_required_field_validation(self):
        for name, doc in self.built.items():
            for step, actions in doc.get('actionSets', {}).items():
                for action in actions:
                    errors = registry.validate(action)
                    self.assertEqual(errors, [], f"{name}[{step}]: {errors}")

    def test_lint_reports_no_errors_or_warnings(self):
        # lint_dir does full cross-file analysis (parse, unknown-field check,
        # includedData scope including loadContext expansion and loop/workflow
        # includedData propagation) — this is the same check `clay lint
        # system registry` runs.
        results = clay_lint.lint_dir(_REGISTRY_DIR)
        for r in results:
            self.assertEqual(r.errors, [], f"{r.path}: {r.errors}")
            self.assertEqual(r.warnings, [], f"{r.path}: {r.warnings}")


class TestActionRendering(unittest.TestCase):
    """Unit tests for WorkflowSkeleton.action(), exhaustive over all 6 real
    skeleton=True types: id-then-type key order, required fields rendering
    as "<json_type>" markers, optional fields rendering their declared
    default (or a marker where the default is None).
    """

    def setUp(self):
        registry.discover()
        self.skel = WorkflowSkeleton()

    def test_read_file(self):
        result = self.skel.action('readFile')
        self.assertEqual(list(result), ['id', 'type', 'file', 'root', 'encoding', 'maxBytes'])
        self.assertEqual(result, {
            'id': '<string>', 'type': 'readFile', 'file': '<string>',
            'root': '.', 'encoding': 'utf-8', 'maxBytes': '<integer>',
        })

    def test_write_file(self):
        result = self.skel.action('writeFile')
        self.assertEqual(list(result), [
            'id', 'type', 'file', 'content', 'root', 'encoding', 'append',
            'createParent', 'stripCodeFence', 'requireCodeFence', 'ensureFinalNewline',
        ])
        self.assertEqual(result, {
            'id': '<string>', 'type': 'writeFile', 'file': '<string>', 'content': '<string>',
            'root': '.', 'encoding': 'utf-8', 'append': False, 'createParent': True,
            'stripCodeFence': True, 'requireCodeFence': False, 'ensureFinalNewline': False,
        })

    def test_scramda2(self):
        result = self.skel.action('scramda2')
        self.assertEqual(list(result), ['id', 'type', 'prompt', 'model', 'modelProfile', 'max_tokens', 'examples'])
        self.assertEqual(result, {
            'id': '<string>', 'type': 'scramda2', 'prompt': '<string>',
            'model': '<string>', 'modelProfile': '<string>',
            'max_tokens': '<integer>', 'examples': '<array>',
        })

    def test_human_decision(self):
        result = self.skel.action('humanDecision')
        self.assertEqual(list(result), ['id', 'type', 'prompt'])
        self.assertEqual(result, {'id': '<string>', 'type': 'humanDecision', 'prompt': '<string>'})

    def test_workflow(self):
        result = self.skel.action('workflow')
        self.assertEqual(list(result), ['id', 'type', 'file', 'outputKey'])
        self.assertEqual(result, {
            'id': '<string>', 'type': 'workflow', 'file': '<string>', 'outputKey': 'final',
        })

    def test_loop(self):
        result = self.skel.action('loop')
        self.assertEqual(list(result), ['id', 'type', 'file', 'iterations',
                                        'continueKey', 'outputKey', 'merge'])
        self.assertEqual(result, {
            'id': '<string>', 'type': 'loop', 'file': '<string>',
            'iterations': 0, 'continueKey': '<string>', 'outputKey': 'final',
            'merge': False,
        })


class TestActionFieldExclusion(unittest.TestCase):
    """True unit test of the skeleton=False *field*-level exclusion branch
    in action() (clay/actions/skeleton.py:40-41). None of the 6 real
    skeleton=True types has a field with skeleton=False today, so that
    branch is unreachable via any real registered type — this registers a
    throwaway type through the real action()/req()/opt() decorators for the
    duration of the test to exercise it directly.
    """

    _TYPE_NAME = '_test_skeleton_field_exclusion'

    def setUp(self):
        registry.discover()

        @_action_decorator(self._TYPE_NAME)
        class _Sample:
            # req() fields carry no default, so they must precede the opt()
            # fields — dataclass() rejects a non-default field after a
            # defaulted one, exactly as it would for a real action schema.
            id:      str  = req("kept — required")
            hidden:  str  = req("excluded via skeleton=False", skeleton=False)
            visible: str  = opt("kept — optional with a default", "shown")
            silent:  bool = opt("excluded via skeleton=False", True, skeleton=False)

        self.addCleanup(registry._REGISTRY.pop, self._TYPE_NAME, None)
        self.addCleanup(registry._FLAGS.pop, self._TYPE_NAME, None)

    def test_skeleton_false_fields_are_excluded(self):
        result = WorkflowSkeleton().action(self._TYPE_NAME)
        self.assertEqual(result, {
            'id': '<string>', 'type': self._TYPE_NAME, 'visible': 'shown',
        })
        self.assertNotIn('hidden', result)
        self.assertNotIn('silent', result)


class TestWorkflowSkeletonDeterminism(unittest.TestCase):
    """Same registry state -> byte-identical (structurally identical) tree."""

    def setUp(self):
        registry.discover()

    def test_build_is_deterministic(self):
        self.assertEqual(WorkflowSkeleton().build(), WorkflowSkeleton().build())


class TestWorkflowSkeletonWrite(unittest.TestCase):
    """write() actually produces files on disk matching build()."""

    def setUp(self):
        registry.discover()
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.tmpdir = tmpdir.name

    def test_write_produces_expected_files_with_matching_content(self):
        dest = os.path.join(self.tmpdir, 'registry')
        skel = WorkflowSkeleton()
        expected = skel.build()

        written = skel.write(dest)

        self.assertEqual(set(written), {os.path.join(dest, name) for name in expected})
        for name, doc in expected.items():
            with open(os.path.join(dest, name)) as f:
                raw = f.read()
            self.assertEqual(json.loads(raw), doc)
            self.assertTrue(raw.endswith('\n'), f"{name}: missing trailing newline")
            self.assertIn('\n  ', raw, f"{name}: not 2-space indented")

    def test_write_creates_missing_dest_dir(self):
        dest = os.path.join(self.tmpdir, 'nested', 'does', 'not', 'exist')
        WorkflowSkeleton().write(dest)
        self.assertTrue(os.path.isdir(dest))

    def test_write_overwrites_existing_files(self):
        dest = os.path.join(self.tmpdir, 'registry2')
        os.makedirs(dest)
        stale_path = os.path.join(dest, 'main.json')
        with open(stale_path, 'w') as f:
            f.write('{"stale": true}')

        WorkflowSkeleton().write(dest)

        with open(stale_path) as f:
            content = json.load(f)
        self.assertNotIn('stale', content)
