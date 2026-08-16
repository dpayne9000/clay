"""Unit tests for write_file._resolve_path() — path confinement, not the
write itself. See docs/bugs/F-45-writefile-rejects-absolute-paths-under-approved-root.md
for the bug this closes: an absolute `file` that resolves inside the
approved root must be accepted, and one that escapes it must still be
refused — the same containment rule that already applied to relative paths.
"""

import os
import tempfile
import unittest

from unittest.mock import patch

from ....actions.core import write_file
from ....run import workspaces


class ResolvePathAbsoluteInputTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

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

    def test_an_absolute_path_inside_the_approved_root_is_accepted(self):
        requested = os.path.join(self.root, "out.py")
        output_path, error = write_file._resolve_path(
            {"file": requested, "root": self.root}, {})
        self.assertIsNone(error)
        self.assertEqual(str(output_path), os.path.realpath(requested))

    def test_an_absolute_path_outside_the_approved_root_still_escapes(self):
        with tempfile.TemporaryDirectory() as outside:
            requested = os.path.join(outside, "out.py")
            output_path, error = write_file._resolve_path(
                {"file": requested, "root": self.root}, {})
        self.assertIsNone(output_path)
        self.assertEqual(error, "writeFile: path escapes the configured output root")

    def test_a_relative_path_is_unaffected_by_this_fix(self):
        output_path, error = write_file._resolve_path(
            {"file": "out.py", "root": self.root}, {})
        self.assertIsNone(error)
        self.assertEqual(str(output_path), os.path.realpath(os.path.join(self.root, "out.py")))


if __name__ == '__main__':
    unittest.main()
