import unittest
from pathlib import Path

from scripts.build.install_release import install_requirement, launcher_script


class InstallReleaseTest(unittest.TestCase):
    def test_core_archive_installs_base_distribution(self):
        self.assertEqual("clay", install_requirement({"flavor": "core"}))

    def test_ui_archive_installs_ui_extra(self):
        self.assertEqual("clay[ui]", install_requirement({"flavor": "ui"}))

    def test_unknown_archive_flavor_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported release flavor"):
            install_requirement({"flavor": "unknown"})


class LauncherScriptTest(unittest.TestCase):
    RELEASE = Path("/home/u/.local/share/clay/releases/clay-0.1.0-macos-arm64-core")

    def test_launcher_runs_the_recorded_absolute_console_script(self):
        console = self.RELEASE / "venv" / "bin" / "clay"
        self.assertEqual(
            '#!/bin/sh\nexec "%s" "$@"\n' % console,
            launcher_script(console),
        )

    def test_launcher_does_not_derive_its_target_from_the_invoked_path(self):
        # $0 is the ~/.local/bin/clay symlink, not the release file, so a
        # target derived from it resolves to ~/.local/bin/venv/bin/clay.
        script = launcher_script(self.RELEASE / "venv" / "bin" / "clay")
        self.assertNotIn("$0", script)
        self.assertNotIn("dirname", script)

    def test_relative_launcher_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be absolute"):
            launcher_script(Path("venv/bin/clay"))

    def test_unquotable_launcher_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not safely quotable"):
            launcher_script(Path('/opt/clay "release"/venv/bin/clay'))


if __name__ == "__main__":
    unittest.main()
