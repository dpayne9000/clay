import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.build import contract, release


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseFixture:
    def __init__(self, root, version="1.2.3"):
        self.directory = Path(root) / version
        self.directory.mkdir()
        self.version = version
        self.revision = "a" * 40
        self.artifacts = []
        targets = json.loads(contract.TARGETS_FILE.read_text(encoding="utf-8"))["targets"]
        for target_name, target in targets.items():
            for flavor in ("core", "ui"):
                self.artifacts.append(self._artifact(target_name, target, flavor))
        source = self.directory / f"clay-{version}-source.tar.gz"
        source.write_bytes(b"source")
        self.release = {
            "formatVersion": 1,
            "version": version,
            "sourceRevision": self.revision,
            "stable": False,
            "source": {
                "file": source.name,
                "size": source.stat().st_size,
                "sha256": _sha256(source),
            },
            "artifacts": self.artifacts,
        }
        self.write()

    def _artifact(self, target_name, target, flavor):
        slug = f"clay-{self.version}-{target_name}-{flavor}"
        path = self.directory / f"{slug}.tar.gz"
        manifest = {
            "version": self.version,
            "sourceRevision": self.revision,
            "target": target_name,
            "system": target["system"],
            "architecture": target["architecture"],
            "flavor": flavor,
        }
        body = json.dumps(manifest).encode()
        with tarfile.open(path, "w:gz") as archive:
            info = tarfile.TarInfo(f"{slug}/manifest.json")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
        return {
            **manifest,
            "formatVersion": 1,
            "product": "clay",
            "file": path.name,
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }

    def write(self):
        (self.directory / "release.json").write_text(
            json.dumps(self.release), encoding="utf-8"
        )
        records = [*self.artifacts, self.release["source"]]
        (self.directory / "SHA256SUMS").write_text(
            "".join(f"{item['sha256']}  {item['file']}\n" for item in records),
            encoding="utf-8",
        )
        for path in self.directory.iterdir():
            if path.is_file() and not path.name.endswith(".sig"):
                path.with_name(path.name + ".sig").write_bytes(b"test-signature")


class ReleaseContractTest(unittest.TestCase):
    def test_complete_release_returns_exact_public_files(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(directory)
            _record, files = contract.validate_release(fixture.directory)
        self.assertEqual(22, len(files))
        self.assertIn("release.json", {path.name for path in files})
        self.assertIn("SHA256SUMS", {path.name for path in files})

    def test_checksum_file_must_not_contain_an_extra_file(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(directory)
            with (fixture.directory / "SHA256SUMS").open("a") as stream:
                stream.write(f"{'0' * 64}  surprise.txt\n")
            with self.assertRaisesRegex(contract.ReleaseContractError, "exactly"):
                contract.validate_release(fixture.directory)

    def test_artifact_filename_must_be_a_basename(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(directory)
            fixture.release["artifacts"][0]["file"] = "../outside.tar.gz"
            fixture.write()
            with self.assertRaisesRegex(contract.ReleaseContractError, "basename"):
                contract.validate_release(fixture.directory)

    def test_target_archive_rejects_paths_outside_target_allowlist(self):
        for unexpected_root in ("api", "api2", "dist", "docs", "scripts", "web"):
            with self.subTest(unexpected_root=unexpected_root):
                with tempfile.TemporaryDirectory() as directory:
                    fixture = ReleaseFixture(directory)
                    artifact = fixture.release["artifacts"][0]
                    path = fixture.directory / artifact["file"]
                    root = path.name.removesuffix(".tar.gz")
                    manifest = {
                        field: artifact[field]
                        for field in (
                            "version", "sourceRevision", "target", "system",
                            "architecture", "flavor",
                        )
                    }
                    with tarfile.open(path, "w:gz") as archive:
                        manifest_body = json.dumps(manifest).encode()
                        manifest_info = tarfile.TarInfo(f"{root}/manifest.json")
                        manifest_info.size = len(manifest_body)
                        archive.addfile(manifest_info, io.BytesIO(manifest_body))
                        body = b"not for release"
                        info = tarfile.TarInfo(
                            f"{root}/{unexpected_root}/content.txt"
                        )
                        info.size = len(body)
                        archive.addfile(info, io.BytesIO(body))
                    artifact["size"] = path.stat().st_size
                    artifact["sha256"] = _sha256(path)
                    fixture.write()
                    with self.assertRaisesRegex(
                        contract.ReleaseContractError,
                        f"path outside its allowlist: {unexpected_root}/content.txt",
                    ):
                        contract.validate_release(fixture.directory)

    def test_target_archive_rejects_an_unexpected_file_under_allowed_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(directory)
            artifact = fixture.release["artifacts"][0]
            path = fixture.directory / artifact["file"]
            root = path.name.removesuffix(".tar.gz")
            manifest = {
                field: artifact[field]
                for field in (
                    "version", "sourceRevision", "target", "system",
                    "architecture", "flavor",
                )
            }
            with tarfile.open(path, "w:gz") as archive:
                manifest_body = json.dumps(manifest).encode()
                manifest_info = tarfile.TarInfo(f"{root}/manifest.json")
                manifest_info.size = len(manifest_body)
                archive.addfile(manifest_info, io.BytesIO(manifest_body))
                body = b"unexpected"
                info = tarfile.TarInfo(f"{root}/runtime/unexpected.txt")
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            artifact["size"] = path.stat().st_size
            artifact["sha256"] = _sha256(path)
            fixture.write()
            with self.assertRaisesRegex(
                contract.ReleaseContractError,
                "path outside its allowlist: runtime/unexpected.txt",
            ):
                contract.validate_release(fixture.directory)

    def test_promotion_requires_confirmation_and_marks_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = ReleaseFixture(directory)
            with patch.object(release, "DIST", Path(directory)):
                # promote expects DIST/releases/<version>.
                releases = Path(directory) / "releases"
                releases.mkdir()
                fixture.directory.replace(releases / fixture.version)
                with patch("builtins.input", return_value="y"), \
                     patch.object(release, "private_key", return_value=Path("key")), \
                     patch.object(release, "sign_and_verify") as sign:
                    def fake_sign(path, _key):
                        signature = path.with_name(path.name + ".sig")
                        signature.write_bytes(b"promoted-signature")
                        return signature
                    sign.side_effect = fake_sign
                    release.promote(fixture.version)
                promoted = json.loads(
                    (releases / fixture.version / "release.json").read_text()
                )
        self.assertTrue(promoted["stable"])
        self.assertIn("promotedAt", promoted)


if __name__ == "__main__":
    unittest.main()
