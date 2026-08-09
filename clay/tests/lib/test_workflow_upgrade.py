import tempfile
import unittest
from pathlib import Path

from clay.lib import workflow_upgrade


class WorkflowUpgradeTest(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.shipped = self.root / 'shipped'
        self.installed = self.root / 'installed'

    def write(self, root, relative, content):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_groups_main_workflow_and_keeps_standalone_json_separate(self):
        self.write(self.shipped, 'agents/coder/main.json', '{}')
        self.write(self.shipped, 'agents/coder/training.json', '{}')
        self.write(self.shipped, 'content/summary.json', '{}')

        candidates = workflow_upgrade.upgrades(self.shipped, self.installed)

        self.assertEqual(
            [candidate.name for candidate in candidates],
            ['agents/coder', 'content/summary.json'])

    def test_diff_covers_modified_added_and_removed_files(self):
        self.write(self.shipped, 'coder/main.json', 'shipped\n')
        self.write(self.shipped, 'coder/new.json', 'new\n')
        self.write(self.installed, 'coder/main.json', 'local\n')
        self.write(self.installed, 'coder/old.json', 'old\n')
        candidate = workflow_upgrade.WorkflowUpgrade(
            'coder', self.shipped / 'coder', self.installed / 'coder')

        rendered = candidate.diff()

        self.assertIn('=== modified: main.json ===', rendered)
        self.assertIn('=== added: new.json ===', rendered)
        self.assertIn('=== removed: old.json ===', rendered)
        self.assertIn('-local', rendered)
        self.assertIn('+shipped', rendered)
        self.assertIn('shipped/new.json', rendered)
        self.assertIn('installed/old.json', rendered)

    def test_install_backs_up_and_replaces_the_complete_workflow(self):
        self.write(self.shipped, 'coder/main.json', 'shipped')
        self.write(self.shipped, 'coder/new.json', 'new')
        self.write(self.installed, 'coder/main.json', 'local')
        self.write(self.installed, 'coder/local-only.json', 'local')
        candidate = workflow_upgrade.WorkflowUpgrade(
            'coder', self.shipped / 'coder', self.installed / 'coder')
        backup = self.root / 'backups'

        saved = workflow_upgrade.install(candidate, backup)

        self.assertEqual((self.installed / 'coder/main.json').read_text(), 'shipped')
        self.assertTrue((self.installed / 'coder/new.json').is_file())
        self.assertFalse((self.installed / 'coder/local-only.json').exists())
        self.assertEqual((saved / 'main.json').read_text(), 'local')
        self.assertTrue((saved / 'local-only.json').is_file())


if __name__ == '__main__':
    unittest.main()
