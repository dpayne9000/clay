"""Unit tests for memory_actions handlers."""

import json
import os
import unittest
from unittest.mock import patch

from ....actions.agent import memory_actions
from ..fixtures import temp_memory_base
from ...test_core import _EventLog


class TestWriteMemory(unittest.TestCase):

    def _write(self, base, content='hello world', tags='a, b', namespace='test'):
        with patch('builtins.print'):
            return memory_actions.write_handler(
                {"id": "mem", "namespace": namespace, "content": "c", "tagsKey": "t"},
                {"c": content, "t": tags}
            )

    def test_creates_json_file(self):
        with temp_memory_base(memory_actions) as base:
            result = self._write(base)
            entry_id = result["data"]
            path = os.path.join(base, "test", f"{entry_id}.json")
            self.assertTrue(os.path.exists(path))

    def test_stores_content_and_tags(self):
        with temp_memory_base(memory_actions) as base:
            result = self._write(base, content='important fact', tags='foo, bar')
            entry_id = result["data"]
            path = os.path.join(base, "test", f"{entry_id}.json")
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data["content"], "important fact")
            self.assertIn("foo", data["tags"])
            self.assertIn("bar", data["tags"])

    def test_missing_namespace_returns_none(self):
        with temp_memory_base(memory_actions), patch('builtins.print'):
            result = memory_actions.write_handler(
                {"id": "mem", "content": "c"},
                {"c": "something"}
            )
        self.assertIsNone(result)

    def test_missing_content_key_returns_none(self):
        with temp_memory_base(memory_actions), patch('builtins.print'):
            result = memory_actions.write_handler(
                {"id": "mem", "namespace": "test"},
                {}
            )
        self.assertIsNone(result)

    def test_missing_content_data_returns_none(self):
        with temp_memory_base(memory_actions), patch('builtins.print'):
            result = memory_actions.write_handler(
                {"id": "mem", "namespace": "test", "content": "missing_key"},
                {}
            )
        self.assertIsNone(result)

    def test_entry_id_ends_with_numeric_suffix(self):
        with temp_memory_base(memory_actions) as base:
            result = self._write(base, tags="python, cache")
            entry_id = result["data"]
        parts = entry_id.split("-")
        self.assertTrue(parts[-1].isdigit(), f"Last part not numeric: {entry_id!r}")

    def test_auto_tags_derived_when_tagskey_absent(self):
        with temp_memory_base(memory_actions) as base:
            with patch('builtins.print'):
                result = memory_actions.write_handler(
                    {"id": "mem", "namespace": "test", "content": "c"},
                    {"c": "redis cache session storage expiry"}
                )
            entry_id = result["data"]
            path = os.path.join(base, "test", f"{entry_id}.json")
            with open(path) as f:
                entry = json.load(f)
        self.assertGreater(len(entry["tags"]), 0)
        content_words = {"redis", "cache", "session", "storage", "expiry"}
        self.assertTrue(content_words & set(entry["tags"]))

    def test_explicit_tags_used_when_provided(self):
        with temp_memory_base(memory_actions) as base:
            result = self._write(base, tags="explicit, tags, here")
            entry_id = result["data"]
            path = os.path.join(base, "test", f"{entry_id}.json")
            with open(path) as f:
                entry = json.load(f)
        self.assertIn("explicit", entry["tags"])
        self.assertIn("tags", entry["tags"])


