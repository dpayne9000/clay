import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from clay import cli


class DisabledCloudCommandsTest(unittest.TestCase):
    def test_obsolete_cloud_commands_are_not_registered(self):
        for command in ("login", "logout", "whoami", "push", "pull"):
            with self.subTest(command=command):
                stderr = io.StringIO()
                with patch.object(sys, "argv", ["clay", command]), \
                        contextlib.redirect_stderr(stderr), \
                        self.assertRaises(SystemExit) as raised:
                    cli.cli()
                self.assertEqual(2, raised.exception.code)
                self.assertIn("invalid choice", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
