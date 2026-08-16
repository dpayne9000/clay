"""Visible workspace authorization before the Qt client starts clayd."""

from PySide6.QtWidgets import QMessageBox

from ..daemon.client import (
    DaemonPermissionDenied,
    authorize_daemon_workspace,
    ensure_daemon,
)
from ..lib import paths
from ..run import approval, workspaces


_LABELS = {
    'fileReads': 'read files',
    'fileWrites': 'write files',
    'commands': 'run commands',
}


def _confirm(check, parent=None) -> bool:
    missing = ', '.join(_LABELS[gate] for gate in approval.GATES
                        if gate in check.missing)
    text = (
        'CLAY needs advance permission for an unattended daemon workflow.\n\n'
        f'Directory: {check.path}\n'
        f'Missing: {missing}\n\n'
        f'Grant these permissions for {check.path} in '
        f'{workspaces.REGISTER_PATH}?'
    )
    answer = QMessageBox.question(
        parent,
        'Daemon workspace permissions',
        text,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    return answer == QMessageBox.Yes


def ensure_daemon_with_qt(parent=None) -> bool:
    """Prompt through Qt, persist and verify, then start clayd."""
    try:
        authorize_daemon_workspace(
            paths.project_dir(), lambda check: _confirm(check, parent))
    except DaemonPermissionDenied:
        return False
    return ensure_daemon()
