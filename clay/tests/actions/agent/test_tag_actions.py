"""Unit and workflow-layer tests for tag_actions."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import tag_actions
from ....run import engine
from ..fixtures import write_workflow, simple_workflow


class TestDeriveTags(unittest.TestCase):

    def test_returns_list_of_strings(self):
        tags = tag_actions.derive_tags("python flask web api")
        self.assertIsInstance(tags, list)
        self.assertTrue(all(isinstance(t, str) for t in tags))

    def test_keywords_extracted(self):
        tags = tag_actions.derive_tags("mongodb database connection pooling")
        self.assertIn("mongodb", tags)
        self.assertIn("database", tags)
        self.assertIn("connection", tags)

    def test_stopwords_excluded(self):
        tags = tag_actions.derive_tags("this is a test of the system")
        for stopword in ("this", "is", "the", "of"):
            self.assertNotIn(stopword, tags)

    def test_short_tokens_excluded(self):
        tags = tag_actions.derive_tags("go is a compiled language")
        self.assertNotIn("go", tags)
        self.assertNotIn("is", tags)

    def test_camelcase_split(self):
        tags = tag_actions.derive_tags("handleRequest processQueue buildResponse")
        joined = ' '.join(tags)
        self.assertIn("request", joined)
        self.assertIn("handle", joined)

    def test_respects_max_tags(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        tags = tag_actions.derive_tags(text, max_tags=3)
        self.assertLessEqual(len(tags), 3)

    def test_empty_text_returns_empty_list(self):
        self.assertEqual(tag_actions.derive_tags(""), [])

    def test_all_stopwords_returns_empty(self):
        self.assertEqual(tag_actions.derive_tags("the and or but in on at"), [])

    def test_output_is_lowercase(self):
        tags = tag_actions.derive_tags("Flask Django FastAPI SQLAlchemy")
        for t in tags:
            self.assertEqual(t, t.lower())

    def test_duplicate_tokens_rank_highest(self):
        tags = tag_actions.derive_tags("redis redis redis cache session storage")
        self.assertEqual(tags[0], "redis")

    def test_extra_context_words_may_appear(self):
        tags = tag_actions.derive_tags(
            "database migration schema",
            extra_context="authentication tokens jwt"
        )
        self.assertIn("database", tags)
        self.assertIn("migration", tags)


class TestTagsFromFilename(unittest.TestCase):

    def test_kebab_name_split(self):
        parts = tag_actions.tags_from_filename("express-app-scaffold.py")
        self.assertIn("express", parts)
        self.assertIn("app", parts)
        self.assertIn("scaffold", parts)

    def test_extension_stripped(self):
        parts = tag_actions.tags_from_filename("jwt-auth.py")
        self.assertNotIn("py", parts)

    def test_underscore_split(self):
        parts = tag_actions.tags_from_filename("mongo_connection_pool.py")
        self.assertIn("mongo", parts)
        self.assertIn("connection", parts)
        self.assertIn("pool", parts)

    def test_stopwords_excluded(self):
        parts = tag_actions.tags_from_filename("the-best-api.py")
        self.assertNotIn("the", parts)

    def test_short_segments_excluded(self):
        parts = tag_actions.tags_from_filename("db-connector.py")
        self.assertNotIn("db", parts)
        self.assertIn("connector", parts)

    def test_empty_filename_returns_empty(self):
        self.assertEqual(tag_actions.tags_from_filename(""), [])


class TestTagsToString(unittest.TestCase):

    def test_joins_with_comma_space(self):
        self.assertEqual(tag_actions.tags_to_string(["python", "flask", "api"]),
                         "python, flask, api")

    def test_empty_list_returns_empty_string(self):
        self.assertEqual(tag_actions.tags_to_string([]), "")

    def test_single_tag(self):
        self.assertEqual(tag_actions.tags_to_string(["redis"]), "redis")


class TestDerivatagsHandler(unittest.TestCase):

    def test_content_key_resolved(self):
        result = tag_actions.handler(
            {"id": "tags", "contentKey": "body"},
            {"body": "flask rest api authentication middleware"}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["id"], "tags")
        self.assertIn("flask", result["data"])

    def test_inline_content_fallback(self):
        result = tag_actions.handler(
            {"id": "tags", "content": "redis cache session"}, {}
        )
        self.assertIn("redis", result["data"])

    def test_content_key_takes_priority_over_inline(self):
        result = tag_actions.handler(
            {"id": "tags", "contentKey": "body", "content": "fallback"},
            {"body": "mongodb database aggregation"}
        )
        self.assertIn("mongodb", result["data"])

    def test_missing_content_returns_empty_string(self):
        with patch('builtins.print'):
            result = tag_actions.handler({"id": "tags", "contentKey": "missing"}, {})
        self.assertEqual(result["data"], "")

    def test_blank_content_returns_empty_string(self):
        with patch('builtins.print'):
            result = tag_actions.handler({"id": "tags", "content": "   "}, {})
        self.assertEqual(result["data"], "")

    def test_max_tags_field_respected(self):
        result = tag_actions.handler(
            {"id": "tags", "content": "alpha beta gamma delta epsilon zeta", "maxTags": 2}, {}
        )
        tags = [t.strip() for t in result["data"].split(",") if t.strip()]
        self.assertLessEqual(len(tags), 2)

    def test_result_is_comma_separated_string(self):
        result = tag_actions.handler(
            {"id": "tags", "content": "python flask api web framework"}, {}
        )
        self.assertIsInstance(result["data"], str)
        if result["data"]:
            parts = [p.strip() for p in result["data"].split(",")]
            self.assertTrue(all(p for p in parts))

    def test_id_preserved_in_result(self):
        result = tag_actions.handler(
            {"id": "my_tags", "content": "kubernetes deployment"}, {}
        )
        self.assertEqual(result["id"], "my_tags")

    def test_output_is_valid_for_memory_tagskey(self):
        """Output format must be usable as tagsKey in writeMemory (comma-separated lowercase)."""
        result = tag_actions.handler(
            {"id": "tags", "content": "kubernetes deployment orchestration helm charts"}, {}
        )
        tags = result["data"]
        self.assertTrue(tags.strip())
        parts = [p.strip() for p in tags.split(",") if p.strip()]
        self.assertGreater(len(parts), 0)
        for p in parts:
            self.assertEqual(p, p.lower())
            self.assertRegex(p, r'^[a-z][a-z0-9]*$')


class TestDeriveTagsWorkflowLayer(unittest.TestCase):

    def test_derivetags_output_stored_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = write_workflow(d, simple_workflow({"run": [
                {"id": "my_tags", "type": "deriveTags",
                 "contentKey": "body", "maxTags": 4}
            ]}))
            data = engine.run(path, initial_data={"body": "redis cache session expiry"})
        self.assertIn("my_tags", data)
        self.assertIn("redis", data["my_tags"])


if __name__ == '__main__':
    unittest.main()
