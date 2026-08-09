"""The outer boundary: which directories a file action may use at all.

The per-path guards inside each action were always sound — they refuse an
absolute path, collapse `..` and require relative_to(root). What none of them
bounded was the *root*, which comes out of a workflow file and can be built
from context a model produced. These tests are about that root.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ...run import approval, io, workspaces


class _FakeIO:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def prompt(self, prompt_id, text):
        self.prompts.append((prompt_id, text))
        return self.answers.pop(0) if self.answers else ''


class _ClosedIO:
    def prompt(self, prompt_id, text):
        raise io.ChannelClosed('gone')


class _WorkspaceTestCase(unittest.TestCase):
    """Every test gets its own register. None of them touch ~/.clay."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()

        register = patch.object(workspaces, 'REGISTER_PATH',
                                str(self.tmp / 'workspaces.json'))
        register.start()
        self.addCleanup(register.stop)

        workspaces.reset_session()
        approval.reset()
        self.addCleanup(workspaces.reset_session)
        self.addCleanup(approval.reset)

    def dir(self, *parts) -> Path:
        path = self.tmp.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def authorize(self, root, *answers):
        channel = _FakeIO(*answers)
        with patch.object(io, 'get', return_value=channel):
            result = workspaces.authorize(root)
        self.channel = channel
        return result


class RegisterTest(_WorkspaceTestCase):

    def test_an_absent_register_approves_nothing(self):
        self.assertEqual(workspaces.load(), [])

    def test_approve_then_load_round_trips(self):
        target = self.dir('project')
        workspaces.approve(target)

        grants = workspaces.load()
        self.assertEqual([g.path for g in grants], [target])
        self.assertTrue(grants[0].added, 'no timestamp recorded')

    def test_the_file_is_json_with_a_version(self):
        workspaces.approve(self.dir('project'))
        with open(workspaces.REGISTER_PATH) as handle:
            data = json.load(handle)
        self.assertEqual(data['version'], workspaces.VERSION)
        self.assertEqual(len(data['approved']), 1)

    def test_a_corrupt_register_approves_nothing_and_says_so(self):
        """Failing closed. A truncated file must not read as a grant, and it
        must not read as silence either — "why is it asking about my project
        again" needs an answer."""
        with open(workspaces.REGISTER_PATH, 'w') as handle:
            handle.write('{"approved": [')

        with patch('builtins.print') as printed:
            self.assertEqual(workspaces.load(), [])
        said = ' '.join(str(c) for c in printed.call_args_list)
        self.assertIn('unapproved', said)

    def test_entries_without_a_path_are_dropped_not_fatal(self):
        with open(workspaces.REGISTER_PATH, 'w') as handle:
            json.dump({'version': 1, 'approved': [
                {'gates': {}}, {'path': str(self.dir('good'))}]}, handle)
        self.assertEqual([g.path for g in workspaces.load()],
                         [self.tmp / 'good'])

    def test_approving_twice_does_not_duplicate(self):
        target = self.dir('project')
        workspaces.approve(target)
        workspaces.approve(target, {'fileWrites': False})
        grants = workspaces.load()
        self.assertEqual(len(grants), 1)
        self.assertFalse(grants[0].gates['fileWrites'], 'the later grant lost')

    def test_forget_removes_one_and_reports_it(self):
        target = self.dir('project')
        workspaces.approve(target)
        self.assertTrue(workspaces.forget(target))
        self.assertEqual(workspaces.load(), [])
        self.assertFalse(workspaces.forget(target), 'removed something twice')


class ContainmentTest(_WorkspaceTestCase):
    """Subtree grants, decided by the same primitive the path guards use."""

    def test_the_directory_itself_is_covered(self):
        target = self.dir('project')
        workspaces.approve(target)
        self.assertEqual(self.authorize(target), target)

    def test_a_child_is_covered(self):
        workspaces.approve(self.dir('project'))
        child = self.dir('project', 'src', 'deep')
        self.assertEqual(self.authorize(child), child)

    def test_a_sibling_is_not(self):
        workspaces.approve(self.dir('project'))
        other = self.dir('elsewhere')
        with self.assertRaises(workspaces.WorkspaceDenied):
            self.authorize(other, 'n')

    def test_a_parent_is_not(self):
        """Approving a subdirectory must not hand over the tree above it."""
        workspaces.approve(self.dir('project', 'src'))
        with self.assertRaises(workspaces.WorkspaceDenied):
            self.authorize(self.tmp / 'project', 'n')

    def test_a_dot_dot_escape_is_not_covered(self):
        """resolve() collapses it before the comparison, so "inside" cannot be
        spelled around."""
        workspaces.approve(self.dir('project'))
        self.dir('elsewhere')
        with self.assertRaises(workspaces.WorkspaceDenied):
            self.authorize(self.tmp / 'project' / '..' / 'elsewhere', 'n')

    @unittest.skipUnless(hasattr(os, 'symlink'), 'no symlinks on this platform')
    def test_a_symlink_out_of_an_approved_tree_is_not_covered(self):
        """The check is on the resolved path. A link inside an approved
        directory pointing anywhere else is that other place."""
        workspaces.approve(self.dir('project'))
        outside = self.dir('secrets')
        link = self.tmp / 'project' / 'link'
        os.symlink(outside, link)

        with self.assertRaises(workspaces.WorkspaceDenied):
            self.authorize(link, 'n')

    def test_a_name_that_merely_starts_the_same_is_not_covered(self):
        """String prefixes would make /tmp/project-old a child of
        /tmp/project. relative_to() compares path components."""
        workspaces.approve(self.dir('project'))
        near = self.dir('project-old')
        with self.assertRaises(workspaces.WorkspaceDenied):
            self.authorize(near, 'n')

    def test_the_deepest_grant_wins(self):
        workspaces.approve(self.dir('project'), {'fileWrites': False})
        workspaces.approve(self.dir('project', 'client'), {'fileWrites': True})

        grant = workspaces.find(self.tmp / 'project' / 'client' / 'src')
        self.assertEqual(grant.path, self.tmp / 'project' / 'client')
        self.assertTrue(grant.gates['fileWrites'], 'the broad grant won')


