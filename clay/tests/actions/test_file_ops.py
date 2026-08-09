"""Unit tests for the workspace protocol — listWorkspace, serveFileReads,
applyFileWrites.

The three actions share WorkspaceRoot, and the property that matters most is
that they agree: a path listWorkspace prints must be a path serveFileReads can
resolve. test_listed_paths_round_trip_through_reads pins that directly.
"""

import os
import tempfile
import unittest

from unittest.mock import patch

from ...actions.core.file_ops import (
    SHELL_LANGUAGES,
    EditError,
    WorkspaceRoot,
    apply_handler,
    diff_body,
    has_broken_write_tag,
    has_unwritten_code,
    list_handler,
    parse_changes,
    parse_reads,
    parse_written_paths,
    serve_handler,
    unwritten_fences,
)
from ...run import approval, io, workspaces
from ..test_core import _EventLog


def _read_tag(path):
    return f'<read_file><path>{path}</path></read_file>'


def _write_tag(path, content):
    return (f'<write_file><path>{path}</path>\n'
            f'<content>\n{content}\n</content></write_file>')


class WorkspaceTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        # This test's own register, holding this test's own directory. Same
        # fixture as clay/tests/run/test_workspaces.py, for the same reason:
        # workspaces.load() reads $CLAY_HOME/workspaces.json, so without it
        # these tests either stop on an approval prompt or read whatever the
        # developer running them happens to have approved. Neither is a test.
        #
        # Kept outside self.root: listWorkspace enumerates that directory, and
        # a register file sitting in it would show up as workspace content.
        self._reg = tempfile.TemporaryDirectory()
        self.addCleanup(self._reg.cleanup)
        register = patch.object(
            workspaces, 'REGISTER_PATH',
            os.path.join(self._reg.name, 'workspaces.json'))
        register.start()
        self.addCleanup(register.stop)
        workspaces.reset_session()
        self.addCleanup(workspaces.reset_session)
        workspaces.approve(self.root)

        # Enter it once, here, so the register is finished with the approval
        # gates before any test touches them. Approving a directory records the
        # gates a session starts with beneath it, and authorize() seeds the
        # session from them on first use — once per directory, by design. Left
        # to happen inside a test, that first use is the handler call, and the
        # seeding lands *after* setUp has set the gate under test and silently
        # replaces it with whatever the developer's own ~/.clay/config.json
        # holds. Same reason REGISTER_PATH is redirected above: a test must not
        # read the machine it runs on.
        workspaces.authorize(self.root)

    def _put(self, rel, content='x\n'):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as fh:
            fh.write(content)
        return path

    def _content(self, rel):
        with open(os.path.join(self.root, rel)) as fh:
            return fh.read()

    def _tree(self):
        found = []
        for base, _, names in os.walk(self.root):
            for name in names:
                found.append(os.path.relpath(os.path.join(base, name), self.root))
        return sorted(found)

    def _list(self, **extra):
        return list_handler({'id': 'files', 'root': self.root, **extra}, {})

    def _serve(self, reply, ctx=None, **extra):
        return serve_handler(
            {'id': 'file_context', 'reply': 'reply', 'root': self.root, **extra},
            {'reply': reply, **(ctx or {})})

    def _apply(self, reply, **extra):
        return apply_handler(
            {'id': 'files_written', 'reply': 'reply', 'root': self.root, **extra},
            {'reply': reply})


class _FakeIO:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def prompt(self, prompt_id, text):
        self.prompts.append((prompt_id, text))
        return self.answers.pop(0) if self.answers else ''


class ApprovalGateTestCase(WorkspaceTestCase):
    """Handler tests with manual approval switched on for one gate."""

    gate = ''

    def setUp(self):
        super().setUp()
        approval.reset()
        self.addCleanup(approval.reset)
        approval.set_manual(True)
        for gate in approval.GATES:
            approval.set_gate(gate, gate == self.gate)

    def answering(self, *answers):
        self.channel = _FakeIO(*answers)
        return patch.object(io, 'get', return_value=self.channel)


class ApplyFileWritesApprovalTest(ApprovalGateTestCase):

    gate = 'fileWrites'

    REPLY = ('```python a.py\nA = 1\n```\n'
             '```python b.py\nB = 2\n```\n'
             '```python c.py\nC = 3\n```\n')

    def test_approving_everything_writes_everything(self):
        with self.answering('y'):
            result = self._apply(self.REPLY)
        self.assertEqual(['a.py', 'b.py', 'c.py'], self._tree())
        self.assertEqual(3, result['data'].count('CREATED'))

    def test_rejecting_one_writes_the_others_and_names_the_skip(self):
        # Deliberate and reported, unlike the silent partial write that
        # unwritten_fences() refuses: the human chose this one.
        with self.answering('2'):
            result = self._apply(self.REPLY)
        self.assertEqual(['a.py', 'c.py'], self._tree())
        self.assertNotIn('b.py', result['data'])

    def test_rejecting_everything_writes_nothing_and_reports_nothing(self):
        with self.answering('n'):
            result = self._apply(self.REPLY)
        self.assertEqual([], self._tree())
        # Empty rather than an error: the gate closing is not a failure, and
        # `when: files_written` should skip the review exactly as it would for
        # a turn that wrote nothing.
        self.assertEqual('', result['data'])

    def test_the_prompt_shows_a_diff_for_an_edit_and_a_note_for_a_new_file(self):
        self._put('a.py', 'A = 0\n')
        with self.answering('y'):
            self._apply(self.REPLY)
        text = self.channel.prompts[0][1]
        self.assertIn('-A = 0', text)
        self.assertIn('+A = 1', text)
        self.assertIn('new file', text)

    def test_a_closed_channel_writes_nothing(self):
        class _Closed:
            def prompt(self, prompt_id, text):
                raise io.ChannelClosed('gone')

        with patch.object(io, 'get', return_value=_Closed()):
            self._apply(self.REPLY)
        self.assertEqual([], self._tree())

    def test_the_gate_off_asks_nothing(self):
        approval.set_manual(False)
        with self.answering('n'):
            self._apply(self.REPLY)
        self.assertEqual(['a.py', 'b.py', 'c.py'], self._tree())
        self.assertEqual([], self.channel.prompts)


class ServeFileReadsApprovalTest(ApprovalGateTestCase):

    gate = 'fileReads'

    def test_a_refused_read_is_told_not_silently_dropped(self):
        # A model handed fewer files than it asked for, with no explanation,
        # writes code around what it imagines is there.
        self._put('a.py', 'A\n')
        self._put('b.py', 'B\n')
        with self.answering('1'):
            result = self._serve(_read_tag('a.py') + _read_tag('b.py'))
        self.assertIn('(not approved', result['data'])
        self.assertNotIn('A\n', result['data'])
        self.assertIn('B\n', result['data'])

    def test_approving_everything_serves_everything(self):
        self._put('a.py', 'A\n')
        with self.answering('y'):
            result = self._serve(_read_tag('a.py'))
        self.assertIn('A\n', result['data'])

    def test_reads_are_off_by_default(self):
        approval.set_gate('fileReads', False)
        self._put('a.py', 'A\n')
        with self.answering('n'):
            result = self._serve(_read_tag('a.py'))
        self.assertIn('A\n', result['data'])
        self.assertEqual([], self.channel.prompts)


