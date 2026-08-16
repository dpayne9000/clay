"""display.* — the character caps a front-end reads before drawing.

Asserted against a patched load_config, never against ~/.clay/config.json:
these are assertions about the reading rules, and reading the developer's own
config would make them pass or fail on the machine rather than on the code.
"""

import unittest
from unittest.mock import patch

from ...lib import config


def _config(display):
    """A parsed config carrying `display`, or no display key at all."""
    return {} if display is None else {'display': display}


class MaxTokensTest(unittest.TestCase):

    def _get(self, value):
        cfg = {} if value is None else {'maxTokens': value}
        with patch.object(config, 'load_config', return_value=cfg):
            return config.get_max_tokens()

    def test_the_configured_number_is_used(self):
        self.assertEqual(self._get(8192), 8192)

    def test_missing_or_invalid_values_use_the_default(self):
        for value in (None, 0, -1, True, '4096'):
            with self.subTest(value=value):
                self.assertEqual(self._get(value), config.DEFAULT_MAX_TOKENS)


class PromptMaxCharsTest(unittest.TestCase):

    def _get(self, display):
        with patch.object(config, 'load_config', return_value=_config(display)):
            return config.get_prompt_max_chars()

    def test_the_configured_number_is_used(self):
        self.assertEqual(self._get({'promptMaxChars': 4096}), 4096)

    def test_zero_means_uncapped(self):
        self.assertEqual(self._get({'promptMaxChars': 0}), 0)

    def test_a_negative_number_is_clamped_to_uncapped(self):
        self.assertEqual(self._get({'promptMaxChars': -5}), 0)

    def test_a_missing_key_falls_back_to_the_baked_in_default(self):
        # create_user_config() only writes ~/.clay/config.json when it is
        # missing, so an existing file never gains the key. Treating absent as
        # uncapped would mean the setting did nothing on every existing install.
        self.assertEqual(self._get(None), config.DEFAULT_PROMPT_MAX_CHARS)
        self.assertEqual(self._get({}), config.DEFAULT_PROMPT_MAX_CHARS)

    def test_true_is_not_a_one_character_cap(self):
        # bool is a subclass of int.
        self.assertEqual(self._get({'promptMaxChars': True}),
                         config.DEFAULT_PROMPT_MAX_CHARS)

    def test_a_string_is_rejected(self):
        self.assertEqual(self._get({'promptMaxChars': '200'}),
                         config.DEFAULT_PROMPT_MAX_CHARS)


class PayloadMaxCharsTest(unittest.TestCase):

    def _get(self, display, action_type):
        with patch.object(config, 'load_config', return_value=_config(display)):
            return config.get_payload_max_chars(action_type)

    def test_the_configured_number_is_used(self):
        table = {'payloadMaxChars': {'writeMemory': 640}}
        self.assertEqual(self._get(table, 'writeMemory'), 640)

    def test_each_action_carries_its_own_number(self):
        table = {'payloadMaxChars': {'writeMemory': 100,
                                     'serveFileReads': 9000}}
        self.assertEqual(self._get(table, 'writeMemory'), 100)
        self.assertEqual(self._get(table, 'serveFileReads'), 9000)

    def test_an_action_absent_from_the_table_is_uncapped(self):
        # The scope decision: only the listed actions are cut. An action that
        # is not named is drawn whole, which is what every action did before.
        table = {'payloadMaxChars': {'writeMemory': 100}}
        self.assertEqual(self._get(table, 'applyFileWrites'), 0)
        self.assertEqual(self._get(table, 'scramda2'), 0)

    def test_zero_means_uncapped(self):
        self.assertEqual(self._get({'payloadMaxChars': {'writeMemory': 0}},
                                   'writeMemory'), 0)

    def test_a_negative_number_is_clamped_to_uncapped(self):
        self.assertEqual(self._get({'payloadMaxChars': {'writeMemory': -5}},
                                   'writeMemory'), 0)

    def test_a_missing_table_falls_back_to_the_baked_in_caps(self):
        for display in (None, {}):
            with self.subTest(display=display):
                self.assertEqual(
                    self._get(display, 'writeMemory'),
                    config.DEFAULT_PAYLOAD_MAX_CHARS['writeMemory'])

    def test_a_missing_table_still_leaves_unlisted_actions_whole(self):
        self.assertEqual(self._get(None, 'applyFileWrites'), 0)

    def test_a_table_that_is_not_an_object_falls_back(self):
        self.assertEqual(self._get({'payloadMaxChars': 800}, 'writeMemory'),
                         config.DEFAULT_PAYLOAD_MAX_CHARS['writeMemory'])

    def test_true_is_not_a_one_character_cap(self):
        # bool is a subclass of int. Drawn whole rather than cut to one
        # character, and said out loud once — never silently.
        config._payload_max_bad_values.discard('writeMemory')
        self.assertEqual(self._get({'payloadMaxChars': {'writeMemory': True}},
                                   'writeMemory'), 0)

    def test_a_string_is_rejected(self):
        config._payload_max_bad_values.discard('writeSkill')
        self.assertEqual(self._get({'payloadMaxChars': {'writeSkill': '800'}},
                                   'writeSkill'), 0)


if __name__ == '__main__':
    unittest.main()
