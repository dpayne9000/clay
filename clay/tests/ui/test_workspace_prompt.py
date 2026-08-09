import os
import unittest
from unittest.mock import MagicMock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtWidgets import QApplication

    from clay.run import workspaces
    from clay.ui.dashboard import AgentCard
    from clay.ui.manager import DaemonTerminal
    from clay.ui.panels import LogPanel
except ModuleNotFoundError:
    QApplication = None
    AgentCard = None
    DaemonTerminal = None
    LogPanel = None


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class WorkspacePromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.panel = LogPanel()
        self.answers = []
        self.panel.input_submitted.connect(
            lambda prompt_id, text: self.answers.append((prompt_id, text))
        )

    def tearDown(self):
        self.panel.close()

    def test_workspace_prompt_uses_buttons_instead_of_text_entry(self):
        self.panel._ask({
            "id": workspaces.PROMPT_ID,
            "prompt": "Approve this directory?",
        })

        self.assertFalse(self.panel._workspace_prompt_row.isHidden())
        self.assertTrue(self.panel._prompt_row.isHidden())

    def test_workspace_buttons_submit_existing_engine_answers(self):
        choices = (
            ("_workspace_approve", "y"),
            ("_workspace_once", "o"),
            ("_workspace_refuse", "n"),
        )
        for button_name, answer in choices:
            with self.subTest(button=button_name):
                self.panel._ask({
                    "id": workspaces.PROMPT_ID,
                    "prompt": "Approve this directory?",
                })
                getattr(self.panel, button_name).click()
                self.assertEqual(
                    (workspaces.PROMPT_ID, answer), self.answers[-1]
                )
                self.assertTrue(self.panel._workspace_prompt_row.isHidden())

    def test_other_prompts_keep_the_text_entry(self):
        self.panel._ask({"id": "question", "prompt": "What value?"})

        self.assertFalse(self.panel._prompt_row.isHidden())
        self.assertTrue(self.panel._workspace_prompt_row.isHidden())


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class DaemonWorkspacePromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_daemon_terminal_uses_workspace_buttons_and_submits_once(self):
        terminal = DaemonTerminal("wf-1")
        answers = []
        terminal.input_submitted.connect(
            lambda wf_id, text: answers.append((wf_id, text))
        )

        terminal.show_prompt("Approve?", workspaces.PROMPT_ID)
        self.assertFalse(terminal._workspace_bar.isHidden())
        self.assertTrue(terminal._input_bar.isHidden())
        terminal._workspace_once.click()

        self.assertEqual([("wf-1", "o")], answers)
        self.assertTrue(terminal._workspace_bar.isHidden())
        terminal.close()

    def test_dashboard_card_uses_workspace_buttons_and_submits_once(self):
        card = AgentCard("wf-2", "Workflow", MagicMock())
        answers = []
        card.input_submitted.connect(
            lambda wf_id, text: answers.append((wf_id, text))
        )

        card.show_prompt("Approve?", workspaces.PROMPT_ID)
        self.assertFalse(card._workspace_bar.isHidden())
        self.assertTrue(card._input_bar.isHidden())
        card._workspace_refuse.click()

        self.assertEqual([("wf-2", "n")], answers)
        self.assertTrue(card._workspace_bar.isHidden())
        card.close()


if __name__ == "__main__":
    unittest.main()