class WritePayloadTest(WorkspaceTestCase):
    """What applyFileWrites draws after it writes — diff for an edit, file for
    a creation. Asserted on `kind` rather than on text so a front-end can be
    changed without these tests following it around."""

    def test_a_new_file_is_drawn_whole(self):
        with _EventLog() as log:
            self._apply('```python a.py\nA = 1\n```\n')
        self.assertIn('A = 1', ' '.join(log.outputs('file')))
        self.assertEqual([], log.outputs('diff'))

    def test_an_edit_is_drawn_as_a_diff(self):
        self._put('a.py', 'A = 0\nB = 0\n')
        with _EventLog() as log:
            self._apply('```python a.py\nA = 1\nB = 0\n```\n')
        drawn = ' '.join(log.outputs('diff'))
        self.assertIn('-A = 0', drawn)
        self.assertIn('+A = 1', drawn)
        # The unchanged line is not repeated as a change, which is the point.
        self.assertNotIn('+B = 0', drawn)
        self.assertEqual([], log.outputs('file'))

    def test_the_label_counts_the_lines_that_moved(self):
        self._put('a.py', 'A = 0\n')
        with _EventLog() as log:
            self._apply('```python a.py\nA = 1\n```\n')
        self.assertIn('(+1 −1)', ' '.join(log.outputs('diff')))

    def test_a_file_written_twice_diffs_against_disk_not_the_first_write(self):
        # The intermediate result was never on disk, so a diff against it would
        # describe a state nobody can look at.
        self._put('a.py', 'A = 0\n')
        with _EventLog() as log:
            self._apply('```python a.py\nA = 1\n```\n'
                        '```python a.py\nA = 2\n```\n')
        drawn = ' '.join(log.outputs('diff'))
        self.assertIn('-A = 0', drawn)
        self.assertIn('+A = 2', drawn)
        self.assertNotIn('A = 1', drawn)


class DiffBodyTest(unittest.TestCase):

    def test_an_edit_shows_only_what_moved(self):
        diff = diff_body('a\nb\nc\n', 'a\nB\nc\n', 'f.py')
        self.assertIn('-b', diff)
        self.assertIn('+B', diff)
        self.assertNotIn('\n+a', diff)

    def test_an_unchanged_file_says_so_rather_than_drawing_an_empty_diff(self):
        self.assertIn('no change', diff_body('a\n', 'a\n', 'f.py'))

    def test_a_file_with_no_trailing_newline_still_produces_whole_lines(self):
        diff = diff_body('a', 'b', 'f.py')
        self.assertTrue(diff.endswith('\n'))


class ListWorkspaceTest(WorkspaceTestCase):

    def test_lists_root_relative_paths_sorted(self):
        self._put('pkg/mod.py')
        self._put('main.py')
        self.assertEqual(self._list()['data'], 'main.py\npkg/mod.py')

    def test_empty_workspace_says_so(self):
        self.assertIn('no files yet', self._list()['data'])

    def test_missing_directory_is_not_an_error(self):
        result = list_handler(
            {'id': 'files', 'root': os.path.join(self.root, 'nope')}, {})
        self.assertIsNone(result.get('error'))
        self.assertIn('no files yet', result['data'])

    def test_noise_directories_are_skipped(self):
        self._put('keep.py')
        self._put('__pycache__/keep.cpython-311.pyc')
        self._put('node_modules/dep/index.js')
        self.assertEqual(self._list()['data'], 'keep.py')

    def test_overflow_is_reported_as_a_count(self):
        for i in range(5):
            self._put(f'f{i}.py')
        data = self._list(maxFiles=2)['data']
        self.assertEqual(data.count('\n'), 2)          # 2 files + 1 notice line
        self.assertIn('3 further file(s) not listed', data)

    def test_listed_paths_round_trip_through_reads(self):
        """Every path the listing prints must resolve for serveFileReads."""
        self._put('pkg/deep/mod.py', 'CONTENT\n')
        listed = self._list()['data'].splitlines()
        self.assertEqual(listed, ['pkg/deep/mod.py'])

        served = self._serve(_read_tag(listed[0]))['data']
        self.assertIn('CONTENT', served)
        self.assertNotIn('not found', served)


class ServeFileReadsTest(WorkspaceTestCase):

    def test_reply_without_tags_serves_nothing(self):
        self.assertEqual(self._serve('just talking, no tags')['data'], '')

    def test_serves_requested_file_in_a_labelled_block(self):
        self._put('a.py', 'print(1)\n')
        data = self._serve(_read_tag('a.py'))['data']
        self.assertIn('=== a.py ===', data)
        self.assertIn('print(1)', data)

    def test_missing_file_is_reported_not_fatal(self):
        result = self._serve(_read_tag('ghost.py'))
        self.assertIsNone(result.get('error'))
        self.assertIn('(not found)', result['data'])

    def test_escaping_path_is_refused_inline(self):
        data = self._serve(_read_tag('../secrets.txt'))['data']
        self.assertIn('refused', data)

    def test_absolute_path_is_refused(self):
        data = self._serve(_read_tag('/etc/passwd'))['data']
        self.assertIn('refused', data)

    def test_long_file_is_truncated_with_a_marker(self):
        self._put('big.py', 'y' * 500)
        data = self._serve(_read_tag('big.py'), maxBytes=100)['data']
        self.assertIn('truncated at 100 of 500 chars', data)
        self.assertNotIn('y' * 101, data)

    def test_request_limit_reports_the_skipped_remainder(self):
        for i in range(4):
            self._put(f'f{i}.py')
        reply = ''.join(_read_tag(f'f{i}.py') for i in range(4))
        data = self._serve(reply, maxFiles=2)['data']
        self.assertIn('2 further read request(s) skipped', data)


class ServeFileReadsVisibilityTest(WorkspaceTestCase):
    """Whether a pass read the disk has to be visible even when the payloads
    are not — a hidden action that read nothing and one that read four files
    look identical otherwise, which is how a hallucinated review goes unnoticed."""

    def test_reading_nothing_is_said_out_loud(self):
        self._put('a.py')
        with _EventLog() as log:
            self._serve('just talking, no tags', visible=False)
        self.assertIn('nothing was read', ' '.join(log.messages('log')))

    def test_an_empty_workspace_is_not_warned_about(self):
        # Nothing on disk means nothing to read and no assumption to make.
        with _EventLog() as log:
            self._serve('just talking, no tags')
        self.assertEqual(log.messages('log'), [])

    def test_the_files_actually_read_are_named(self):
        self._put('a.py', 'print(1)\n')
        with _EventLog() as log:
            self._serve(_read_tag('a.py'), visible=False)
        line = ' '.join(log.messages('log'))
        self.assertIn('read 1 file(s)', line)
        self.assertIn('a.py', line)

    def test_a_file_that_could_not_be_read_is_warned_about(self):
        self._put('a.py')
        with _EventLog() as log:
            self._serve(_read_tag('ghost.py'))
        self.assertIn('could not read ghost.py', ' '.join(log.messages('log')))