class AskingTest(_WorkspaceTestCase):

    def test_yes_approves_and_remembers(self):
        target = self.dir('project')
        self.assertEqual(self.authorize(target, 'y'), target)
        self.assertEqual([g.path for g in workspaces.load()], [target])

    def test_the_prompt_names_the_directory_and_the_subtree(self):
        target = self.dir('project')
        self.authorize(target, 'y')
        prompt_id, text = self.channel.prompts[0]
        self.assertEqual(prompt_id, workspaces.PROMPT_ID)
        self.assertIn(str(target), text)
        self.assertIn('everything under it', text)

    def test_once_allows_without_remembering(self):
        target = self.dir('project')
        self.assertEqual(self.authorize(target, 'o'), target)
        self.assertEqual(workspaces.load(), [], 'a one-off was written down')

    def test_once_is_not_asked_again_in_the_same_session(self):
        target = self.dir('project')
        self.authorize(target, 'o')
        self.authorize(target)          # no answers left; would return ''
        self.assertEqual(self.channel.prompts, [], 'asked twice in one session')

    def test_a_remembered_directory_is_not_asked_again(self):
        target = self.dir('project')
        self.authorize(target, 'y')
        self.authorize(target)
        self.assertEqual(self.channel.prompts, [])

    def test_anything_unrecognised_refuses(self):
        """A typo must not hand over a directory. Blank included — at an
        approval prompt blank approves, and that must not carry over here."""
        for answer in ('', 'maybe', 'sure', 'ok', '1', 'yesterday'):
            with self.subTest(answer=answer):
                workspaces.reset_session()
                target = self.dir('project')
                with self.assertRaises(workspaces.WorkspaceDenied):
                    self.authorize(target, answer)
                self.assertEqual(workspaces.load(), [])

    def test_a_closed_channel_refuses(self):
        with patch.object(io, 'get', return_value=_ClosedIO()):
            with self.assertRaises(workspaces.WorkspaceDenied):
                workspaces.authorize(self.dir('project'))

    def test_the_refusal_names_the_directory(self):
        target = self.dir('project')
        with self.assertRaises(workspaces.WorkspaceDenied) as caught:
            self.authorize(target, 'n')
        self.assertIn(str(target), str(caught.exception))


class UnattendedTest(_WorkspaceTestCase):
    """Nobody to ask means refuse — the opposite of approval.confirm()."""

    def setUp(self):
        super().setUp()
        approval.set_unattended(True)
        self.addCleanup(approval.set_unattended, False)

    def test_an_unapproved_directory_refuses_without_prompting(self):
        channel = _FakeIO('y')
        with patch.object(io, 'get', return_value=channel):
            with self.assertRaises(workspaces.WorkspaceDenied):
                workspaces.authorize(self.dir('project'))
        self.assertEqual(channel.prompts, [], 'prompted with nobody there')

    def test_the_refusal_says_how_to_fix_it(self):
        target = self.dir('project')
        with self.assertRaises(workspaces.WorkspaceDenied) as caught:
            workspaces.authorize(target)
        self.assertIn('clay dirs add', str(caught.exception))

    def test_an_approved_directory_still_works_unattended(self):
        """The point is not to stop scheduled runs, only to stop them widening
        their own reach."""
        target = self.dir('project')
        workspaces.approve(target)
        self.assertEqual(workspaces.authorize(target), target)


