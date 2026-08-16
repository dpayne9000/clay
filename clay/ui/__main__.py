"""Launch the Qt UI through `python -m clay.ui [workflow.json ...]`."""
import sys
import os
from PySide6.QtWidgets import QApplication
from .window import WorkflowWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('clay')
    app.setOrganizationName('clay')

    from .preflight import ensure_daemon_with_qt
    if not ensure_daemon_with_qt():
        return 1

    win = WorkflowWindow()
    win.show()

    # Open workflow files supplied on the command line.
    for arg in sys.argv[1:]:
        if os.path.exists(arg) and arg.endswith('.json'):
            win.load_workflow(arg)

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
