import io
import json
from pathlib import Path
import tarfile
import tempfile
import tomllib
import unittest
from unittest.mock import patch
import zipfile

from scripts.build import release


class ReleaseConfigurationTest(unittest.TestCase):
    def test_setup_specifies_exact_runtime_packages(self):
        project = tomllib.loads((release.ROOT / "pyproject.toml").read_text())
        packages = project["tool"]["setuptools"]["packages"]
        self.assertEqual(
            [
                "clay", "clay.actions", "clay.actions.agent",
                "clay.actions.core", "clay.adapters", "clay.auth",
                "clay.channels", "clay.daemon", "clay.lib", "clay.run",
                "clay.run.renderers", "clay.run.termui", "clay.ui",
                "clay.vendor", "clay.vendor.gopher",
            ],
            packages,
        )
        self.assertFalse(any(name.startswith("clay.tests") for name in packages))
        self.assertEqual(
            {name.replace(".", "/") for name in packages},
            release.WHEEL_PYTHON_PACKAGES,
        )

    def test_package_data_specifies_only_production_trees(self):
        project = tomllib.loads((release.ROOT / "pyproject.toml").read_text())
        setuptools_config = project["tool"]["setuptools"]
        self.assertFalse(setuptools_config["include-package-data"])
        package_data = setuptools_config["package-data"]["clay"]
        joined = "\n".join(package_data)
        self.assertNotIn("data/**/*", package_data)
        self.assertNotIn("workflows/dev", joined)
        self.assertNotIn("workflows/test", joined)
        self.assertNotIn("tests/", joined)
        for required in (
            "data/configs/default.json",
            "data/skills/system-editor/*",
            "data/workflows/system/**/*.json",
            "data/workflows/templates/**/*.json",
            "run/termui/themes/*.theme",
            "vendor/gopher/LICENSE",
        ):
            self.assertIn(required, package_data)

    def test_source_paths_specify_runtime_code_and_production_data(self):
        paths = set(release.SOURCE_ARCHIVE_PATHS)
        for module in (
            "clay/__init__.py", "clay/cli.py", "clay/cloud.py",
            "clay/lint.py", "clay/sync.py",
        ):
            self.assertIn(module, paths)
        self.assertIn("clay/actions", paths)
        self.assertIn("clay/run", paths)
        self.assertIn("clay/data/workflows/system", paths)
        self.assertIn("clay/data/workflows/templates", paths)
        self.assertFalse(any(path.startswith("clay/tests") for path in paths))
        self.assertFalse(any("data/workflows/dev" in path for path in paths))
        self.assertFalse(any("data/workflows/test" in path for path in paths))

    def test_source_allowlist_accepts_production_files_not_development_files(self):
        self.assertTrue(
            release._source_archive_file_is_allowed(
                "clay-0.1.2/clay/data/configs/default.json", "0.1.2"
            )
        )
        self.assertFalse(
            release._source_archive_file_is_allowed(
                "clay-0.1.2/clay/data/workflows/dev/main.json", "0.1.2"
            )
        )

    def test_source_allowlist_explicitly_names_directories(self):
        expected = {
            "clay/actions", "clay/adapters", "clay/auth", "clay/channels",
            "clay/daemon", "clay/lib", "clay/run", "clay/ui", "clay/vendor",
            "clay/data/skills/celeb-tracker", "clay/data/skills/developer",
            "clay/data/skills/network-connection-probe",
            "clay/data/skills/network-explorer", "clay/data/skills/system-editor",
            "clay/data/workflows/system", "clay/data/workflows/templates",
        }
        self.assertEqual(expected, set(release.SOURCE_ARCHIVE_DIRECTORIES))

    def test_all_supported_targets_pin_cpython_311_runtime_hashes(self):
        configuration = json.loads(release.TARGETS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(
            {"macos-arm64", "macos-x86_64", "linux-arm64", "linux-x86_64"},
            set(configuration["targets"]),
        )
        for target in configuration["targets"].values():
            self.assertIn("cpython-3.11.15", target["runtime"]["url"])
            self.assertEqual(64, len(target["runtime"]["sha256"]))

    def test_runtime_extraction_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "runtime.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                info = tarfile.TarInfo("../escape")
                content = b"bad"
                info.size = len(content)
                output.addfile(info, io.BytesIO(content))
            with self.assertRaises(release.BuildError):
                release._validate_runtime_archive(archive)

    def test_component_inventory_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "loop").symlink_to("loop")
            records = release._component_records(root)
        self.assertEqual([{"path": "loop", "link": "loop"}], records)

    def test_wheel_source_staging_does_not_modify_local_build_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dist = root / "dist"
            (root / "build" / "lib" / "obsolete").mkdir(parents=True)
            (root / "clay.egg-info").mkdir()
            (root / "clay.egg-info" / "SOURCES.txt").write_text("obsolete")
            source = root / "clay" / "cli.py"
            source.parent.mkdir()
            source.write_text("source")
            readme = root / "README.md"
            readme.write_text("readme")
            with patch.object(
                release, "SOURCE_ARCHIVE_PATHS", ("README.md", "clay/cli.py")
            ):
                with release._staged_release_source(root, dist) as staged:
                    self.assertEqual("readme", (staged / "README.md").read_text())
                    self.assertEqual("source", (staged / "clay" / "cli.py").read_text())
                    self.assertFalse((staged / "build").exists())
                    self.assertFalse((staged / "clay.egg-info").exists())
                self.assertEqual([], list(dist.glob("tmp-release-*")))
            self.assertTrue((root / "build" / "lib" / "obsolete").is_dir())
            self.assertTrue((root / "clay.egg-info" / "SOURCES.txt").is_file())
            self.assertEqual("source", source.read_text())

    def test_release_wheel_must_contain_clay_and_gopher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendored = root / "vendor"
            (vendored / "nested").mkdir(parents=True)
            (vendored / "__init__.py").write_text("")
            (vendored / "nested" / "client.py").write_text("")
            wheel = root / "clay.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("clay/__init__.py", "")
                archive.writestr("clay/vendor/gopher/__init__.py", "")
            with self.assertRaisesRegex(release.BuildError, "nested/client.py"):
                release._validate_clay_wheel(wheel, vendored)

    def test_release_wheel_accepts_clay_and_gopher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendored = root / "vendor"
            vendored.mkdir(parents=True)
            (vendored / "__init__.py").write_text("")
            (vendored / "client.py").write_text("")
            wheel = root / "clay.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("clay/__init__.py", "")
                archive.writestr("clay/vendor/gopher/__init__.py", "")
                archive.writestr("clay/vendor/gopher/client.py", "")
            release._validate_clay_wheel(wheel, vendored)

    def test_release_wheel_rejects_paths_outside_install_allowlist(self):
        for unexpected_root in ("api", "api2", "dist", "docs", "scripts", "web"):
            with self.subTest(unexpected_root=unexpected_root):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    vendored = root / "vendor"
                    vendored.mkdir()
                    (vendored / "__init__.py").write_text("")
                    wheel = root / "clay.whl"
                    unexpected = f"{unexpected_root}/not-for-release.txt"
                    with zipfile.ZipFile(wheel, "w") as archive:
                        archive.writestr("clay/__init__.py", "")
                        archive.writestr("clay/vendor/gopher/__init__.py", "")
                        archive.writestr(unexpected, "")
                    with self.assertRaisesRegex(release.BuildError, unexpected):
                        release._validate_clay_wheel(wheel, vendored)

    def test_release_wheel_rejects_clay_tests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendored = root / "vendor"
            vendored.mkdir()
            (vendored / "__init__.py").write_text("")
            wheel = root / "clay.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("clay/__init__.py", "")
                archive.writestr("clay/vendor/gopher/__init__.py", "")
                archive.writestr("clay/tests/test_core.py", "")
            with self.assertRaisesRegex(release.BuildError, "clay/tests/test_core.py"):
                release._validate_clay_wheel(wheel, vendored)

    def test_release_wheel_rejects_development_workflow_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendored = root / "vendor"
            vendored.mkdir()
            (vendored / "__init__.py").write_text("")
            wheel = root / "clay.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("clay/__init__.py", "")
                archive.writestr("clay/vendor/gopher/__init__.py", "")
                archive.writestr("clay/data/workflows/dev/agent/main.json", "{}")
            with self.assertRaisesRegex(release.BuildError, "workflows/dev"):
                release._validate_clay_wheel(wheel, vendored)

    def test_release_rejects_a_stale_gopher_vendor_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "connectors" / "gopher" / "gopher"
            vendored = root / "clay" / "vendor" / "gopher"
            upstream.mkdir(parents=True)
            vendored.mkdir(parents=True)
            for package in (upstream, vendored):
                (package / "__init__.py").write_text("", encoding="utf-8")
            (upstream / "chat.py").write_text("upstream\n", encoding="utf-8")
            (vendored / "chat.py").write_text("stale\n", encoding="utf-8")

            with self.assertRaisesRegex(release.BuildError, "chat.py"):
                release._validate_vendored_gopher(upstream, vendored)

    def test_release_accepts_an_exact_gopher_vendor_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "connectors" / "gopher" / "gopher"
            vendored = root / "clay" / "vendor" / "gopher"
            upstream.mkdir(parents=True)
            vendored.mkdir(parents=True)
            for package in (upstream, vendored):
                (package / "nested").mkdir()
                (package / "__init__.py").write_text("", encoding="utf-8")
                (package / "chat.py").write_text("same\n", encoding="utf-8")
                (package / "nested" / "client.py").write_text(
                    "same nested\n", encoding="utf-8"
                )

            release._validate_vendored_gopher(upstream, vendored)

    def test_source_archive_must_contain_recursive_gopher_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vendored = root / "vendor"
            (vendored / "nested").mkdir(parents=True)
            (vendored / "__init__.py").write_text("")
            (vendored / "nested" / "client.py").write_text("")
            archive_path = root / "source.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                body = b""
                info = tarfile.TarInfo(
                    "clay-1.0/clay/vendor/gopher/__init__.py"
                )
                info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            with self.assertRaisesRegex(release.BuildError, "nested/client.py"):
                release._validate_source_archive(archive_path, "1.0", vendored)

    def test_source_archive_rejects_paths_outside_source_allowlist(self):
        for unexpected_root in ("api", "api2", "dist", "docs", "scripts", "web"):
            with self.subTest(unexpected_root=unexpected_root):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    vendored = root / "vendor"
                    vendored.mkdir()
                    archive_path = root / "source.tar.gz"
                    with tarfile.open(archive_path, "w:gz") as archive:
                        body = b"not for release"
                        member = f"clay-1.0/{unexpected_root}/content.txt"
                        info = tarfile.TarInfo(member)
                        info.size = len(body)
                        archive.addfile(info, io.BytesIO(body))
                    with self.assertRaisesRegex(release.BuildError, member):
                        release._validate_source_archive(archive_path, "1.0", vendored)


if __name__ == "__main__":
    unittest.main()