class TestSearchMemory(unittest.TestCase):

    def _write(self, base, content, tags='', namespace='test'):
        with patch('builtins.print'):
            return memory_actions.write_handler(
                {"id": "mem", "namespace": namespace, "content": "c", "tagsKey": "t"},
                {"c": content, "t": tags}
            )

    def test_finds_relevant_entry(self):
        with temp_memory_base(memory_actions) as base:
            self._write(base, 'python asyncio coroutines', tags='python, async')
            self._write(base, 'node express routing', tags='node, express')
            with patch('builtins.print'):
                result = memory_actions.search_handler(
                    {"id": "found", "namespace": "test", "query": "asyncio"}, {}
                )
        self.assertIn("asyncio", result["data"])
        self.assertNotIn("express", result["data"])

    def test_empty_namespace_returns_empty_string(self):
        with temp_memory_base(memory_actions):
            result = memory_actions.search_handler(
                {"id": "found", "namespace": "test"}, {}
            )
        self.assertEqual(result["data"], "")

    def test_missing_namespace_returns_none(self):
        with temp_memory_base(memory_actions), patch('builtins.print'):
            result = memory_actions.search_handler({"id": "found"}, {})
        self.assertIsNone(result)

    def test_no_query_returns_all(self):
        with temp_memory_base(memory_actions) as base:
            self._write(base, 'entry one', tags='')
            self._write(base, 'entry two', tags='')
            result = memory_actions.search_handler(
                {"id": "found", "namespace": "test"}, {}
            )
        self.assertIn("entry one", result["data"])
        self.assertIn("entry two", result["data"])

    def test_respects_max_results(self):
        with temp_memory_base(memory_actions) as base:
            for i in range(5):
                self._write(base, f'shared topic entry {i}', tags='shared')
            result = memory_actions.search_handler(
                {"id": "found", "namespace": "test", "query": "shared", "maxResults": 2}, {}
            )
        parts = result["data"].split("\n\n")
        self.assertLessEqual(len(parts), 2)

    def test_tag_match_ranks_higher_than_content_match(self):
        """Entry with query word in tags should rank above entry with it only in content."""
        with temp_memory_base(memory_actions) as base:
            self._write(base, 'generic content about web development',
                        tags='authentication, jwt, security', namespace='score_test')
            self._write(base, 'covers authentication mechanisms in web apps',
                        tags='web, apps, general', namespace='score_test')
            with patch('builtins.print'):
                result = memory_actions.search_handler(
                    {"id": "found", "namespace": "score_test", "query": "authentication"}, {}
                )
        self.assertIn("authentication", result["data"])
        first_entry = result["data"].split("\n\n")[0]
        self.assertTrue(
            "jwt" in first_entry or "security" in first_entry,
            f"Tag-matched entry should rank first, got: {first_entry[:200]!r}"
        )

    def test_query_from_context_key(self):
        with temp_memory_base(memory_actions) as base:
            self._write(base, 'flask REST API design', tags='flask, rest, api')
            with patch('builtins.print'):
                result = memory_actions.search_handler(
                    {"id": "found", "namespace": "test", "queryKey": "q"},
                    {"q": "flask api"}
                )
        self.assertIn("flask", result["data"])


class TestListMemory(unittest.TestCase):

    def _write(self, base, content='alpha'):
        with patch('builtins.print'):
            return memory_actions.write_handler(
                {"id": "mem", "namespace": "test", "content": "c"},
                {"c": content}
            )

    def test_returns_all_entry_ids(self):
        with temp_memory_base(memory_actions) as base:
            r1 = self._write(base, 'alpha')
            r2 = self._write(base, 'beta')
            with patch('builtins.print'):
                result = memory_actions.list_handler({"id": "lst", "namespace": "test"}, {})
        self.assertIn(r1["data"], result["data"])
        self.assertIn(r2["data"], result["data"])

    def test_missing_namespace_returns_none(self):
        with temp_memory_base(memory_actions), patch('builtins.print'):
            result = memory_actions.list_handler({"id": "lst"}, {})
        self.assertIsNone(result)


class TestReadMemory(unittest.TestCase):

    def _write(self, base, content):
        with patch('builtins.print'):
            return memory_actions.write_handler(
                {"id": "mem", "namespace": "test", "content": "c"},
                {"c": content}
            )

    def test_returns_entry_content(self):
        with temp_memory_base(memory_actions) as base:
            r = self._write(base, 'specific fact')
            with patch('builtins.print'):
                result = memory_actions.read_handler(
                    {"id": "rd", "namespace": "test", "entryId": r["data"]}, {}
                )
        self.assertIn("specific fact", result["data"])

    def test_missing_entry_returns_empty_string(self):
        with temp_memory_base(memory_actions):
            result = memory_actions.read_handler(
                {"id": "rd", "namespace": "test", "entryId": "nonexistent"}, {}
            )
        self.assertEqual(result["data"], "")

    def test_missing_namespace_returns_none(self):
        with temp_memory_base(memory_actions), patch('builtins.print'):
            result = memory_actions.read_handler({"id": "rd", "entryId": "x"}, {})
        self.assertIsNone(result)

    def test_write_then_read_roundtrip(self):
        with temp_memory_base(memory_actions) as base:
            r = self._write(base, 'specific unique fact about grpc')
            read_result = memory_actions.read_handler(
                {"id": "rd", "namespace": "test", "entryId": r["data"]}, {}
            )
        self.assertIn("grpc", read_result["data"])
        self.assertIn("specific unique fact", read_result["data"])


