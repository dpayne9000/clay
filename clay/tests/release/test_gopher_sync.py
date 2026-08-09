from pathlib import Path
import tempfile
import unittest

from scripts.build.sync_gopher import runtime_files, synchronize


class GopherSynchronizationTest(unittest.TestCase):
    def test_recursive_runtime_tree_is_mirrored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            (source / "nested").mkdir(parents=True)
            (source / "__init__.py").write_text("package\n")
            (source / "nested" / "client.py").write_text("client\n")

            count = synchronize(source, destination)

            self.assertEqual(2, count)
            self.assertEqual("client\n", (
                destination / "nested" / "client.py"
            ).read_text())

    def test_obsolete_vendor_file_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "__init__.py").write_text("")
            (destination / "__init__.py").write_text("")
            obsolete = destination / "obsolete.py"
            obsolete.write_text("old\n")

            synchronize(source, destination)

            self.assertFalse(obsolete.exists())

    def test_python_caches_are_not_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "__pycache__").mkdir()
            (root / "__init__.py").write_text("")
            (root / "__pycache__" / "chat.pyc").write_bytes(b"cache")

            self.assertEqual(["__init__.py"], list(runtime_files(root)))


if __name__ == "__main__":
    unittest.main()
