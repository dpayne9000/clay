"""startup.json — the user's copy is authoritative, the packaged one is a seed.

Asserted against patched module paths, never against a real ~/.clay: these are
assertions about the reading rules, and touching the developer's own directory
would make them pass or fail on the machine rather than on the code.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ...lib import config


CODING = {'user': ['workflows/system/coding/main.json'], 'daemon': []}
CLAY = {'user': ['workflows/system/clay/main.json'], 'daemon': []}
CUSTOM = {'user': ['workflows/my-assistant/main.json'], 'daemon': []}


class StartupSourceTest(unittest.TestCase):
    """load_startup seeds the user directory, then prefers what is there."""

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.package = tempfile.TemporaryDirectory()
        self.addCleanup(self.package.cleanup)

        self.user_path = os.path.join(self.home.name, 'startup.json')
        self.base_path = os.path.join(self.package.name, 'startup.json')
        self._write(self.base_path, CODING)

        patcher = patch.multiple(
            config,
            clay_dir=self.home.name,
            _STARTUP_PATH=self.user_path,
            _BASE_STARTUP_PATH=self.base_path,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _write(path, data):
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)

    def test_the_packaged_copy_is_seeded_on_first_read(self):
        self.assertFalse(os.path.exists(self.user_path))
        self.assertEqual(config.load_startup(), CODING)
        self.assertTrue(os.path.isfile(self.user_path))

    def test_the_user_copy_wins_over_the_packaged_one(self):
        self._write(self.user_path, CUSTOM)
        self.assertEqual(config.load_startup(), CUSTOM)

    def test_an_upgrade_never_reverts_the_user_choice(self):
        """Create-or-fail, not overwrite. The packaged value changing in a new
        release must not silently move a workflow someone chose."""
        self._write(self.user_path, CUSTOM)
        self._write(self.base_path, CODING)
        config.load_startup()
        with open(self.user_path, encoding='utf-8') as handle:
            self.assertEqual(json.load(handle), CUSTOM)

    def test_recognized_legacy_default_moves_to_new_shipped_default(self):
        old = {'user': ['workflows/system/coding/main.json'], 'daemon': []}
        new = {'_startupVersion': 2, '_defaultManaged': True,
               'user': ['workflows/system/chat/main.json'], 'daemon': []}
        self._write(self.user_path, old)
        self._write(self.base_path, new)

        self.assertEqual(config.load_startup(), new)

    def test_cli_selected_default_is_not_changed_by_upgrade(self):
        selected = {'_startupVersion': 1, '_defaultManaged': False,
                    'user': ['workflows/system/coding/main.json'], 'daemon': []}
        new = {'_startupVersion': 2, '_defaultManaged': True,
               'user': ['workflows/system/chat/main.json'], 'daemon': []}
        self._write(self.user_path, selected)
        self._write(self.base_path, new)

        self.assertEqual(config.load_startup(), selected)

    def test_a_corrupt_user_copy_is_recreated_from_the_package(self):
        with open(self.user_path, 'w', encoding='utf-8') as handle:
            handle.write('{not json')
        self.assertEqual(config.load_startup(), CODING)

    def test_a_non_dict_user_copy_falls_back_to_the_package(self):
        self._write(self.user_path, ['workflows/system/clay/main.json'])
        self.assertEqual(config.load_startup(), CODING)

    def test_an_unwritable_user_directory_still_starts_something(self):
        """An installed clay on a read-only home has to resolve a workflow."""
        with patch.object(config, 'ensure_user_dir',
                          side_effect=OSError('read-only')):
            self.assertEqual(config.load_startup(), CODING)

    def test_no_readable_copy_anywhere_returns_empty(self):
        os.remove(self.base_path)
        with patch.object(config, 'ensure_user_dir',
                          side_effect=OSError('read-only')):
            self.assertEqual(config.load_startup(), {})


class StartupPathTest(unittest.TestCase):

    def test_the_user_copy_sits_beside_config_json(self):
        self.assertEqual(os.path.dirname(config._STARTUP_PATH),
                         os.path.dirname(config._CONFIG_PATH))
        self.assertEqual(os.path.basename(config._STARTUP_PATH),
                         'startup.json')

    def test_the_packaged_copy_is_the_one_that_ships(self):
        self.assertEqual(config._BASE_STARTUP_PATH,
                         config.data_path('configs', 'startup.json'))


if __name__ == '__main__':
    unittest.main()
