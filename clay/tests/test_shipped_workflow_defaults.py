"""Regression tests for the shipped default workflow and Telegram menu."""

import json
import unittest

from clay.lib import config


def _data(*parts):
    with open(config.data_path(*parts), encoding='utf-8') as source:
        return json.load(source)


class ShippedWorkflowDefaultsTest(unittest.TestCase):

    def test_bare_clay_defaults_to_general_chat(self):
        startup = _data('configs', 'startup.json')
        self.assertEqual(['workflows/system/chat/main.json'], startup['user'])

    def test_telegram_menu_contains_the_selected_five(self):
        telegram = _data('workflows', 'system', 'messaging', 'telegram.json')
        menu = telegram['actionSets']['boot'][0]['workflows']
        self.assertEqual([
            ('General chat', 'workflows/system/chat/main.json'),
            ('Coding', 'workflows/system/coding/main.json'),
            ('Build a workflow',
             'workflows/system/process_builder/main.json'),
            ('Code review',
             'workflows/templates/agents/code-review/main.json'),
            ('Web research',
             'workflows/templates/agents/web-researcher/main.json'),
        ], [(item['label'], item['path']) for item in menu])


if __name__ == '__main__':
    unittest.main()
