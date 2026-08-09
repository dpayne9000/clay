"""Unit tests for skill_actions handlers."""

import os
import tempfile
import unittest
from unittest.mock import patch

from ....actions.agent import skill_actions
from ..fixtures import temp_skills_base
from ...test_core import _EventLog


class TestWriteSkill(unittest.TestCase):

    def test_write_creates_file(self):
        with temp_skills_base(skill_actions) as base:
            result = skill_actions.write_handler(
                {"id": "saved", "skillset": "test", "name": "my-script",
                 "extension": "py", "content": "code"},
                {"code": "print('hi')"}
            )
            self.assertIsNotNone(result)
            self.assertTrue(os.path.exists(result["data"]))
            with open(result["data"]) as f:
                self.assertEqual(f.read(), "print('hi')")

    def test_write_disallowed_extension_returns_none(self):
        with temp_skills_base(skill_actions), patch('builtins.print'):
            result = skill_actions.write_handler(
                {"id": "saved", "skillset": "test", "name": "x",
                 "extension": "exe", "content": "code"},
                {"code": "data"}
            )
        self.assertIsNone(result)

    def test_write_missing_skillset_returns_none(self):
        with temp_skills_base(skill_actions), patch('builtins.print'):
            result = skill_actions.write_handler(
                {"id": "saved", "name": "x", "content": "code"},
                {"code": "data"}
            )
        self.assertIsNone(result)

    def test_write_missing_content_key_returns_none(self):
        with temp_skills_base(skill_actions), patch('builtins.print'):
            result = skill_actions.write_handler(
                {"id": "saved", "skillset": "test", "name": "x",
                 "extension": "py", "content": "missing_key"},
                {}
            )
        self.assertIsNone(result)

    def test_write_allowed_extensions(self):
        for ext in ("py", "json", "txt", "sh"):
            with temp_skills_base(skill_actions) as base:
                result = skill_actions.write_handler(
                    {"id": "s", "skillset": "test", "name": "x",
                     "extension": ext, "content": "c"},
                    {"c": "content"}
                )
            self.assertIsNotNone(result, f"Extension {ext!r} should be allowed")

    def test_file_path_contains_skillset_and_name(self):
        with temp_skills_base(skill_actions) as base:
            result = skill_actions.write_handler(
                {"id": "s", "skillset": "myskills", "name": "my-tool",
                 "extension": "py", "content": "c"},
                {"c": "def f(): pass"}
            )
        self.assertIn("myskills", result["data"])
        self.assertIn("my-tool", result["data"])


class TestListSkills(unittest.TestCase):

    def test_empty_skillset_returns_empty_string(self):
        with temp_skills_base(skill_actions):
            result = skill_actions.list_handler(
                {"id": "idx", "skillset": "empty-set"}, {}
            )
        self.assertEqual(result["data"], "")

    def test_lists_filenames(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "myskills")
            os.makedirs(d)
            open(os.path.join(d, "arp-scanner.py"), 'w').close()
            open(os.path.join(d, "port-scanner.py"), 'w').close()
            result = skill_actions.list_handler({"id": "idx", "skillset": "myskills"}, {})
        self.assertIn("arp-scanner.py", result["data"])
        self.assertIn("port-scanner.py", result["data"])

    def test_excludes_dotfiles(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "dots")
            os.makedirs(d)
            open(os.path.join(d, ".gitkeep"), 'w').close()
            open(os.path.join(d, "real.py"), 'w').close()
            result = skill_actions.list_handler({"id": "idx", "skillset": "dots"}, {})
        self.assertNotIn(".gitkeep", result["data"])
        self.assertIn("real.py", result["data"])


class TestRemoveSkill(unittest.TestCase):

    def test_remove_deletes_file(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "rm-test")
            os.makedirs(d)
            path = os.path.join(d, "tool.py")
            open(path, 'w').close()
            skill_actions.remove_handler(
                {"id": "removed", "skillset": "rm-test", "name": "tool", "extension": "py"}, {}
            )
            self.assertFalse(os.path.exists(path))

    def test_remove_missing_file_non_fatal(self):
        with temp_skills_base(skill_actions), patch('builtins.print'):
            result = skill_actions.remove_handler(
                {"id": "removed", "skillset": "ghost", "name": "none", "extension": "py"}, {}
            )
        self.assertIsNotNone(result)


class TestSearchSkills(unittest.TestCase):

    def test_matches_query_keyword(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "search-test")
            os.makedirs(d)
            open(os.path.join(d, "arp-scanner.py"), 'w').close()
            open(os.path.join(d, "port-scanner.py"), 'w').close()
            open(os.path.join(d, "dns-resolver.py"), 'w').close()
            result = skill_actions.search_handler(
                {"id": "found", "skillset": "search-test", "query": "scanner"}, {}
            )
        self.assertIn("arp-scanner.py", result["data"])
        self.assertIn("port-scanner.py", result["data"])
        self.assertNotIn("dns-resolver.py", result["data"])

    def test_query_from_context_key(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "key-test")
            os.makedirs(d)
            open(os.path.join(d, "ping-sweep.py"), 'w').close()
            result = skill_actions.search_handler(
                {"id": "found", "skillset": "key-test", "queryKey": "q"},
                {"q": "ping"}
            )
        self.assertIn("ping-sweep.py", result["data"])

    def test_empty_query_returns_all(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "all-test")
            os.makedirs(d)
            open(os.path.join(d, "a.py"), 'w').close()
            open(os.path.join(d, "b.py"), 'w').close()
            result = skill_actions.search_handler(
                {"id": "found", "skillset": "all-test"}, {}
            )
        self.assertIn("a.py", result["data"])
        self.assertIn("b.py", result["data"])

    def test_better_keyword_overlap_ranks_higher(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "rank-test")
            os.makedirs(d)
            open(os.path.join(d, "redis-cache-session.py"), 'w').close()
            open(os.path.join(d, "redis-client-basic.py"), 'w').close()
            open(os.path.join(d, "unrelated-file.py"), 'w').close()
            result = skill_actions.search_handler(
                {"id": "out", "skillset": "rank-test",
                 "query": "redis cache session storage"},
                {}
            )
        files = result["data"].splitlines()
        self.assertIn("redis-cache-session.py", files)
        if "redis-client-basic.py" in files:
            self.assertLess(
                files.index("redis-cache-session.py"),
                files.index("redis-client-basic.py")
            )

    def test_no_match_returns_empty(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "no-match")
            os.makedirs(d)
            open(os.path.join(d, "jwt-auth-middleware.py"), 'w').close()
            result = skill_actions.search_handler(
                {"id": "out", "skillset": "no-match",
                 "query": "mongodb aggregation pipeline"},
                {}
            )
        self.assertNotIn("jwt-auth-middleware.py", result["data"])