class ServeFileReadsPathsKeyTest(WorkspaceTestCase):
    """pathsKey hands a pass the files it is about to work on, without
    spending a model call to have it ask for them by name."""

    def _written(self, *rels):
        return '\n'.join(f'CREATED: {os.path.join(self.root, rel)}'
                         for rel in rels)

    def test_absolute_paths_from_apply_are_served(self):
        # applyFileWrites reports resolved absolute paths, which resolve()
        # refuses on sight — WorkspaceRoot.relative is what bridges the two.
        self._put('a.py', 'print(1)\n')
        data = self._serve('', ctx={'files_written': self._written('a.py')},
                           pathsKey='files_written')['data']
        self.assertIn('=== a.py ===', data)
        self.assertIn('print(1)', data)

    def test_contents_come_from_disk_not_from_the_reply(self):
        # The whole point: the review pass sees what is on disk now, including
        # a fix an earlier pass made, not what a reply claimed to write.
        self._put('a.py', 'FIXED\n')
        data = self._serve('', ctx={'files_written': 'a.py'},
                           pathsKey='files_written')['data']
        self.assertIn('FIXED', data)

    def test_read_tags_are_served_after_the_path_list(self):
        self._put('a.py', 'AAA\n')
        self._put('b.py', 'BBB\n')
        data = self._serve(_read_tag('b.py'), ctx={'files_written': 'a.py'},
                           pathsKey='files_written')['data']
        self.assertLess(data.index('=== a.py ==='), data.index('=== b.py ==='))

    def test_a_file_in_both_is_served_once(self):
        self._put('a.py', 'AAA\n')
        data = self._serve(_read_tag('a.py'), ctx={'files_written': 'a.py'},
                           pathsKey='files_written')['data']
        self.assertEqual(data.count('=== a.py ==='), 1)

    def test_a_path_outside_the_workspace_is_dropped_and_warned_about(self):
        with _EventLog() as log:
            data = self._serve('', ctx={'files_written': '/etc/passwd'},
                               pathsKey='files_written')['data']
        self.assertEqual(data, '')
        self.assertIn('outside the workspace', ' '.join(log.messages('log')))

    def test_no_pathsKey_leaves_the_reply_path_untouched(self):
        self._put('a.py', 'AAA\n')
        self.assertIn('AAA', self._serve(_read_tag('a.py'))['data'])


