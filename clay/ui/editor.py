"""JSON editor with syntax highlighting and live validation."""
import json
from PySide6.QtWidgets import QPlainTextEdit, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal, QTimer, QRegularExpression
from PySide6.QtGui import (
    QFont, QColor, QSyntaxHighlighter, QTextCharFormat,
)


class _JsonHighlighter(QSyntaxHighlighter):
    """Minimal JSON syntax highlighter."""

    def __init__(self, parent):
        super().__init__(parent)
        self._rules = []

        # Strings
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#2ecc71'))
        self._rules.append((QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'), fmt))

        # Numbers
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#f39c12'))
        self._rules.append((QRegularExpression(r'\b-?\d+\.?\d*\b'), fmt))

        # Keywords
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#e74c3c'))
        self._rules.append((QRegularExpression(r'\b(true|false|null)\b'), fmt))

        # Keys (string followed by colon)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#4a7fa5'))
        fmt.setFontWeight(QFont.Bold)
        self._rules.append((QRegularExpression(r'"[^"]*"\s*(?=:)'), fmt))

        # Braces
        fmt = QTextCharFormat()
        fmt.setForeground(QColor('#8ab4cc'))
        self._rules.append((QRegularExpression(r'[\{\}\[\]]'), fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)


class JsonEditor(QWidget):
    """JSON editor widget with syntax highlighting and a validation status bar."""

    text_changed = Signal()
    valid_json = Signal(dict)    # emits parsed JSON when valid

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
            QWidget { background: #0a1018; }
            QPlainTextEdit {
                background: #0a1018; color: #8ab4cc; border: none;
                selection-background-color: #1e3a52;
            }
            QLabel { color: #4a7fa5; padding: 2px 6px; font-size: 10px; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._editor = QPlainTextEdit()
        self._editor.setFont(QFont('Menlo', 10))
        self._editor.setTabStopDistance(20)
        self._editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self._editor)

        self._status = QLabel('')
        self._status.setStyleSheet('background: #0e1825; color: #4a7fa5; font-family: Menlo;')
        layout.addWidget(self._status)

        self._highlighter = _JsonHighlighter(self._editor.document())

        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(400)
        self._validate_timer.timeout.connect(self._validate)

        self._editor.textChanged.connect(self._on_text_changed)

    def set_json(self, data):
        text = json.dumps(data, indent=4)
        self._editor.setPlainText(text)

    def get_json(self):
        try:
            return json.loads(self._editor.toPlainText())
        except Exception:
            return None

    def get_text(self):
        return self._editor.toPlainText()

    def set_text(self, text):
        self._editor.setPlainText(text)

    def _on_text_changed(self):
        self._validate_timer.start()
        self.text_changed.emit()

    def _validate(self):
        text = self._editor.toPlainText()
        if not text.strip():
            self._status.setText('')
            self._status.setStyleSheet('background: #0e1825; color: #4a7fa5; font-family: Menlo;')
            return
        try:
            data = json.loads(text)
            self._status.setText('✓  valid JSON')
            self._status.setStyleSheet('background: #0e1825; color: #2ecc71; font-family: Menlo;')
            self.valid_json.emit(data)
        except json.JSONDecodeError as e:
            self._status.setText(f'✕  {e}')
            self._status.setStyleSheet('background: #0e1825; color: #e74c3c; font-family: Menlo;')