class GateTest(_WorkspaceTestCase):
    """A directory carries the manual-approval gates for work done in it."""

    def test_gates_use_approval_polarity(self):
        """true means ASK, here as everywhere else — see the module docstring.
        The one thing in this design most likely to be written backwards."""
        target = self.dir('project')
        workspaces.approve(target, {'fileWrites': True})
        approval.set_manual(True)
        approval.set_gate('fileWrites', False)

        self.authorize(target)
        self.assertTrue(approval.enabled('fileWrites'),
                        'fileWrites=true should mean ask before writing')

    def test_entering_a_directory_applies_its_gates(self):
        target = self.dir('project')
        workspaces.approve(target, {'fileWrites': False, 'commands': True})
        approval.set_manual(True)

        self.authorize(target)
        self.assertFalse(approval.enabled('fileWrites'))
        self.assertTrue(approval.enabled('commands'))

    def test_gates_are_applied_once_per_session(self):
        """Otherwise the next file action overwrites a /manual toggle typed
        mid-run, every time."""
        target = self.dir('project')
        workspaces.approve(target, {'fileWrites': True})
        approval.set_manual(True)

        self.authorize(target)
        approval.set_gate('fileWrites', False)   # a human types /manual writes off
        self.authorize(target)

        self.assertFalse(approval.enabled('fileWrites'),
                         'the register overwrote a live toggle')

    def test_an_unknown_gate_key_in_the_file_is_ignored(self):
        grant = workspaces.Grant(self.dir('project'),
                                 {'fileWrites': True, 'nonsense': True})
        self.assertNotIn('nonsense', grant.gates)
        self.assertEqual(set(grant.gates), set(approval.GATES))

    def test_a_non_boolean_gate_falls_back_to_the_default(self):
        """A truthy string deciding whether a model may write without asking is
        exactly the silent failure the config loader already refuses."""
        grant = workspaces.Grant(self.dir('project'), {'fileWrites': 'no'})
        self.assertIsInstance(grant.gates['fileWrites'], bool)


class DefaultRootTest(_WorkspaceTestCase):

    def test_the_default_root_is_the_launch_directory(self):
        """Was "output", which resolved to $CWD/output — so the same workflow
        wrote somewhere different depending on where it was started."""
        self.assertEqual(workspaces.DEFAULT_ROOT, '.')

    def test_every_file_action_declares_the_same_default(self):
        from ...actions.core import file_ops, read_file, write_file, write_file_set
        self.assertEqual(read_file.DEFAULT_INPUT_ROOT, workspaces.DEFAULT_ROOT)
        self.assertEqual(write_file.DEFAULT_OUTPUT_ROOT, workspaces.DEFAULT_ROOT)
        self.assertEqual(file_ops.DEFAULT_ROOT, workspaces.DEFAULT_ROOT)
        self.assertEqual(write_file_set.DEFAULT_ROOT, workspaces.DEFAULT_ROOT)

    def test_the_launch_directory_is_not_approved_implicitly(self):
        """The whole point of the register. `clay run` from a home directory
        would otherwise put an entire account in scope, silently."""
        self.assertIsNone(workspaces.find(Path.cwd()))


class ActionRefusalTest(_WorkspaceTestCase):
    """The boundary reaches the handlers, not just the module."""

    def _denied(self, handler, action, ctx=None):
        channel = _FakeIO('n')
        with patch.object(io, 'get', return_value=channel):
            return handler(action, ctx or {})

    def test_write_file_refuses_an_unapproved_root(self):
        # `content` names a context key, not a literal.
        from ...actions.core.write_file import handler
        result = self._denied(handler, {'id': 'w', 'file': 'a.py',
                                        'root': str(self.dir('nope')),
                                        'content': 'body'},
                              {'body': 'print(1)'})
        self.assertIsNone(result['data'])
        self.assertIn('not approved', result['error'])
        self.assertFalse((self.tmp / 'nope' / 'a.py').exists(),
                         'the file was written despite the refusal')

    def test_read_file_refuses_an_unapproved_root(self):
        from ...actions.core.read_file import handler
        target = self.dir('nope')
        (target / 'a.py').write_text('secret')
        result = self._denied(handler, {'id': 'r', 'file': 'a.py',
                                        'root': str(target)})
        self.assertIsNone(result['data'])
        self.assertIn('not approved', result['error'])

    def test_list_workspace_refuses_an_unapproved_root(self):
        from ...actions.core.file_ops import list_handler
        result = self._denied(list_handler, {'id': 'l',
                                             'root': str(self.dir('nope'))})
        self.assertIn('not approved', result['error'])

    def test_an_approved_root_still_writes(self):
        from ...actions.core.write_file import handler
        target = self.dir('yes')
        workspaces.approve(target)
        with patch.object(io, 'get', return_value=_FakeIO()):
            result = handler({'id': 'w', 'file': 'a.py', 'root': str(target),
                              'content': 'body'}, {'body': 'print(1)'})
        self.assertIsNone(result.get('error'))
        self.assertIn('print(1)', (target / 'a.py').read_text())

    def test_an_interpolated_root_is_authorized_too(self):
        """`root` supports {placeholder}, so it can be built from context a
        model produced — the reason the check is after interpolation."""
        from ...actions.core.file_ops import list_handler
        channel = _FakeIO('n')
        with patch.object(io, 'get', return_value=channel):
            result = list_handler({'id': 'l', 'root': '{escape}'},
                                  {'escape': str(self.dir('nope'))})
        self.assertIn('not approved', result['error'])
        self.assertIn(str(self.tmp / 'nope'), channel.prompts[0][1])


if __name__ == '__main__':
    unittest.main()
