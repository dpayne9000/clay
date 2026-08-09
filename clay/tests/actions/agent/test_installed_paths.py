import unittest

from ....actions.agent import alert_actions, email_actions, memory_actions, web_actions
from ....lib import config


class InstalledPathTest(unittest.TestCase):
    def test_memory_and_saved_sites_use_clay_home(self):
        self.assertEqual(config.user_path("memory"), memory_actions.MEMORY_BASE)
        self.assertEqual(config.user_path("webactions"), web_actions.WEBACTIONS_BASE)

    def test_email_and_alert_defaults_use_application_resources(self):
        self.assertEqual(
            config.resource("configs", "email.json"), email_actions.CONFIG_PATH
        )
        self.assertEqual(
            config.resource("configs", "alerts.json"), alert_actions.CONFIG_PATH
        )


if __name__ == "__main__":
    unittest.main()
