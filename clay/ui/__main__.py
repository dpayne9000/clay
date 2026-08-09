"""Entry point: python -m clay.ui [workflow.json ...]"""
import sys
import os
from PySide6.QtWidgets import QApplication
from .window import WorkflowWindow


def main():
    from ..cli import _ensure_daemon
    _ensure_daemon()

    app = QApplication(sys.argv)
    app.setApplicationName('clay')
    app.setOrganizationName('clay')

    win = WorkflowWindow()
    win.show()

    # Open any files passed as arguments
    for arg in sys.argv[1:]:
        if os.path.exists(arg) and arg.endswith('.json'):
            win.load_workflow(arg)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
