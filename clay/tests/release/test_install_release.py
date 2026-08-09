import unittest

from scripts.build.install_release import install_requirement


class InstallReleaseTest(unittest.TestCase):
    def test_core_archive_installs_base_distribution(self):
        self.assertEqual("clay", install_requirement({"flavor": "core"}))

    def test_ui_archive_installs_ui_extra(self):
        self.assertEqual("clay[ui]", install_requirement({"flavor": "ui"}))

    def test_unknown_archive_flavor_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported release flavor"):
            install_requirement({"flavor": "unknown"})


if __name__ == "__main__":
    unittest.main()
