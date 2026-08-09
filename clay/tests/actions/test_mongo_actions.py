"""Unit tests for mongo_actions handler (skipped when pymongo absent)."""

import unittest
from unittest.mock import patch, MagicMock

try:
    from ...actions import mongo_actions
    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False
    mongo_actions = None


def _mock_client(docs=None):
    docs = docs or []
    mock_col = MagicMock()
    mock_col.find.return_value = iter(docs)
    mock_db = MagicMock()
    mock_db.__getitem__.return_value = mock_col
    mock_client = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    return mock_client, mock_col


@unittest.skipUnless(HAS_PYMONGO, "pymongo not installed")
class TestMongoActions(unittest.TestCase):

    def test_missing_url_returns_none(self):
        with patch('builtins.print'):
            result = mongo_actions.handler(
                {"id": "out", "db": "mydb", "collection": "col"}, {}
            )
        self.assertIsNone(result)

    def test_missing_db_returns_none(self):
        with patch('builtins.print'):
            result = mongo_actions.handler(
                {"id": "out", "url": "mongodb://localhost", "collection": "col"}, {}
            )
        self.assertIsNone(result)

    def test_missing_collection_returns_none(self):
        with patch('builtins.print'):
            result = mongo_actions.handler(
                {"id": "out", "url": "mongodb://localhost", "db": "mydb"}, {}
            )
        self.assertIsNone(result)

    def test_successful_query_returns_documents(self):
        mock_client, _ = _mock_client(docs=[{"_id": 1, "name": "Alice"}])
        with patch('clay.actions.mongo_actions.MongoClient', return_value=mock_client), \
             patch('builtins.print'):
            result = mongo_actions.handler(
                {"id": "docs", "url": "mongodb://localhost",
                 "db": "mydb", "collection": "users"},
                {}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "docs")
        self.assertEqual(result["data"][0]["name"], "Alice")

    def test_client_closed_after_query(self):
        mock_client, _ = _mock_client()
        with patch('clay.actions.mongo_actions.MongoClient', return_value=mock_client), \
             patch('builtins.print'):
            mongo_actions.handler(
                {"id": "out", "url": "mongodb://localhost",
                 "db": "db", "collection": "col"},
                {}
            )
        mock_client.close.assert_called_once()

    def test_find_exception_returns_none(self):
        mock_client, mock_col = _mock_client()
        mock_col.find.side_effect = Exception("timeout")
        with patch('clay.actions.mongo_actions.MongoClient', return_value=mock_client), \
             patch('builtins.print'):
            result = mongo_actions.handler(
                {"id": "out", "url": "mongodb://localhost",
                 "db": "db", "collection": "col"},
                {}
            )
        self.assertIsNone(result)
        mock_client.close.assert_called_once()

    def test_empty_result_set(self):
        mock_client, _ = _mock_client(docs=[])
        with patch('clay.actions.mongo_actions.MongoClient', return_value=mock_client), \
             patch('builtins.print'):
            result = mongo_actions.handler(
                {"id": "out", "url": "mongodb://localhost",
                 "db": "db", "collection": "empty"},
                {}
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["data"], [])


if __name__ == '__main__':
    unittest.main()