class ApplyFileWritesTest(WorkspaceTestCase):

    def test_reply_without_tags_is_a_successful_no_op(self):
        result = self._apply('here is an explanation with no blocks')
        self.assertIsNone(result.get('error'))
        self.assertEqual(result['data'], '')
        self.assertEqual(self._tree(), [])

    def test_fence_naming_a_file_on_the_fence_line_is_written(self):
        result = self._apply("```python greet.py\nprint('hi')\n```\n")
        self.assertIn('CREATED', result['data'])
        self.assertEqual(self._tree(), ['greet.py'])
        self.assertEqual(self._content('greet.py'), "print('hi')\n")

    def test_fence_naming_a_file_in_a_leading_comment_is_written(self):
        result = self._apply("```python\n# greet.py\nprint('hi')\n```\n")
        self.assertIn('CREATED', result['data'])
        self.assertEqual(self._tree(), ['greet.py'])
        # The path comment is a marker, not part of the file.
        self.assertEqual(self._content('greet.py'), "print('hi')\n")

    def test_write_tag_without_content_wrapper_lands_on_disk(self):
        """The bug report, end to end: this reply wrote nothing at all."""
        result = self._apply(
            '<write_file><path>hey.py</path>\n'
            '  # hey.py\n'
            '  print("Hey fucka you!")\n'
            '  </write_file>\n'
            '\n'
            '  You can run it with:\n'
            '  ```bash\n'
            '  python hey.py\n'
            '  ```\n')
        self.assertIn('CREATED', result['data'])
        self.assertEqual(self._tree(), ['hey.py'])
        # Dedented, or python raises IndentationError on the first statement.
        self.assertEqual(self._content('hey.py'),
                         '# hey.py\nprint("Hey fucka you!")\n')

    def test_broken_write_tag_is_warned_about(self):
        with _EventLog() as log:
            result = self._apply('<write_file><path>hey.py</path>\n'
                                 'print("hi")\n')
        self.assertEqual(result['data'], '')
        self.assertEqual(self._tree(), [])
        self.assertIn('<write_file>', ' '.join(log.messages('log')))

    def test_unnamed_fence_is_refused_not_silently_dropped(self):
        # The failure this catches: the model prints a ```python block, the
        # user sees code, and the workspace stays empty with no explanation.
        # It is not guessed at — the only other clue is prose.
        with _EventLog() as log:
            result = self._apply("Let's write the code:\n\n"
                                 "```python\nprint('hi')\n```\n")
        self.assertIsNone(result['data'])
        self.assertIn('no usable file path', result['error'])
        self.assertEqual(self._tree(), [])
        self.assertIn('no usable file path', ' '.join(log.messages('log')))

    def test_prose_comment_is_not_mistaken_for_a_path(self):
        with _EventLog() as log:
            result = self._apply("```python\n# draw the finger\nprint('hi')\n```\n")
        self.assertEqual(self._tree(), [])
        self.assertIn('no usable file path', ' '.join(log.messages('log')))

    def test_bash_fence_is_a_command_not_a_file(self):
        # A turn that just runs a command writes nothing by design; neither the
        # bash fence nor its closing ``` may read as a lost file.
        with _EventLog() as log:
            result = self._apply('Running it:\n\n```bash\npython3 greet.py\n```\n')
        self.assertEqual(result['data'], '')
        self.assertEqual(self._tree(), [])
        self.assertEqual(log.messages('log'), [])

    def test_the_written_file_is_echoed_in_full(self):
        body = 'def f():\n    return 1\n\n\nprint(f())\n'
        with _EventLog() as log:
            self._apply(f'```python m.py\n{body}```')
        echoed = '\n'.join(log.outputs('file'))
        self.assertIn('m.py written', echoed)
        # Every line, indentation and blank lines intact — the point is to see
        # what actually landed on disk, not a summary of it.
        for line in body.split('\n'):
            self.assertIn(line, echoed)
        self.assertIn('    return 1', echoed)

    def test_a_partly_named_reply_writes_nothing_at_all(self):
        # The reported bug: a multi-file reply names its first fence, drifts on
        # the rest, and the named files land while the others vanish without a
        # word — files_written then lists a subset that reads as success.
        reply = ("```python a.py\nA = 1\n```\n\n"
                 "```python\nB = 2\n```\n\n"
                 "```python\nC = 3\n```\n")
        with _EventLog() as log:
            result = self._apply(reply)

        self.assertEqual(self._tree(), [])
        self.assertIsNone(result['data'])
        self.assertIn('2 non-command code fence(s)', result['error'])
        # It says what was thrown away, not only what was missing — the named
        # file is the part a reader would otherwise assume survived.
        self.assertIn('1 recognized file change(s)', result['error'])
        self.assertIn('every fence', ' '.join(log.messages('log')))

    def test_a_fully_named_multi_file_reply_still_writes(self):
        reply = ("```python a.py\nA = 1\n```\n\n"
                 "```python pkg/b.py\nB = 2\n```\n\n"
                 "```python pkg/c.py\nC = 3\n```\n")
        result = self._apply(reply)
        self.assertEqual(self._tree(), ['a.py', 'pkg/b.py', 'pkg/c.py'])
        self.assertIsNone(result.get('error'))

    def test_the_lone_unnamed_fence_inference_still_writes(self):
        # unwritten_fences() exists so the refusal does not swallow this: the
        # fence names no file and is written anyway.
        result = self._apply('```python\nA = 1\n```\n'
                             '```bash\npython3 flap.py\n```')
        self.assertEqual(self._tree(), ['flap.py'])
        self.assertIsNone(result.get('error'))

    def test_write_then_run_in_one_reply(self):
        reply = ("```python greet.py\nprint('hi')\n```\n\n"
                 "```bash\npython3 greet.py\n```\n")
        with _EventLog() as log:
            result = self._apply(reply)
        self.assertEqual(self._tree(), ['greet.py'])
        self.assertNotIn('name no file', ' '.join(log.messages('log')))

    def test_tag_and_fence_apply_in_reply_order(self):
        reply = (_write_tag('a.py', 'A')
                 + '\n\n```python b.py\nB\n```\n\n'
                 + _write_tag('c.py', 'C'))
        result = self._apply(reply)
        created = [l.split(': ', 1)[1] for l in result['data'].splitlines()]
        self.assertEqual([os.path.basename(p) for p in created],
                         ['a.py', 'b.py', 'c.py'])

    def test_fence_whose_content_needs_a_closing_fence_uses_the_tag(self):
        # The one thing a fence cannot carry, which is why the tag remains.
        result = self._apply(_write_tag('doc.md', '```python\nx = 1\n```'))
        self.assertEqual(self._tree(), ['doc.md'])
        self.assertIn('```python', self._content('doc.md'))

    def test_edit_updates_an_existing_file(self):
        self._put('m.py', 'X = 1\nPORT = 8080\n')
        result = self._apply('```python m.py\n<<<<<<< SEARCH\nPORT = 8080\n'
                             '=======\nPORT = 9090\n>>>>>>> REPLACE\n```')
        self.assertIn('UPDATED', result['data'])
        self.assertEqual(self._content('m.py'), 'X = 1\nPORT = 9090\n')

    def test_a_failed_edit_writes_nothing_at_all(self):
        # The invariant that matters: an earlier file in the same reply must
        # not be committed when a later edit turns out not to match.
        self._put('m.py', 'X = 1\n')
        reply = ('```python new.py\nA\n```\n'
                 + '```python m.py\n<<<<<<< SEARCH\nABSENT\n'
                   '=======\nNEW\n>>>>>>> REPLACE\n```')
        result = self._apply(reply)
        self.assertIsNotNone(result.get('error'))
        self.assertEqual(self._tree(), ['m.py'])
        self.assertEqual(self._content('m.py'), 'X = 1\n')

    def test_two_changes_to_one_file_compose(self):
        # The second edit must see the first one's result, not the stale disk
        # copy, or it reports "not found" for text the reply just added.
        self._put('m.py', 'A\n')
        reply = ('```python m.py\n<<<<<<< SEARCH\nA\n=======\nB\n>>>>>>> REPLACE\n```\n'
                 '```python m.py\n<<<<<<< SEARCH\nB\n=======\nC\n>>>>>>> REPLACE\n```')
        result = self._apply(reply)
        self.assertIsNone(result.get('error'))
        self.assertEqual(self._content('m.py'), 'C\n')

    def test_conflict_markers_never_reach_the_file(self):
        result = self._apply('```python flap.py\n<<<<<<< SEARCH\n=======\n'
                             'import sys\n>>>>>>> REPLACE\n```')
        self.assertEqual(self._content('flap.py'), 'import sys\n')

    def test_unnamed_fence_named_by_its_command_is_written(self):
        reply = ('```python\nimport sys\n```\n\n'
                 'You can run it with:\n```bash\npython flap.py\n```')
        result = self._apply(reply)
        self.assertEqual(self._tree(), ['flap.py'])
        self.assertEqual(self._content('flap.py'), 'import sys\n')

    def test_writes_every_block_creating_parents(self):
        reply = (_write_tag('main.py', "print('hi')")
                 + '\n\n'
                 + _write_tag('pkg/mod.py', 'VALUE = 1'))
        result = self._apply(reply)
        self.assertIsNone(result.get('error'))
        self.assertEqual(self._tree(),
                         ['main.py', os.path.join('pkg', 'mod.py')])
        self.assertEqual(result['data'].count('CREATED:'), 2)

    def test_content_gains_a_final_newline(self):
        self._apply(_write_tag('a.py', 'x = 1'))
        with open(os.path.join(self.root, 'a.py')) as fh:
            self.assertEqual(fh.read(), 'x = 1\n')

    def test_rewriting_a_file_replaces_it_whole(self):
        self._put('a.py', 'old\n')
        self._apply(_write_tag('a.py', 'new'))
        with open(os.path.join(self.root, 'a.py')) as fh:
            self.assertEqual(fh.read(), 'new\n')

    def test_escaping_path_writes_nothing_at_all(self):
        reply = (_write_tag('safe.py', 'ok')
                 + '\n\n'
                 + _write_tag('../escape.py', 'bad'))
        result = self._apply(reply)
        self.assertIn('refused path', result['error'])
        # All-or-nothing: the safe block was not written either.
        self.assertEqual(self._tree(), [])

    def test_absolute_path_writes_nothing(self):
        result = self._apply(_write_tag('/tmp/evil.py', 'bad'))
        self.assertIn('refused path', result['error'])
        self.assertEqual(self._tree(), [])

    def test_max_files_refuses_the_whole_reply(self):
        reply = '\n\n'.join(_write_tag(f'f{i}.py', 'x') for i in range(3))
        result = self._apply(reply, maxFiles=2)
        self.assertIn('the limit is 2', result['error'])
        self.assertEqual(self._tree(), [])


class RootInterpolationTest(WorkspaceTestCase):
    """`root` interpolates from context so a workflow can declare the
    workspace once instead of repeating the literal path on every action."""

    def test_list_resolves_root_from_context(self):
        self._put('a.py')
        result = list_handler({'id': 'files', 'root': '{workspace}'},
                              {'workspace': self.root})
        self.assertEqual(result['data'], 'a.py')

    def test_serve_resolves_root_from_context(self):
        self._put('a.py', 'CONTENT\n')
        result = serve_handler(
            {'id': 'ctx', 'reply': 'reply', 'root': '{workspace}'},
            {'reply': _read_tag('a.py'), 'workspace': self.root})
        self.assertIn('CONTENT', result['data'])

    def test_apply_resolves_root_from_context(self):
        result = apply_handler(
            {'id': 'written', 'reply': 'reply', 'root': '{workspace}'},
            {'reply': _write_tag('a.py', 'x = 1'), 'workspace': self.root})
        self.assertIsNone(result.get('error'))
        self.assertEqual(self._tree(), ['a.py'])

    def test_unresolved_placeholder_is_refused_not_crashed(self):
        """A {placeholder} naming no context key is a workflow bug, not a path.

        It survives interpolation intact — _SafeMap leaves it alone rather than
        raising — and then becomes a literal directory name under the project
        directory that nothing has ever approved. The boundary refuses it.

        That refusal is the point. Before the workspace register existed this
        asserted the opposite: that the action shrugged and reported an empty
        listing. Reporting "no files yet" for a directory whose name is a typo
        is how a workflow runs to completion having read nothing, and says so
        nowhere. Refusing names the bad path in the error.

        Unattended here and not in the fixture. It is what makes authorize()
        raise instead of asking, but it also switches off approval.confirm(),
        and the read and write gate tests in this file need that prompt to fire.
        """
        approval.set_unattended(True)
        self.addCleanup(approval.set_unattended, False)
        result = list_handler({'id': 'files', 'root': '{nosuchkey}'}, {})
        self.assertIsNone(result['data'])
        self.assertIn('{nosuchkey}', result['error'])
        self.assertIn('not an approved working directory', result['error'])


