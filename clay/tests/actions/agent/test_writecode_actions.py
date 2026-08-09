"""Unit tests for writecode_actions (writeCode) handler."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import writecode_actions
from ....actions.agent.writecode_actions import _strip_fences


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

    def test_writes_stripped_content_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "output.py")
            result = writecode_actions.handler(
                {"id": "out", "contentKey": "code", "file": path},
                {"code": "```python\ndef foo():\n    pass\n```"}
            )
            self.assertIsNotNone(result)
            with open(path) as f:
                self.assertEqual(f.read(), "def foo():\n    pass")

    def test_returns_file_path_as_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.py")
            result = writecode_actions.handler(
                {"id": "out", "contentKey": "code", "file": path},
                {"code": "x = 1"}
            )
            self.assertEqual(result["data"], path)

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "src", "lib", "util.py")
            writecode_actions.handler(
                {"id": "out", "contentKey": "code", "file": path},
                {"code": "pass"}
            )
            self.assertTrue(os.path.exists(path))

    def test_file_template_interpolated_from_context(self):
        with tempfile.TemporaryDirectory() as d:
            template = os.path.join(d, "{filename}.py")
            result = writecode_actions.handler(
                {"id": "out", "contentKey": "code", "file": template},
                {"code": "x = 1", "filename": "my_module"}
            )
            self.assertTrue(result["data"].endswith("my_module.py"))
            self.assertTrue(os.path.exists(result["data"]))

    def test_missing_content_key_returns_none(self):
        with patch('builtins.print'):
            result = writecode_actions.handler(
                {"id": "out", "file": "/tmp/x.py"}, {}
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
        with tempfile.TemporaryDirectory() as d, patch('builtins.print'):
            result = writecode_actions.handler(
                {"id": "out", "contentKey": "missing", "file": os.path.join(d, "x.py")},
                {}
            )
        self.assertIsNone(result)

    def test_no_fence_content_written_as_is(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.py")
            writecode_actions.handler(
                {"id": "out", "contentKey": "code", "file": path},
                {"code": "def bar():\n    return 42"}
            )
            with open(path) as f:
                self.assertEqual(f.read(), "def bar():\n    return 42")


if __name__ == '__main__':
    unittest.main()
