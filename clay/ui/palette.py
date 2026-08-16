"""Provide action types that users can drag onto the canvas."""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit,
)
from PySide6.QtCore import Qt, QMimeData, QByteArray
from PySide6.QtGui import QDrag, QFont, QColor


_ACTION_TYPES = [
    ('Flow',       ['workflow', 'loop', 'humanDecision', 'humanShell']),
    ('AI / Data',  ['scramda2', 'transformData', 'deriveTags']),
    ('Code',       ['python', 'runCode', 'shell']),
    ('I/O',        ['API', 'writeFile', 'writeCode', 'loadContext']),
    ('Memory',     ['writeMemory', 'searchMemory', 'listMemory', 'readMemory']),
    ('Skills',     ['writeSkill', 'listSkills', 'removeSkill', 'searchSkills']),
    ('Web',        ['browseWeb', 'searchWeb', 'listSites', 'loadSite']),
    ('System',     ['report', 'mongo', 'createAgentAction']),
]


class PalettePanel(QWidget):
    """Display draggable action types grouped by category."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget { background: #0d1520; color: #8ab4cc; font-family: Menlo; font-size: 11px; }
            QListWidget { background: #0a1018; border: 1px solid #1e2a3a; }
            QListWidget::item { padding: 3px 8px; }
            QListWidget::item:hover { background: #1e2a3a; }
            QListWidget::item:selected { background: #1e3a52; }
            QLineEdit {
                background: #0a1018; color: #8ab4cc; border: 1px solid #1e2a3a;
                padding: 4px 8px; border-radius: 3px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel('Action Palette')
        title.setFont(QFont('Menlo', 11, QFont.Bold))
        title.setStyleSheet('color: #aed6f1;')
        layout.addWidget(title)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText('Filter actions…')
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._list = _DragList()
        self._populate()
        layout.addWidget(self._list)

    def _populate(self):
        self._list.clear()
        for group, types in _ACTION_TYPES:
            header = QListWidgetItem(f'── {group} ──')
            header.setFlags(Qt.NoItemFlags)
            header.setForeground(QColor('#4a7fa5'))
            font = QFont('Menlo', 9, QFont.Bold)
            header.setFont(font)
            self._list.addItem(header)
            for t in types:
                item = QListWidgetItem(f'  {t}')
                item.setData(Qt.UserRole, t)
                self._list.addItem(item)

    def _apply_filter(self, text):
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            data = item.data(Qt.UserRole)
            if data is None:
                # Show a group header when any child matches the filter.
                item.setHidden(bool(text))
            else:
                item.setHidden(text not in data.lower())


class _DragList(QListWidget):
    """Start a MIME-data drag when the user moves a list item."""

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return
        action_type = item.data(Qt.UserRole)
        if not action_type:
            return
        mime = QMimeData()
        mime.setData('application/x-clay-action', QByteArray(action_type.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)