class TagParsingTest(unittest.TestCase):

    def test_reads_are_parsed_in_reply_order(self):
        reply = 'first ' + _read_tag('a.py') + ' then ' + _read_tag('b.py')
        self.assertEqual(parse_reads(reply), ['a.py', 'b.py'])

    def test_writes_keep_content_verbatim(self):
        body = 'def f():\n    return {"a": 1}'
        change = parse_changes(_write_tag('m.py', body))[0]
        self.assertEqual(change.path, 'm.py')
        self.assertEqual(change.apply(None), body)

    def test_prose_parses_to_nothing(self):
        self.assertEqual(parse_reads('no tags here'), [])
        self.assertEqual(parse_changes('no tags here'), [])

    def test_none_is_tolerated(self):
        self.assertEqual(parse_reads(None), [])
        self.assertEqual(parse_changes(None), [])

    def test_content_wrapper_is_optional(self):
        """Models routinely drop <content> and put the body after </path>."""
        reply = ('<write_file><path>m.py</path>\n'
                 'print("hi")\n'
                 '</write_file>')
        self.assertEqual(_named(reply), [('m.py', 'print("hi")')])

    def test_body_indented_under_the_tag_is_dedented(self):
        """Indentation there is layout, not content — written verbatim it
        makes a Python file that raises IndentationError on line one."""
        reply = ('<write_file><path>m.py</path>\n'
                 '  import sys\n'
                 '  print(sys.argv)\n'
                 '  </write_file>')
        self.assertEqual(_named(reply),
                         [('m.py', 'import sys\nprint(sys.argv)\n')])

    def test_indented_content_wrapper_is_dedented_too(self):
        # The wrapper's trailing newline stays in the body here — indentation
        # sits between it and </content> — and dedent then blanks that line,
        # leaving the newline apply_handler would have added regardless.
        reply = ('<write_file><path>m.py</path>\n'
                 '  <content>\n'
                 '  print("hi")\n'
                 '  </content></write_file>')
        self.assertEqual(_named(reply), [('m.py', 'print("hi")\n')])

    def test_inner_indentation_survives_dedent(self):
        """dedent removes only what every non-blank line shares."""
        reply = ('<write_file><path>m.py</path>\n'
                 'def f():\n'
                 '    return 1\n'
                 '</write_file>')
        self.assertEqual(_named(reply), [('m.py', 'def f():\n    return 1')])

    def test_the_reply_that_wrote_nothing(self):
        """Verbatim from the bug report: a whole file, a name, and 0 writes."""
        reply = (
            '<write_file><path>hey.py</path>\n'
            '  # hey.py\n'
            '  print("Hey fucka you!")\n'
            '  </write_file>\n'
            '\n'
            '  You can run it with:\n'
            '  ```bash\n'
            '  python hey.py\n'
            '  ```\n')
        changes = parse_changes(reply)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, 'hey.py')
        self.assertEqual(changes[0].apply(None),
                         '# hey.py\nprint("Hey fucka you!")\n')

    def test_tag_and_fence_in_one_reply_keep_reading_order(self):
        reply = ('<write_file><path>a.py</path>\nA\n</write_file>\n'
                 '```python b.py\nB\n```')
        self.assertEqual([c.path for c in parse_changes(reply)],
                         ['a.py', 'b.py'])


class BrokenWriteTagTest(unittest.TestCase):
    """A tag that parses to nothing must say so. Silence there reads as
    "this turn had no files" when it means "your file was lost"."""

    def test_unclosed_tag_is_flagged(self):
        self.assertTrue(has_broken_write_tag(
            '<write_file><path>a.py</path>\nprint(1)\n'))

    def test_tag_without_a_path_is_flagged(self):
        self.assertTrue(has_broken_write_tag(
            '<write_file>\nprint(1)\n</write_file>'))

    def test_tag_with_an_empty_path_is_flagged(self):
        self.assertTrue(has_broken_write_tag(
            '<write_file><path>  </path>\nprint(1)\n</write_file>'))

    def test_a_tag_that_parsed_is_not_flagged(self):
        self.assertFalse(has_broken_write_tag(
            '<write_file><path>a.py</path>\nprint(1)\n</write_file>'))

    def test_no_tag_at_all_is_not_flagged(self):
        self.assertFalse(has_broken_write_tag('just prose'))
        self.assertFalse(has_broken_write_tag(None))

    def test_one_good_tag_beside_one_broken_is_not_flagged(self):
        """Something was written, so the turn is not silent — the warning is
        for a reply that produced no writes at all."""
        self.assertFalse(has_broken_write_tag(
            '<write_file><path>a.py</path>\nA\n</write_file>\n'
            '<write_file>\nB\n</write_file>'))


def _named(text):
    """(path, resulting content) for each change, against an absent file."""
    return [(c.path, c.apply(None)) for c in parse_changes(text)]


