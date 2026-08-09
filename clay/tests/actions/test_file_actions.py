"""Unit tests for file_actions (writeFile) handler."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ...actions import file_actions


class TestFileActions(unittest.TestCase):

    def test_writes_content_to_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "output.txt")
            result = file_actions.handler(
                {"id": "out", "file": path, "content": "body"},
                {"body": "hello world"}
            )
            self.assertIsNotNone(result)
            with open(path) as f:
                self.assertEqual(f.read(), "hello world")

    def test_returns_file_path_as_data(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.txt")
            result = file_actions.handler(
                {"id": "out", "file": path, "content": "body"},
                {"body": "x"}
            )
            self.assertEqual(result["data"], path)

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "subdir", "deep", "out.txt")
            file_actions.handler(
                {"id": "out", "file": path, "content": "body"},
                {"body": "data"}
            )
            self.assertTrue(os.path.exists(path))

    def test_file_template_interpolated_from_context(self):
        with tempfile.TemporaryDirectory() as d:
            result = file_actions.handler(
                {"id": "out", "file": os.path.join(d, "{name}.txt"), "content": "body"},
                {"name": "report", "body": "content here"}
            )
            self.assertTrue(result["data"].endswith("report.txt"))
            self.assertTrue(os.path.exists(result["data"]))

    def test_missing_file_field_returns_error(self):
        with patch('builtins.print'):
            result = file_actions.handler(
                {"id": "out", "content": "body"},
                {"body": "x"}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "out")
        self.assertIn("error", result)

    def test_missing_content_field_returns_error(self):
        with tempfile.TemporaryDirectory() as d, patch('builtins.print'):
            result = file_actions.handler(
                {"id": "out", "file": os.path.join(d, "out.txt")},
                {}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "out")
        self.assertIn("error", result)

    def test_content_key_not_in_ctx_returns_error(self):
        with tempfile.TemporaryDirectory() as d, patch('builtins.print'):
            result = file_actions.handler(
                {"id": "out", "file": os.path.join(d, "out.txt"), "content": "missing_key"},
                {}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "out")
        self.assertIn("error", result)

    def test_unknown_placeholder_left_as_is_in_path(self):
        # SafeMap: unresolved placeholders stay in the path
        with tempfile.TemporaryDirectory() as d:
            result = file_actions.handler(
                {"id": "out", "file": os.path.join(d, "{unknown}.txt"), "content": "body"},
                {"body": "data"}
            )
            self.assertIsNotNone(result)
            self.assertIn("{unknown}", result["data"])

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.txt")
            with open(path, 'w') as f:
                f.write("old content")
            file_actions.handler(
                {"id": "out", "file": path, "content": "body"},
                {"body": "new content"}
            )
            with open(path) as f:
                self.assertEqual(f.read(), "new content")


if __name__ == '__main__':
    unittest.main()
