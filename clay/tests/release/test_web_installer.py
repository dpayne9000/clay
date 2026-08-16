"""User-visible installation and launcher-path contract."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / 'web' / 'install.sh'
README = ROOT / 'README.md'
INSTALL_DOC = ROOT / 'docs' / 'INSTALL.md'


class WebInstallerPathTest(unittest.TestCase):

    def setUp(self):
        self.script = INSTALLER.read_text(encoding='utf-8')

    def test_default_program_and_launcher_directories_are_explicit(self):
        self.assertIn('$HOME/.local/share/clay', self.script)
        self.assertIn('$HOME/.local/bin', self.script)

    def test_installer_detects_when_launcher_directory_is_not_on_path(self):
        self.assertIn('case ":${PATH:-}:" in', self.script)
        self.assertIn('"$BIN_DIR is not on PATH"', self.script)
        self.assertIn('export PATH=\\"$BIN_DIR:\\$PATH\\"', self.script)

    def test_installer_prints_a_version_verification_command(self):
        self.assertIn('Verify: clay --version', self.script)
        self.assertIn('Then verify: clay --version', self.script)


class WebInstallerOrderingTest(unittest.TestCase):
    """The venv and the launcher record absolute paths at creation time."""

    def setUp(self):
        self.script = INSTALLER.read_text(encoding='utf-8')

    def test_release_reaches_its_final_directory_before_it_is_installed(self):
        moved = self.script.index('mv "$INSTALLING" "$DESTINATION"')
        installed = self.script.index('"$DESTINATION/install.py"')
        self.assertLess(moved, installed)

    def test_a_failed_installation_removes_the_destination(self):
        self.assertIn('INCOMPLETE=$DESTINATION', self.script)
        self.assertIn('rm -rf "$INCOMPLETE"', self.script)

    def test_the_selected_release_is_published_by_moving_the_symlink(self):
        installed = self.script.index('"$DESTINATION/install.py"')
        selected = self.script.index('"$INSTALL_ROOT/current.next"')
        self.assertLess(installed, selected)

    def test_release_installation_runs_config_migrations(self):
        installer = (ROOT / 'scripts' / 'build' / 'install_release.py').read_text(
            encoding='utf-8')
        self.assertIn('create_user_config; create_user_config()', installer)


class InstallDocumentationPathTest(unittest.TestCase):

    def test_readme_verifies_path_immediately_after_install(self):
        readme = README.read_text(encoding='utf-8')
        install = readme.index('## Install')
        configure = readme.index('## Model server')
        section = readme[install:configure]
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', section)
        self.assertIn('clay --version', section)

    def test_install_doc_contains_persistent_and_repair_instructions(self):
        document = INSTALL_DOC.read_text(encoding='utf-8')
        self.assertIn('~/.zshrc', document)
        self.assertIn('~/.bashrc', document)
        self.assertIn('ln -sfn "$HOME/.local/share/clay/current/clay"',
                      document)
        self.assertIn('CLAY_INSTALL_ROOT', document)
        self.assertIn('CLAY_BIN_DIR', document)


if __name__ == '__main__':
    unittest.main()