class FenceParsingTest(unittest.TestCase):
    """A named code fence is a write. The name is the whole question: without
    one the code cannot be placed, and a guessed filename creates a real file
    the user never asked for."""

    def test_path_on_the_fence_line(self):
        self.assertEqual(_named('```python pkg/m.py\nX = 1\n```'),
                         [('pkg/m.py', 'X = 1\n')])

    def test_path_in_a_leading_comment_is_stripped_from_the_content(self):
        self.assertEqual(_named('```python\n# pkg/m.py\nX = 1\n```'),
                         [('pkg/m.py', 'X = 1\n')])

    def test_path_on_first_body_line_is_recovered_for_code_language(self):
        self.assertEqual(
            _named('```javascript\noutput/app.js\nconst x = 1;\n```'),
            [('output/app.js', 'const x = 1;\n')],
        )

    def test_text_fence_may_legitimately_begin_with_a_filename(self):
        self.assertEqual(
            parse_changes('```text\nnotes.txt\nlisted content\n```'), [])

    def test_path_on_the_line_above_the_fence(self):
        # The aider convention: models trained on it put the name here.
        self.assertEqual(_named('pkg/m.py\n```python\nX = 1\n```'),
                         [('pkg/m.py', 'X = 1\n')])

    def test_prose_above_the_fence_is_not_a_path(self):
        self.assertEqual(_named("Here's the code:\n```python\nX = 1\n```"), [])

    def test_comment_styles_other_than_hash(self):
        for marker in ('//', '--', ';'):
            with self.subTest(marker=marker):
                self.assertEqual(
                    _named(f'```c\n{marker} m.c\nint x;\n```'),
                    [('m.c', 'int x;\n')])

    def test_unnamed_fence_is_not_a_write(self):
        self.assertEqual(parse_changes('```python\nX = 1\n```'), [])

    def test_prose_comment_is_not_a_path(self):
        self.assertEqual(parse_changes('```python\n# draw the thing\nX = 1\n```'), [])

    def test_shell_fences_are_never_writes(self):
        for lang in SHELL_LANGUAGES:
            with self.subTest(lang=lang):
                self.assertEqual(parse_changes(f'```{lang}\nls\n```'), [])

    def test_shell_fence_naming_a_path_is_still_a_command(self):
        # `sh deploy.sh` on a fence line is an invocation, not a file to write.
        self.assertEqual(parse_changes('```sh deploy.sh\nls\n```'), [])

    def test_tags_and_fences_interleave_in_reply_order(self):
        reply = (_write_tag('a.py', 'A') + '\n```python b.py\nB\n```\n'
                 + _write_tag('c.py', 'C'))
        self.assertEqual([c.path for c in parse_changes(reply)],
                         ['a.py', 'b.py', 'c.py'])

    def test_content_is_kept_verbatim_including_braces(self):
        body = 'def f():\n    return {"a": 1}\n'
        self.assertEqual(_named(f'```python m.py\n{body}```'),
                         [('m.py', body)])

    def test_unwritten_code_detection(self):
        self.assertTrue(has_unwritten_code('```python\nX = 1\n```'))
        self.assertFalse(has_unwritten_code('```python m.py\nX = 1\n```'))
        self.assertFalse(has_unwritten_code('```bash\nls\n```'))
        self.assertFalse(has_unwritten_code('just prose'))
        self.assertFalse(has_unwritten_code(None))


class UnlabelledFenceTest(unittest.TestCase):
    """A bare ``` fence is the one models emit most often.

    It used to match nothing at all: not written, and not flagged either, so a
    reply that showed a whole file produced an empty workspace in silence.
    """

    def test_the_reply_that_wrote_nothing(self):
        # Reported verbatim: a bare fence whose info string landed on the
        # body's first line, carrying a create-form SEARCH/REPLACE.
        reply = (
            '```\n'
            'python output/coding2/dumdum.py\n'
            '<<<<<<< SEARCH\n'
            '=======\n'
            'def greet_dumdum(name):\n'
            '    """Greet someone with \'Dumdum\'."""\n'
            '    return f"Dumdum, {name}!"\n'
            '\n'
            'user_name = input("What is your name? ")\n'
            'print(greet_dumdum(user_name))\n'
            '>>>>>>> REPLACE\n'
            '```\n\n'
            'To run it:\n```bash\npython3 output/coding2/dumdum.py\n```\n')
        changes = parse_changes(reply)
        self.assertEqual([c.path for c in changes],
                         ['output/coding2/dumdum.py'])
        content = changes[0].apply(None)
        self.assertIn('def greet_dumdum(name):', content)
        self.assertIn('    return f"Dumdum, {name}!"', content)
        self.assertNotIn('SEARCH', content)
        self.assertNotIn('python output/coding2/dumdum.py', content)

    def test_unlabelled_fence_with_a_path_comment(self):
        self.assertEqual(_named('```\n# m.py\nX = 1\n```'), [('m.py', 'X = 1\n')])

    def test_unlabelled_fence_takes_the_path_above_it(self):
        self.assertEqual(_named('m.py\n```\nX = 1\n```'), [('m.py', 'X = 1\n')])

    def test_unnamed_unlabelled_fence_is_flagged_not_written(self):
        self.assertEqual(parse_changes('```\nX = 1\n```'), [])
        self.assertTrue(has_unwritten_code('```\nX = 1\n```'))

    def test_path_alone_on_the_fence_line(self):
        # 'output' is not the language here; reading it as one used to leave
        # the path as '/coding2/d.py', which the workspace then refused.
        self.assertEqual(_named('```output/coding2/d.py\nX = 1\n```'),
                         [('output/coding2/d.py', 'X = 1\n')])

    def test_two_unlabelled_fences_pair_off(self):
        reply = '```\n# a.py\nA\n```\n```\n# b.py\nB\n```'
        self.assertEqual([c.path for c in parse_changes(reply)],
                         ['a.py', 'b.py'])

    def test_a_closing_fence_never_opens_a_block(self):
        self.assertEqual(_named('```python m.py\nX = 1\n```\n\nAll done.'),
                         [('m.py', 'X = 1\n')])


class SpilledInfoTest(unittest.TestCase):
    """The info string on the body's first line, not on the fence.

    Both a language and a path are required. A lone path-looking first line is
    far more likely to be content — a file listing — than a declaration, and a
    path on its own line is already read as a comment or from above the fence.
    """

    def test_language_and_path_are_taken_and_stripped(self):
        self.assertEqual(_named('```\npython m.py\nX = 1\n```'),
                         [('m.py', 'X = 1\n')])

    def test_a_lone_path_line_stays_content(self):
        self.assertEqual(parse_changes('```\noutput/a.py\noutput/b.py\n```'), [])

    def test_a_labelled_fence_keeps_its_first_line(self):
        # The fence already declared a language, so line one is code.
        self.assertEqual(_named('```python m.py\nimport os\nX = 1\n```'),
                         [('m.py', 'import os\nX = 1\n')])

    def test_a_line_of_code_is_not_a_declaration(self):
        self.assertEqual(parse_changes('```\nimport os\nX = 1\n```'), [])

    def test_an_import_of_a_dotted_module_is_not_a_declaration(self):
        # 'os.path' looks exactly like a path; 'import' is not a language.
        self.assertEqual(parse_changes('```\nimport os.path\nX = 1\n```'), [])


class IndentedFenceTest(unittest.TestCase):
    """A fence nested under a list item carries layout indentation.

    Left in place it pushes SEARCH/REPLACE markers off column 0, where
    _HAS_EDIT_MARKERS stops seeing them and the markers land in the file as
    content.
    """

    def test_indented_block_is_dedented(self):
        reply = '  ```python m.py\n  def f():\n      return 1\n  ```'
        self.assertEqual(_named(reply), [('m.py', 'def f():\n    return 1\n')])

    def test_indented_search_replace_still_parses(self):
        reply = ('  ```python m.py\n'
                 '  <<<<<<< SEARCH\n'
                 '  =======\n'
                 '  X = 1\n'
                 '  >>>>>>> REPLACE\n'
                 '  ```')
        self.assertEqual(_named(reply), [('m.py', 'X = 1\n')])

    def test_indented_create_form_writes_the_whole_body(self):
        # Reported as writing a file containing only '>>>>>>> REPLACE'.
        reply = (
            '  ```python drop.py\n'
            '  <<<<<<< SEARCH\n'
            '  =======\n'
            '  # drop.py\n'
            '  import os\n'
            '\n'
            '  def drop_directory(dir_path):\n'
            '      if os.path.exists(dir_path):\n'
            '          print("gone")\n'
            '\n'
            '  if __name__ == "__main__":\n'
            '      drop_directory("x")\n'
            '  >>>>>>> REPLACE\n'
            '  ```')
        (path, content), = _named(reply)
        self.assertEqual(path, 'drop.py')
        self.assertTrue(content.startswith('# drop.py\nimport os\n'))
        self.assertIn('    if os.path.exists(dir_path):', content)
        self.assertNotIn('REPLACE', content)
        self.assertNotIn('SEARCH', content)

    def test_a_normally_shaped_file_is_untouched(self):
        body = 'def f():\n    return 1\n'
        self.assertEqual(_named(f'```python m.py\n{body}```'), [('m.py', body)])


