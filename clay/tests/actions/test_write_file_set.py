"""Unit tests for writeFileSet — manifest-driven code file output."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ...actions.core.write_file_set import handler
from ...run import workspaces


def _manifest(files):
    return json.dumps({"files": files})


def _run(root, raw, **extra):
    action = {"id": "files_written", "type": "writeFileSet",
              "manifest": "code_manifest", "root": root, **extra}
    return handler(action, {"code_manifest": raw})


class WriteFileSetTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        # This test's own register, holding this test's own directory — see
        # clay/tests/run/test_workspaces.py. Kept outside self.root because
        # _tree() walks it and would otherwise count the register as output.
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

    def _tree(self):
        found = []
        for base, _, names in os.walk(self.root):
            for name in names:
                found.append(os.path.relpath(os.path.join(base, name), self.root))
        return sorted(found)

    def test_writes_every_file_in_the_manifest(self):
        result = _run(self.root, _manifest([
            {"path": "pkg/mod.py", "content": "print('a')\n"},
            {"path": "README.md", "content": "# hi\n"},
        ]))
        self.assertIsNone(result.get("error"))
        self.assertEqual(self._tree(), ["README.md", os.path.join("pkg", "mod.py")])
        with open(os.path.join(self.root, "pkg", "mod.py")) as fh:
            self.assertEqual(fh.read(), "print('a')\n")
        self.assertIn("CREATED:", result["data"])

    def test_empty_manifest_is_a_successful_no_op(self):
        result = _run(self.root, _manifest([]))
        self.assertIsNone(result.get("error"))
        self.assertEqual(result["data"], "")
        self.assertEqual(self._tree(), [])

    def test_fenced_json_is_tolerated(self):
        raw = "```json\n" + _manifest([{"path": "a.txt", "content": "x"}]) + "\n```"
        result = _run(self.root, raw)
        self.assertIsNone(result.get("error"))
        self.assertEqual(self._tree(), ["a.txt"])

    def test_invalid_json_is_an_error_result_not_a_crash(self):
        result = _run(self.root, "here are your files: a.txt")
        self.assertIsNone(result["data"])
        self.assertIn("not valid JSON", result["error"])
        self.assertEqual(self._tree(), [])

    def test_path_escape_writes_nothing(self):
        result = _run(self.root, _manifest([
            {"path": "safe.txt", "content": "ok"},
            {"path": "../escape.txt", "content": "bad"},
        ]))
        self.assertIn("escapes the root", result["error"])
        # All-or-nothing: the safe file was not written either.
        self.assertEqual(self._tree(), [])

    def test_absolute_path_rejected(self):
        result = _run(self.root, _manifest([{"path": "/etc/evil", "content": "x"}]))
        self.assertIn("absolute paths", result["error"])
        self.assertEqual(self._tree(), [])

    def test_missing_content_rejected(self):
        result = _run(self.root, _manifest([{"path": "a.txt"}]))
        self.assertIn('missing "content"', result["error"])
        self.assertEqual(self._tree(), [])

    def test_max_files_enforced(self):
        files = [{"path": f"f{i}.txt", "content": "x"} for i in range(3)]
        result = _run(self.root, _manifest(files), maxFiles=2)
        self.assertIn("limit is 2", result["error"])
        self.assertEqual(self._tree(), [])

    def test_missing_manifest_key_is_an_error(self):
        result = handler({"id": "out", "manifest": "nope", "root": self.root}, {})
        self.assertIn("no data for manifest key", result["error"])


if __name__ == '__main__':
    unittest.main()