class TestVisibleOutput(unittest.TestCase):
    """Skill handlers put their filenames and contents on the event bus.

    Asserted through _EventLog.outputs(kind) rather than by matching message
    text — which is the whole reason these are action.output and not log lines.
    """

    def test_a_written_skill_shows_its_path_and_contents(self):
        with temp_skills_base(skill_actions):
            with _EventLog() as log:
                skill_actions.write_handler(
                    {"id": "saved", "skillset": "test", "name": "greet",
                     "extension": "py", "content": "code"},
                    {"code": "print('hi')\nprint('there')"}
                )
        drawn = log.outputs('file')
        self.assertEqual(len(drawn), 1)
        self.assertIn('greet.py', drawn[0])
        self.assertIn('2 lines', drawn[0])
        self.assertIn("print('there')", drawn[0])

    def test_a_removed_skill_says_so_with_no_body(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "test")
            os.makedirs(d)
            open(os.path.join(d, "gone.py"), 'w').close()
            with _EventLog() as log:
                skill_actions.remove_handler(
                    {"id": "rm", "skillset": "test", "name": "gone",
                     "extension": "py"}, {}
                )
        drawn = log.outputs('file')
        self.assertEqual(len(drawn), 1)
        self.assertTrue(drawn[0].endswith('gone.py removed'))

    def test_a_listing_shows_what_it_loaded(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "test")
            os.makedirs(d)
            open(os.path.join(d, "alpha.py"), 'w').close()
            with _EventLog() as log:
                skill_actions.list_handler(
                    {"id": "ls", "skillset": "test"}, {}
                )
        drawn = log.outputs('read')
        self.assertEqual(len(drawn), 1)
        self.assertIn('1 skills', drawn[0])
        self.assertIn('alpha.py', drawn[0])

    def test_a_search_shows_its_ranked_result(self):
        with temp_skills_base(skill_actions) as base:
            d = os.path.join(base, "test")
            os.makedirs(d)
            open(os.path.join(d, "redis-cache-session.py"), 'w').close()
            with _EventLog() as log:
                skill_actions.search_handler(
                    {"id": "q", "skillset": "test", "query": "redis cache"}, {}
                )
        drawn = log.outputs('read')
        self.assertEqual(len(drawn), 1)
        self.assertIn('redis cache', drawn[0])
        self.assertIn('redis-cache-session.py', drawn[0])

    def test_a_hidden_action_draws_nothing(self):
        # The gate lives in logger.output, so no handler can leak past it.
        with temp_skills_base(skill_actions):
            with _EventLog() as log:
                skill_actions.write_handler(
                    {"id": "saved", "skillset": "test", "name": "quiet",
                     "extension": "py", "content": "code", "visible": False},
                    {"code": "print('hi')"}
                )
        self.assertEqual(log.outputs(), [])


class TestPackagedAndUserSkills(unittest.TestCase):

    def _roots(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        user = os.path.join(temporary.name, 'user')
        packaged = os.path.join(temporary.name, 'packaged')
        os.makedirs(os.path.join(user, 'tools'))
        os.makedirs(os.path.join(packaged, 'tools'))
        return user, packaged

    def test_listing_combines_packaged_and_user_names(self):
        user, packaged = self._roots()
        open(os.path.join(user, 'tools', 'user.py'), 'w').close()
        open(os.path.join(packaged, 'tools', 'shipped.py'), 'w').close()
        with patch.object(skill_actions, 'SKILLS_BASE', user), \
             patch.object(skill_actions, 'PACKAGED_SKILLS_BASE', packaged):
            result = skill_actions.list_handler(
                {'id': 'skills', 'skillset': 'tools'}, {})
        self.assertIn('user.py', result['data'])
        self.assertIn('shipped.py', result['data'])

    def test_remove_refuses_a_packaged_only_skill(self):
        user, packaged = self._roots()
        shipped = os.path.join(packaged, 'tools', 'shipped.py')
        open(shipped, 'w').close()
        with patch.object(skill_actions, 'SKILLS_BASE', user), \
             patch.object(skill_actions, 'PACKAGED_SKILLS_BASE', packaged):
            result = skill_actions.remove_handler(
                {'id': 'removed', 'skillset': 'tools', 'name': 'shipped'}, {})
        self.assertIsNone(result)
        self.assertTrue(os.path.isfile(shipped))


if __name__ == '__main__':
    unittest.main()
