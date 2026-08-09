import unittest

from web import build


class ReleaseIndexTest(unittest.TestCase):
    def test_version_key_orders_numeric_versions_numerically(self):
        versions = ["0.9.0", "0.10.0", "0.2.1"]
        self.assertEqual(
            ["0.2.1", "0.9.0", "0.10.0"],
            sorted(versions, key=build._version_key),
        )

    def test_release_page_links_every_artifact(self):
        page = build._release_page([{
            "version": "1.2.3", "stable": True,
            "artifacts": [{
                "file": "clay.tar.gz", "system": "linux",
                "architecture": "x86_64", "flavor": "core",
                "size": 1024, "sha256": "a" * 64,
            }],
        }])
        self.assertIn("1.2.3/clay.tar.gz", page)
        self.assertIn("linux / x86_64 / core", page)
        self.assertIn("clay — releases", page)

    def test_root_release_page_prefixes_artifacts_with_release_directory(self):
        page = build._release_page([{
            "version": "1.2.3", "stable": True,
            "artifacts": [{
                "file": "clay.tar.gz", "system": "linux",
                "architecture": "x86_64", "flavor": "core",
                "size": 1024, "sha256": "a" * 64,
            }],
        }], artifact_prefix="releases/", home_url="index.html",
           releases_url="releases.html")
        self.assertIn('href="releases/1.2.3/clay.tar.gz"', page)
        self.assertIn('href="index.html"', page)


if __name__ == "__main__":
    unittest.main()
