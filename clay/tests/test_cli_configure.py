"""Interactive configuration command behavior."""

import unittest
from unittest.mock import patch

from clay import cli


class ConfigureMaxTokensTest(unittest.TestCase):

    @patch('clay.lib.config_check.configuration_problem', return_value='offline')
    @patch('clay.lib.config.write_user_config')
    @patch('clay.lib.config.load_config', return_value={
        'provider': {'url': 'http://localhost:8080'},
        'models': {'default': 'owner/model:Q4'},
        'maxTokens': 2048,
    })
    def test_configure_persists_max_tokens(
            self, load_config, write_config, configuration_problem):
        answers = iter(['', '', '8192', 'n'])
        with patch('builtins.input', side_effect=lambda _prompt='': next(answers)):
            cli.configure_cmd(None)

        saved = write_config.call_args.args[0]
        self.assertEqual(saved['maxTokens'], 8192)
        self.assertEqual(saved['provider']['url'], 'http://localhost:8080')
        self.assertEqual(saved['models']['default'], 'owner/model:Q4')

    @patch('clay.lib.config_check.configuration_problem', return_value='offline')
    @patch('clay.lib.config.write_user_config')
    @patch('clay.lib.config.load_config', return_value={
        'provider': {'url': 'http://localhost:8080'},
        'models': {'default': 'owner/model:Q4'},
        'maxTokens': 2048,
    })
    def test_configure_reprompts_for_invalid_max_tokens(
            self, load_config, write_config, configuration_problem):
        answers = iter(['', '', 'invalid', '0', '4096', 'n'])
        with patch('builtins.input', side_effect=lambda _prompt='': next(answers)):
            cli.configure_cmd(None)

        self.assertEqual(write_config.call_args.args[0]['maxTokens'], 4096)


if __name__ == '__main__':
    unittest.main()