class CommandNameInferenceTest(unittest.TestCase):
    """One unnamed fence plus one filename in the commands is not ambiguous.
    Two of either is, and then it refuses."""

    def test_lone_unnamed_fence_takes_the_lone_command_filename(self):
        reply = ('```python\nimport sys\n```\n\n'
                 'You can run it with:\n```bash\npython flap.py\n```')
        self.assertEqual(_named(reply), [('flap.py', 'import sys\n')])

    def test_two_unnamed_fences_refuse(self):
        reply = ('```python\nA\n```\n```python\nB\n```\n'
                 '```bash\npython flap.py\n```')
        self.assertEqual(parse_changes(reply), [])

    def test_two_command_filenames_refuse(self):
        reply = ('```python\nA\n```\n'
                 '```bash\npython flap.py\npython other.py\n```')
        self.assertEqual(parse_changes(reply), [])

    def test_no_commands_means_no_inference(self):
        self.assertEqual(parse_changes('```python\nA\n```'), [])

    def test_a_named_fence_is_untouched_by_inference(self):
        reply = ('```python real.py\nA\n```\n```bash\npython other.py\n```')
        self.assertEqual([c.path for c in parse_changes(reply)], ['real.py'])

    def test_the_interpreter_itself_is_not_a_filename(self):
        # 'python3' has no extension and no separator, so only flap.py counts.
        reply = '```python\nA\n```\n```bash\npython3 flap.py\n```'
        self.assertEqual([c.path for c in parse_changes(reply)], ['flap.py'])


class UnwrittenFencesTest(unittest.TestCase):
    """How many fences would actually be lost, which is not the same question
    as whether a fence names a path."""

    def test_a_fence_the_inference_rescues_counts_zero(self):
        # The case the two questions differ on, and the reason this is not just
        # has_unwritten_code(): refusing here would reject a reply whose code
        # does reach disk.
        reply = '```python\nA\n```\n```bash\npython3 flap.py\n```'
        self.assertTrue(has_unwritten_code(reply))
        self.assertEqual(unwritten_fences(reply), 0)

    def test_every_unnamed_fence_is_counted(self):
        self.assertEqual(unwritten_fences('```python\nA\n```\n```python\nB\n```'), 2)

    def test_named_fences_count_zero(self):
        self.assertEqual(unwritten_fences('```python a.py\nA\n```'), 0)

    def test_shell_fences_are_commands_not_lost_files(self):
        self.assertEqual(unwritten_fences('```bash\nls\n```'), 0)

    def test_prose_counts_zero(self):
        self.assertEqual(unwritten_fences('just prose'), 0)
        self.assertEqual(unwritten_fences(None), 0)

    def test_a_fence_inside_a_write_tag_is_content_not_a_lost_file(self):
        # A markdown document holding a ```python example. The tag already
        # named the file; reading its body as structure would refuse the one
        # form that exists precisely to carry a closing fence.
        reply = _write_tag('doc.md', '```python\nx = 1\n```')
        self.assertEqual(unwritten_fences(reply), 0)
        self.assertFalse(has_unwritten_code(reply))
        self.assertEqual([c.path for c in parse_changes(reply)], ['doc.md'])


class WrittenPathsTest(unittest.TestCase):
    """parse_written_paths — applyFileWrites' own output, read back as a list
    of files to serve."""

    def test_created_and_updated_prefixes_are_stripped(self):
        self.assertEqual(
            parse_written_paths('CREATED: /tmp/ws/a.py\nUPDATED: /tmp/ws/b.py'),
            ['/tmp/ws/a.py', '/tmp/ws/b.py'])

    def test_a_bare_path_list_is_accepted(self):
        # So a workflow can assemble the list itself rather than only feeding
        # this handler's own format back in.
        self.assertEqual(parse_written_paths('a.py\npkg/b.py'), ['a.py', 'pkg/b.py'])

    def test_prose_lines_are_dropped(self):
        # '(no files written)' must not be served back as '(not found)'.
        self.assertEqual(parse_written_paths('(no files written)'), [])
        self.assertEqual(parse_written_paths(''), [])
        self.assertEqual(parse_written_paths(None), [])

    def test_a_repeated_path_is_listed_once(self):
        self.assertEqual(
            parse_written_paths('CREATED: a.py\nUPDATED: a.py'), ['a.py'])


def _sr(path, search, replace, lang='python'):
    return (f'```{lang} {path}\n<<<<<<< SEARCH\n{search}=======\n'
            f'{replace}>>>>>>> REPLACE\n```')


class SearchReplaceTest(unittest.TestCase):
    """Aider-style edits. A wrong-but-plausible edit is worse than a refused
    one, so a SEARCH that does not match exactly once raises."""

    def test_empty_search_creates_the_file(self):
        change = parse_changes(_sr('flap.py', '', 'import sys\n'))[0]
        self.assertEqual(change.path, 'flap.py')
        self.assertEqual(change.apply(None), 'import sys\n')

    def test_search_replaces_matching_text(self):
        change = parse_changes(_sr('m.py', 'PORT = 8080\n', 'PORT = 9090\n'))[0]
        self.assertEqual(change.apply('X = 1\nPORT = 8080\nY = 2\n'),
                         'X = 1\nPORT = 9090\nY = 2\n')

    def test_search_not_found_raises(self):
        change = parse_changes(_sr('m.py', 'ABSENT\n', 'NEW\n'))[0]
        with self.assertRaises(EditError) as caught:
            change.apply('something else\n')
        self.assertIn('not found', str(caught.exception))

    def test_ambiguous_search_raises(self):
        change = parse_changes(_sr('m.py', 'x = 1\n', 'x = 2\n'))[0]
        with self.assertRaises(EditError) as caught:
            change.apply('x = 1\nx = 1\n')
        self.assertIn('2 times', str(caught.exception))

    def test_editing_a_missing_file_raises(self):
        change = parse_changes(_sr('m.py', 'anything\n', 'new\n'))[0]
        with self.assertRaises(EditError) as caught:
            change.apply(None)
        self.assertIn('does not exist', str(caught.exception))

    def test_markers_without_a_complete_block_raise(self):
        change = parse_changes('```python m.py\n<<<<<<< SEARCH\nx\n```')[0]
        with self.assertRaises(EditError) as caught:
            change.apply('x\n')
        self.assertIn('no complete SEARCH/REPLACE', str(caught.exception))

    def test_several_edits_apply_in_order(self):
        body = ('```python m.py\n'
                '<<<<<<< SEARCH\nA\n=======\nB\n>>>>>>> REPLACE\n'
                '<<<<<<< SEARCH\nC\n=======\nD\n>>>>>>> REPLACE\n```')
        self.assertEqual(parse_changes(body)[0].apply('A\nC\n'), 'B\nD\n')

    def test_the_reply_that_started_this(self):
        # Empty SEARCH, no name on the fence, filename only in the bash block.
        reply = ('```python\n<<<<<<< SEARCH\n=======\n'
                 'import matplotlib.pyplot as plt\n>>>>>>> REPLACE\n```\n\n'
                 'You can run it with:\n```bash\npython flap.py\n```')
        changes = parse_changes(reply)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].path, 'flap.py')
        self.assertEqual(changes[0].apply(None),
                         'import matplotlib.pyplot as plt\n')
        # The conflict markers must not survive into the file.
        self.assertNotIn('SEARCH', changes[0].apply(None))


