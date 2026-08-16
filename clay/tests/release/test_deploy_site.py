import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.deploy import site


class _FakeAws:
    def __init__(self, remote=None):
        self.remote = remote or {}

    def call(self, *args, allow_failure=False):
        key = args[args.index("--key") + 1]
        value = self.remote.get(key)
        if value is None:
            return None
        return {"Metadata": {"sha256": value}}


class _MissingMetadataAws:
    def call(self, *args, allow_failure=False):
        return {"Metadata": {}}


class DeploymentPlanTest(unittest.TestCase):
    def _write_web_index(self, root, artifacts):
        releases = root / "releases"
        releases.mkdir(parents=True, exist_ok=True)
        (releases / "releases.json").write_text(json.dumps({
            "formatVersion": 1,
            "releases": [{
                "version": "1.0",
                "source": None,
                "artifacts": [{"file": name} for name in artifacts],
            }],
        }), encoding="utf-8")

    def test_existing_different_immutable_object_is_refused(self):
        # TODO(F-50): _deployment_plan() takes no bucket argument, so
        # nothing here checks the entry's key actually belongs to the
        # intended bucket. Add bucket-name validation to _deployment_plan()
        # (or its caller) and cover it here.
        entry = {"key": "releases/1.0/clay.tar.gz", "sha256": "new",
                 "mutable": False}
        with self.assertRaises(site.DeployError):
            site._deployment_plan(
                _FakeAws({entry["key"]: "old"}), [entry]
            )

    def test_existing_different_mutable_object_is_replaced(self):
        # TODO(F-50): see note above — no bucket-name check exercised here.
        entry = {"key": "index.html", "sha256": "new", "mutable": True}
        changes = site._deployment_plan(
            _FakeAws({entry["key"]: "old"}), [entry]
        )
        self.assertEqual("replace", changes[0]["operation"])

    def test_existing_immutable_object_without_hash_is_refused(self):
        # TODO(F-50): see note above — no bucket-name check exercised here.
        entry = {"key": "releases/1.0/clay.tar.gz", "sha256": "new",
                 "mutable": False}
        with self.assertRaises(site.DeployError):
            site._deployment_plan(
                _MissingMetadataAws(), [entry]
            )

    def test_entries_classify_release_binary_as_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "releases" / "1.0").mkdir(parents=True)
            (root / "index.html").write_text("site", encoding="utf-8")
            (root / "releases" / "1.0" / "clay.tar.gz").write_bytes(b"archive")
            (root / "releases" / "1.0" / "release.json").write_text("{}")
            (root / "releases" / "1.0" / "SHA256SUMS").write_text("")
            self._write_web_index(root, ["clay.tar.gz"])
            with patch.object(site, "WEB_ROOT", root):
                entries = {entry["key"]: entry for entry in site._entries()}
        self.assertTrue(entries["index.html"]["mutable"])
        self.assertFalse(entries["releases/1.0/clay.tar.gz"]["mutable"])

    def test_entries_reject_an_unadmitted_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_web_index(root, [])
            (root / "surprise.txt").write_text("not released", encoding="utf-8")
            with patch.object(site, "WEB_ROOT", root):
                with self.assertRaisesRegex(site.DeployError, "unadmitted"):
                    site._entries()


if __name__ == "__main__":
    unittest.main()
