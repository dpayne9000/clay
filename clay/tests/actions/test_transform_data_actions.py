"""Unit tests for transform_data_actions handler."""

import unittest
from unittest.mock import patch

from ...actions import transform_data_actions


class TestTransformDataActions(unittest.TestCase):

    def test_missing_source_key_returns_none(self):
        with patch('builtins.print'):
            result = transform_data_actions.handler(
                {"id": "out", "method": "map", "source": "data"},
                {}
            )
        self.assertIsNone(result)

    def test_unknown_method_returns_none(self):
        with patch('builtins.print'):
            result = transform_data_actions.handler(
                {"id": "out", "method": "reverse", "source": "data"},
                {"data": [1, 2, 3]}
            )
        self.assertIsNone(result)

    def test_map_multiplies_by_two(self):
        result = transform_data_actions.handler(
            {"id": "out", "method": "map", "source": "nums"},
            {"nums": [1, 2, 3]}
        )
        self.assertEqual(result["data"], [2, 4, 6])

    def test_map_empty_list(self):
        result = transform_data_actions.handler(
            {"id": "out", "method": "map", "source": "nums"},
            {"nums": []}
        )
        self.assertEqual(result["data"], [])

    def test_parse_lines_splits_text_into_dict(self):
        result = transform_data_actions.handler(
            {"id": "out", "method": "parseLines", "source": "text"},
            {"text": "line one\nline two\nline three"}
        )
        self.assertEqual(result["data"][1], "line one")
        self.assertEqual(result["data"][2], "line two")
        self.assertEqual(result["data"][3], "line three")

    def test_parse_lines_single_line(self):
        result = transform_data_actions.handler(
            {"id": "out", "method": "parseLines", "source": "text"},
            {"text": "only line"}
        )
        self.assertEqual(result["data"][1], "only line")

    def test_parse_lines_on_non_string_converts(self):
        result = transform_data_actions.handler(
            {"id": "out", "method": "parseLines", "source": "val"},
            {"val": 42}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["data"][1], "42")

    def test_id_preserved_in_result(self):
        result = transform_data_actions.handler(
            {"id": "my_transform", "method": "map", "source": "nums"},
            {"nums": [5]}
        )
        self.assertEqual(result["id"], "my_transform")


if __name__ == '__main__':
    unittest.main()