class WorkspaceRootTest(WorkspaceTestCase):

    def test_relative_path_resolves_under_the_base(self):
        workspace = WorkspaceRoot(self.root)
        self.assertEqual(workspace.resolve('pkg/a.py'),
                         workspace.base / 'pkg' / 'a.py')

    def test_escape_and_absolute_and_empty_resolve_to_none(self):
        workspace = WorkspaceRoot(self.root)
        self.assertIsNone(workspace.resolve('../out.py'))
        self.assertIsNone(workspace.resolve('/etc/passwd'))
        self.assertIsNone(workspace.resolve('   '))
        self.assertIsNone(workspace.resolve(None))


class PathNamingTest(WorkspaceTestCase):
    """One spelling of a file across the whole turn.

    The plan, the read list and the '=== path ===' headers are all
    workspace-relative. applyFileWrites used to be the one thing that was not,
    which left a review pass reconciling '/Users/…/api/client.py' with
    'api/client.py' and a terminal printing the reader's home directory in
    front of every filename.
    """

    def test_files_written_names_paths_relatively(self):
        result = self._apply('```python pkg/a.py\nA = 1\n```\n')
        self.assertEqual('CREATED: pkg/a.py', result['data'])
        self.assertNotIn(self.root, result['data'])

    def test_an_update_is_named_relatively_too(self):
        self._put('pkg/a.py', 'A = 0\n')
        result = self._apply('```python pkg/a.py\nA = 1\n```\n')
        self.assertEqual('UPDATED: pkg/a.py', result['data'])

    def test_the_drawn_labels_carry_no_absolute_path(self):
        self._put('b.py', 'B = 0\n')
        with _EventLog() as log:
            self._apply('```python a.py\nA = 1\n```\n'
                        '```python b.py\nB = 1\n```\n')
        drawn = ' '.join(log.outputs('file') + log.outputs('diff'))
        self.assertIn('a.py written', drawn)
        self.assertIn('b.py updated', drawn)
        self.assertNotIn(self.root, drawn)

    def test_a_read_label_carries_no_absolute_path(self):
        self._put('a.py', 'print(1)\n')
        with _EventLog() as log:
            self._serve('<read_file><path>a.py</path></read_file>')
        self.assertIn('a.py read', ' '.join(log.outputs('read')))
        self.assertNotIn(self.root, ' '.join(log.outputs('read')))

    def test_the_relative_result_still_round_trips_through_pathskey(self):
        # The whole point of the old absolute form was that serveFileReads
        # could take applyFileWrites' output back. That must keep working.
        self._put('a.py', 'print(1)\n')
        written = self._apply('```python a.py\nprint(2)\n```\n')['data']
        served = self._serve('', ctx={'files_written': written},
                             pathsKey='files_written')['data']
        self.assertIn('=== a.py ===', served)
        self.assertIn('print(2)', served)


class UndecodableFileTest(WorkspaceTestCase):
    """A file that is not UTF-8 is refused by both halves, identically.

    serveFileReads used to read with errors='replace' and hand back U+FFFD
    where the bad bytes were — text a model quotes into a SEARCH block that can
    then never match. applyFileWrites read the same file strictly inside an
    `except OSError`, and UnicodeDecodeError is a ValueError, so it left the
    handler and ended the run.
    """

    def _put_bytes(self, rel, raw):
        path = os.path.join(self.root, rel)
        with open(path, 'wb') as fh:
            fh.write(raw)
        return path

    BAD = b'alpha = 1\n\xff\xfe not text\n'

    def test_serving_says_it_cannot_be_read_rather_than_substituting(self):
        self._put_bytes('bad.py', self.BAD)
        data = self._serve('<read_file><path>bad.py</path></read_file>')['data']
        self.assertIn('=== bad.py ===', data)
        self.assertIn('not valid UTF-8', data)
        self.assertNotIn('�', data)
        self.assertNotIn('alpha = 1', data)

    def test_editing_it_is_an_error_and_not_an_exception(self):
        self._put_bytes('bad.py', self.BAD)
        result = self._apply('```python bad.py\n'
                             '<<<<<<< SEARCH\nalpha = 1\n'
                             '=======\nalpha = 2\n>>>>>>> REPLACE\n```\n')
        self.assertIsNone(result['data'])
        self.assertIn('not valid UTF-8', result['error'])
        self.assertIn('bad.py', result['error'])

    def test_the_file_is_left_exactly_as_it_was(self):
        self._put_bytes('bad.py', self.BAD)
        self._apply('```python bad.py\n'
                    '<<<<<<< SEARCH\nalpha = 1\n'
                    '=======\nalpha = 2\n>>>>>>> REPLACE\n```\n')
        with open(os.path.join(self.root, 'bad.py'), 'rb') as fh:
            self.assertEqual(self.BAD, fh.read())

    def test_a_refused_file_does_not_stop_the_others_being_served(self):
        self._put_bytes('bad.py', self.BAD)
        self._put('good.py', 'print(1)\n')
        data = self._serve('<read_file><path>bad.py</path></read_file>'
                           '<read_file><path>good.py</path></read_file>')['data']
        self.assertIn('not valid UTF-8', data)
        self.assertIn('print(1)', data)


class TruncationNoticeTest(WorkspaceTestCase):
    """A truncated file must not be rewritten whole from what was shown.

    The marker used to say only that the text was cut. A model told to 'send
    the complete file when restructuring' would then rebuild it from the part
    it saw, and applyFileWrites would write that — losing everything past the
    cap without a word.
    """

    def test_the_marker_says_the_file_is_incomplete_and_what_to_do(self):
        self._put('big.py', 'x = 1\n' * 400)
        data = self._serve('<read_file><path>big.py</path></read_file>',
                           maxBytes=100)['data']
        self.assertIn('truncated at 100', data)
        self.assertIn('NOT been shown this whole file', data)
        self.assertIn('SEARCH/REPLACE', data)

    def test_a_file_under_the_cap_carries_no_marker(self):
        self._put('small.py', 'x = 1\n')
        data = self._serve('<read_file><path>small.py</path></read_file>',
                           maxBytes=100)['data']
        self.assertNotIn('truncated', data)


if __name__ == '__main__':
    unittest.main()
