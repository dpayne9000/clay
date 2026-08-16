"""Unit tests for writecode_actions (writeCode) handler."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import writecode_actions
from ....actions.agent.writecode_actions import _strip_fences
from ....run import workspaces


class TestStripFences(unittest.TestCase):

    def test_python_fence_stripped(self):
        code = "```python\ndef foo():\n    pass\n```"
        self.assertEqual(_strip_fences(code), "def foo():\n    pass")

    def test_generic_fence_stripped(self):
        code = "```\nhello world\n```"
        self.assertEqual(_strip_fences(code), "hello world")

    def test_json_fence_stripped(self):
        code = '```json\n{"key": "value"}\n```'
        self.assertEqual(_strip_fences(code), '{"key": "value"}')

    def test_no_fence_returned_unchanged(self):
        code = "def foo():\n    pass"
        self.assertEqual(_strip_fences(code), code)

    def test_partial_fence_opening_stripped(self):
        # AI got cut off — no closing ```
        code = "```python\ndef foo():\n    pass"
        result = _strip_fences(code)
        self.assertNotIn("```", result)
        self.assertIn("def foo", result)

    def test_whitespace_stripped(self):
        code = "  ```python\ndef foo():\n    pass\n```  "
        result = _strip_fences(code)
        self.assertEqual(result, "def foo():\n    pass")


class TestWriteCodeHandler(unittest.TestCase):
    """`file` is passed as an absolute path throughout this class — that is
    the scenario F-45 fixed (an absolute path that resolves inside the
    approved root must be accepted). The root itself must still be approved
    before any write reaches it, same as every other action; setUp gives
    each test its own approved directory rather than routing around
    workspaces.authorize()."""

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

    def test_writes_stripped_content_to_file(self):
        path = os.path.join(self.root, "output.py")
        result = writecode_actions.handler(
            {"id": "out", "contentKey": "code", "file": path, "root": self.root},
            {"code": "```python\ndef foo():\n    pass\n```"}
        )
        self.assertIsNotNone(result)
        with open(path) as f:
            self.assertEqual(f.read(), "def foo():\n    pass")

    def test_returns_file_path_as_data(self):
        path = os.path.join(self.root, "out.py")
        result = writecode_actions.handler(
            {"id": "out", "contentKey": "code", "file": path, "root": self.root},
            {"code": "x = 1"}
        )
        # _resolve_path() resolves symlinks (Path.resolve()) for every path,
        # relative or absolute — unchanged by F-45's fix. On macOS /var is a
        # symlink to /private/var, so the returned path is the resolved
        # spelling even though `path` itself (from tempfile) is not.
        self.assertEqual(result["data"], os.path.realpath(path))

    def test_creates_parent_directories(self):
        path = os.path.join(self.root, "src", "lib", "util.py")
        writecode_actions.handler(
            {"id": "out", "contentKey": "code", "file": path, "root": self.root},
            {"code": "pass"}
        )
        self.assertTrue(os.path.exists(path))

    def test_file_template_interpolated_from_context(self):
        template = os.path.join(self.root, "{filename}.py")
        result = writecode_actions.handler(
            {"id": "out", "contentKey": "code", "file": template, "root": self.root},
            {"code": "x = 1", "filename": "my_module"}
        )
        self.assertTrue(result["data"].endswith("my_module.py"))
        self.assertTrue(os.path.exists(result["data"]))

    def test_missing_content_key_returns_none(self):
        with patch('builtins.print'):
            result = writecode_actions.handler(
                {"id": "out", "file": os.path.join(self.root, "x.py"), "root": self.root}, {}
            )
        self.assertIsNone(result)

    def test_missing_file_field_returns_none(self):
        with patch('builtins.print'):
            result = writecode_actions.handler(
                {"id": "out", "contentKey": "code"},
                {"code": "x = 1"}
            )
        self.assertIsNone(result)

    def test_content_key_not_in_ctx_returns_none(self):
        with patch('builtins.print'):
            result = writecode_actions.handler(
                {"id": "out", "contentKey": "missing",
                 "file": os.path.join(self.root, "x.py"), "root": self.root},
                {}
            )
        self.assertIsNone(result)

    def test_no_fence_content_written_as_is(self):
        path = os.path.join(self.root, "out.py")
        writecode_actions.handler(
            {"id": "out", "contentKey": "code", "file": path, "root": self.root},
            {"code": "def bar():\n    return 42"}
        )
        with open(path) as f:
            self.assertEqual(f.read(), "def bar():\n    return 42")


if __name__ == '__main__':
    unittest.main()