class TestVisibleOutput(unittest.TestCase):
    """Memory handlers put their filenames and contents on the event bus."""

    def _write(self, content, **extra):
        action = {"id": "saved", "type": "writeMemory",
                  "namespace": "test", "content": "c"}
        action.update(extra)
        return memory_actions.write_handler(action, {"c": content})

    def test_a_written_entry_shows_its_path_and_the_json_that_landed(self):
        with temp_memory_base(memory_actions):
            with _EventLog() as log:
                self._write('grpc retries need a deadline')
        drawn = log.outputs('file')
        self.assertEqual(len(drawn), 1)
        self.assertIn('.json written', drawn[0])
        self.assertIn('grpc retries need a deadline', drawn[0])

    def test_the_shown_json_is_the_file_on_disk(self):
        # Serialised once and both written and shown, so what a front-end
        # draws cannot disagree with what is on disk.
        with temp_memory_base(memory_actions):
            with _EventLog() as log:
                result = self._write('a fact worth keeping')
            path = os.path.join(memory_actions.MEMORY_BASE, 'test',
                                f'{result["data"]}.json')
            with open(path) as f:
                on_disk = f.read()
        body = log.outputs('file')[0].split('\n', 1)[1]
        self.assertEqual(body, on_disk)

    def test_a_read_shows_the_entry_it_loaded(self):
        with temp_memory_base(memory_actions):
            result = self._write('a fact about quic')
            with _EventLog() as log:
                memory_actions.read_handler(
                    {"id": "rd", "namespace": "test",
                     "entryId": result["data"]}, {}
                )
        drawn = log.outputs('read')
        self.assertEqual(len(drawn), 1)
        self.assertIn('read', drawn[0])
        self.assertIn('a fact about quic', drawn[0])

    def test_a_search_shows_what_it_put_in_context(self):
        # The same text a model is fed downstream, not a count of it.
        with temp_memory_base(memory_actions):
            self._write('the retry budget is thirty seconds')
            with _EventLog() as log:
                memory_actions.search_handler(
                    {"id": "q", "namespace": "test", "query": "retry"}, {}
                )
        drawn = log.outputs('read')
        self.assertEqual(len(drawn), 1)
        self.assertIn("for 'retry'", drawn[0])
        self.assertIn('the retry budget is thirty seconds', drawn[0])

    def test_a_listing_shows_its_entries(self):
        with temp_memory_base(memory_actions):
            self._write('something memorable')
            with _EventLog() as log:
                memory_actions.list_handler(
                    {"id": "ls", "namespace": "test"}, {}
                )
        drawn = log.outputs('read')
        self.assertEqual(len(drawn), 1)
        self.assertIn('1 entries', drawn[0])

    def test_a_hidden_write_draws_nothing(self):
        with temp_memory_base(memory_actions):
            with _EventLog() as log:
                self._write('quiet fact', visible=False)
        self.assertEqual(log.outputs(), [])

    def test_the_skill_dual_write_is_attributed_to_the_memory_action(self):
        # The dual write has no action of its own; a payload with empty
        # provenance is one a front-end cannot attribute or filter.
        from ....actions.agent import skill_actions
        from ..fixtures import temp_skills_base

        with temp_memory_base(memory_actions), temp_skills_base(skill_actions):
            with _EventLog() as log:
                self._write('reusable helper', skillset='test')

        payloads = [e for e in log.events
                    if e.get('type') == 'action.output' and e.get('kind') == 'file']
        self.assertEqual(len(payloads), 2)
        for event in payloads:
            self.assertEqual(event['id'], 'saved')
            self.assertEqual(event['action_type'], 'writeMemory')

    def test_a_hidden_write_also_silences_its_skill_dual_write(self):
        from ....actions.agent import skill_actions
        from ..fixtures import temp_skills_base

        with temp_memory_base(memory_actions), temp_skills_base(skill_actions):
            with _EventLog() as log:
                self._write('reusable helper', skillset='test', visible=False)
        self.assertEqual(log.outputs(), [])


if __name__ == '__main__':
    unittest.main()
