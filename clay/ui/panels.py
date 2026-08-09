"""Side panels: Inspector, Log, MemoryPanel, FileBrowser."""
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QTreeView, QPlainTextEdit,
    QFileSystemModel, QHeaderView, QComboBox, QLineEdit, QFrame,
    QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor

from ..run import approval, events, workspaces
from ..run.renderers.detail import busy_label, payload_lines, skipped_reason
from ..lib import config


def _load_model_profiles():
    """Return model profiles from the same effective config used by the CLI."""
    cfg = config.load_config()
    return list((cfg.get('models') or {}).items())


_STYLE = """
QWidget { background: #0d1520; color: #8ab4cc; font-family: Menlo, monospace; font-size: 11px; }
QPushButton {
    background: #1e2a3a; color: #aed6f1; border: 1px solid #2e4a63;
    padding: 4px 12px; border-radius: 3px;
}
QPushButton:hover { background: #2e4a63; }
QTreeWidget { background: #0a1018; color: #7fb3cc; border: 1px solid #1e2a3a; }
QTreeWidget::item:selected { background: #1e3a52; }
QTreeView { background: #0a1018; color: #7fb3cc; border: 1px solid #1e2a3a; }
QTreeView::item:selected { background: #1e3a52; }
QPlainTextEdit { background: #0a1018; color: #7fb3cc; border: 1px solid #1e2a3a; }
"""


# ── Inspector ─────────────────────────────────────────────────────────────────

class InspectorPanel(QWidget):
    """Shows config, input, output, and timing for a selected node.

    For scramda2 action nodes an additional model/modelProfile editor is shown
    below the property tree so the user can pick from the profiles defined in
    configs/default.json without having to hand-edit the JSON.
    """

    def __init__(self):
        super().__init__()
        self.setStyleSheet(_STYLE)
        self._current_node = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel('Inspector')
        title.setFont(QFont('Menlo', 11, QFont.Bold))
        title.setStyleSheet('color: #aed6f1;')
        layout.addWidget(title)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(['Field', 'Value'])
        self._tree.setColumnWidth(0, 120)
        layout.addWidget(self._tree)

        # ── scramda2 model editor (hidden for non-scramda2 nodes) ────────────
        self._model_section = QFrame()
        self._model_section.setFrameShape(QFrame.StyledPanel)
        self._model_section.setStyleSheet(
            'QFrame { border: 1px solid #2e4a63; border-radius: 3px; background: #0a1018; }'
        )
        ms_layout = QVBoxLayout(self._model_section)
        ms_layout.setContentsMargins(6, 6, 6, 6)
        ms_layout.setSpacing(4)

        sec_title = QLabel('Model  (scramda2)')
        sec_title.setStyleSheet('color: #aed6f1; font-weight: bold; border: none;')
        ms_layout.addWidget(sec_title)

        # Profile row
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel('Profile:'))
        self._profile_combo = QComboBox()
        self._profile_combo.setStyleSheet(
            'QComboBox { background: #141e2b; color: #8ab4cc; border: 1px solid #2e4a63; padding: 2px 6px; }'
            'QComboBox QAbstractItemView { background: #141e2b; color: #8ab4cc; }'
        )
        self._profile_combo.addItem('(none)', None)
        for name, model_id in _load_model_profiles():
            self._profile_combo.addItem(f'{name}  —  {model_id}', name)
        profile_row.addWidget(self._profile_combo)
        ms_layout.addLayout(profile_row)

        # Literal model row
        literal_row = QHBoxLayout()
        literal_row.addWidget(QLabel('Model:'))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText('literal model string (overrides profile)')
        self._model_edit.setStyleSheet(
            'background: #141e2b; color: #8ab4cc; border: 1px solid #2e4a63; padding: 2px 6px;'
        )
        literal_row.addWidget(self._model_edit)
        ms_layout.addLayout(literal_row)

        apply_btn = QPushButton('Apply')
        apply_btn.setMaximumWidth(80)
        apply_btn.clicked.connect(self._apply_model)
        ms_layout.addWidget(apply_btn)

        layout.addWidget(self._model_section)
        self._model_section.setVisible(False)

    def show_node(self, node):
        self._current_node = node
        self._tree.clear()
        meta = getattr(node, 'meta', {})

        def _add(parent, key, value):
            if isinstance(value, dict):
                item = QTreeWidgetItem(parent, [str(key), ''])
                for k, v in value.items():
                    _add(item, k, v)
                item.setExpanded(True)
            elif isinstance(value, list):
                item = QTreeWidgetItem(parent, [str(key), f'[{len(value)} items]'])
                for i, v in enumerate(value):
                    _add(item, str(i), v)
            else:
                s = str(value)
                display = s[:300] + ('…' if len(s) > 300 else '')
                QTreeWidgetItem(parent, [str(key), display])

        root = self._tree.invisibleRootItem()
        label = getattr(node, '_label', str(node))
        state = getattr(node, '_state', '')
        QTreeWidgetItem(root, ['node', label])
        QTreeWidgetItem(root, ['state', state])
        for k, v in meta.items():
            _add(root, k, v)

        # Show/populate model section only for scramda2 action nodes
        action_type = getattr(node, 'action_type', None)
        if action_type == 'scramda2':
            cfg = meta.get('config', {})
            current_profile = cfg.get('modelProfile') or ''
            current_model   = cfg.get('model') or ''
            # Select profile in combo
            idx = 0
            for i in range(self._profile_combo.count()):
                if self._profile_combo.itemData(i) == current_profile:
                    idx = i
                    break
            self._profile_combo.setCurrentIndex(idx)
            self._model_edit.setText(current_model)
            self._model_section.setVisible(True)
        else:
            self._model_section.setVisible(False)

    def _apply_model(self):
        if not self._current_node:
            return
        cfg = self._current_node.meta.get('config')
        if cfg is None:
            return
        profile = self._profile_combo.currentData()
        literal = self._model_edit.text().strip()
        cfg['modelProfile'] = profile or None
        cfg['model']        = literal or None
        # Refresh tree display
        self.show_node(self._current_node)

    def clear(self):
        self._tree.clear()
        self._model_section.setVisible(False)
        self._current_node = None


# ── Log output ────────────────────────────────────────────────────────────────

class LogPanel(QWidget):
    """Live run output, and the row a workflow's questions are answered on.

    Names every event through clay.run.events rather than string literals. The
    literals here had drifted: `workflow.start`/`workflow.complete` are not in
    the vocabulary — the events are `run.start`/`run.complete` — so neither
    branch had ever fired, and there was no `log` branch at all, which is why
    warnings and errors never reached this panel.
    """

    input_submitted = Signal(str, str)   # prompt id, answer

    def __init__(self):
        super().__init__()
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont('Menlo', 9))
        self._log.setMaximumBlockCount(5000)
        layout.addWidget(self._log)

        # ── prompt row: hidden until the workflow asks something ─────────────
        self._prompt_id = ''
        self._prompt_row = QWidget()
        prompt_layout = QHBoxLayout(self._prompt_row)
        prompt_layout.setContentsMargins(0, 0, 0, 0)

        self._prompt_marker = QLabel('?')
        self._prompt_marker.setStyleSheet('color: #00d4aa; font-weight: bold;')
        prompt_layout.addWidget(self._prompt_marker)

        self._prompt_edit = QLineEdit()
        self._prompt_edit.setStyleSheet(
            'background: #141e2b; color: #aed6f1; border: 1px solid #00d4aa; padding: 3px 6px;'
        )
        self._prompt_edit.returnPressed.connect(self._submit)
        prompt_layout.addWidget(self._prompt_edit)

        send_btn = QPushButton('Send')
        send_btn.setMaximumWidth(80)
        send_btn.clicked.connect(self._submit)
        prompt_layout.addWidget(send_btn)

        layout.addWidget(self._prompt_row)
        self._prompt_row.setVisible(False)

        self._workspace_prompt_row = QWidget()
        workspace_layout = QHBoxLayout(self._workspace_prompt_row)
        workspace_layout.setContentsMargins(0, 0, 0, 0)

        self._workspace_approve = QPushButton('Approve & Remember')
        self._workspace_approve.clicked.connect(
            lambda: self._submit_answer('y'))
        workspace_layout.addWidget(self._workspace_approve)

        self._workspace_once = QPushButton('Allow Once')
        self._workspace_once.clicked.connect(
            lambda: self._submit_answer('o'))
        workspace_layout.addWidget(self._workspace_once)

        self._workspace_refuse = QPushButton('Refuse')
        self._workspace_refuse.clicked.connect(
            lambda: self._submit_answer('n'))
        workspace_layout.addWidget(self._workspace_refuse)

        workspace_layout.addStretch()
        layout.addWidget(self._workspace_prompt_row)
        self._workspace_prompt_row.setVisible(False)

        layout.addWidget(self._approval_row())

        clear_btn = QPushButton('Clear')
        clear_btn.setMaximumWidth(80)
        layout.addWidget(clear_btn)
        clear_btn.clicked.connect(self._log.clear)

    # ── manual approval ──────────────────────────────────────────────────────

    def _approval_row(self) -> QWidget:
        """The master switch and one box per gate, always visible.

        Four boxes rather than one, because the three gates are three different
        propositions: approving every read in a workspace is routine where
        approving every write is the thing manual mode exists to stop. A single
        switch would force the noisiest setting on anyone who wanted the
        strictest one.

        Wired straight to clay.run.approval because `clay ui` runs its workflow
        on a worker thread of *this* process — there is no relay to cross, and
        the setting a box shows is the setting the next write reads.
        """
        row = QWidget()
        box_layout = QHBoxLayout(row)
        box_layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel('ask first:')
        label.setStyleSheet('color: #7fa8c9;')
        box_layout.addWidget(label)

        state = approval.state()
        self._approval_boxes = {}
        for key, text in (('manual', 'manual'), ('fileWrites', 'writes'),
                          ('fileReads', 'reads'), ('commands', 'commands')):
            box = QCheckBox(text)
            box.setChecked(bool(state.get(key)))
            box.toggled.connect(
                lambda on, k=key: self._set_approval(k, on))
            box_layout.addWidget(box)
            self._approval_boxes[key] = box

        box_layout.addStretch()
        box_layout.addWidget(self._busy_label())
        self._sync_approval_boxes()
        return row

    # ── busy indicator ───────────────────────────────────────────────────────

    #: Same frames and cadence as the CLI spinner, so the two surfaces of one
    #: product do not each invent their own idea of "working".
    BUSY_FRAMES = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    BUSY_INTERVAL_MS = 80
    #: The label sits on a row beside four checkboxes, so it is cut well below
    #: logger.BUSY_PREVIEW_MAX_CHARS — a longer one stretches the whole panel.
    BUSY_LABEL_MAX = 40

    def _busy_label(self) -> QLabel:
        """The 'working…' label, hidden until an action raises a busy event.

        A label rather than a progress bar: it can say *what* is being waited
        for, which is the whole reason the event carries a prompt preview, and
        a bar cannot. Driven by a QTimer on the GUI thread. WorkflowManager
        marshals clayd's EventSubscriber callback through a queued Qt signal
        before this panel receives it, so nothing here needs marshalling.
        """
        self._busy = QLabel('')
        self._busy.setStyleSheet('color: #7fa8c9;')
        self._busy.setVisible(False)
        self._busy_text = ''
        self._busy_frame = 0
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(self.BUSY_INTERVAL_MS)
        self._busy_timer.timeout.connect(self._tick_busy)
        return self._busy

    def _set_busy(self, event: dict) -> None:
        """Raise, relabel or drop the indicator. `active` is a level."""
        if not event.get('active'):
            self._clear_busy()
            return
        self._busy_text = busy_label(event, self.BUSY_LABEL_MAX)
        self._busy.setVisible(True)
        if not self._busy_timer.isActive():
            self._busy_timer.start()

    def _clear_busy(self) -> None:
        """Idempotent — the run-ending branches all call it unconditionally."""
        self._busy_timer.stop()
        self._busy.setVisible(False)
        self._busy.setText('')
        self._busy_text = ''

    def _tick_busy(self) -> None:
        frame = self.BUSY_FRAMES[self._busy_frame % len(self.BUSY_FRAMES)]
        self._busy_frame += 1
        self._busy.setText(f'{frame}  {self._busy_text}')

    def _set_approval(self, key: str, on: bool) -> None:
        if key == 'manual':
            approval.set_manual(on)
        else:
            approval.set_gate(key, on)
        self._sync_approval_boxes()
        self.append(f'\n»  {approval.summary()}')

    def _sync_approval_boxes(self) -> None:
        """Grey the gates out when the master switch is off.

        Disabled rather than unchecked: the arrangement someone chose survives
        turning manual mode off and comes back when they turn it on, and a box
        that silently cleared itself would read as a setting that was lost.
        """
        live = self._approval_boxes['manual'].isChecked()
        for key, box in self._approval_boxes.items():
            if key != 'manual':
                box.setEnabled(live)

    def append(self, text):
        sb = self._log.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self._log.appendPlainText(text)
        if at_bottom:
            sb.setValue(sb.maximum())

    # ── input ────────────────────────────────────────────────────────────────

    def _ask(self, event):
        self._prompt_id = str(event.get('id', ''))
        self.append(f'\n?  {event.get("prompt", "")}')
        workspace_prompt = self._prompt_id == workspaces.PROMPT_ID
        self._workspace_prompt_row.setVisible(workspace_prompt)
        self._prompt_row.setVisible(not workspace_prompt)
        if workspace_prompt:
            self._workspace_approve.setFocus()
        else:
            self._prompt_edit.setFocus()

    def _submit(self):
        """Send whatever is typed, including nothing.

        An empty answer is a legitimate one — humanDecision reads a blank line
        as "take the default" — so this does not gate on non-empty text. It
        gates on the row being visible, which is the real question: whether a
        prompt is actually outstanding.
        """
        self._submit_answer(self._prompt_edit.text())

    def _submit_answer(self, text):
        """Submit one visible text or workspace-choice prompt exactly once."""
        if self._prompt_row.isHidden() and self._workspace_prompt_row.isHidden():
            return
        prompt_id = self._prompt_id
        self.clear_prompt()
        self.append(f'>  {text}')
        self.input_submitted.emit(prompt_id, text)

    def clear_prompt(self):
        """Withdraw an unanswered question — the run ended or was cancelled."""
        self._prompt_id = ''
        self._prompt_edit.clear()
        self._prompt_row.setVisible(False)
        self._workspace_prompt_row.setVisible(False)

    # ── events ───────────────────────────────────────────────────────────────

    def on_event(self, event):
        t = event.get('type', '')
        if t == events.STEP_START:
            self.append(f'\n── {event.get("step", "")} ──')
        elif t == events.ACTION_START:
            self.append(f'  ▸ {event.get("action_type", "")}  →  {event.get("id", "")}')
        elif t == events.ACTION_DONE:
            ms = event.get('duration_ms', '')
            self.append(f'    done  {ms}ms' if ms else '    done')
        elif t == events.ACTION_OUTPUT:
            self.append(payload_lines(event))
        elif t == events.ACTION_SKIPPED:
            self.append(f'  ▸ skipped  {event.get("id", "")}  '
                        f'({skipped_reason(event)})')
        elif t == events.ACTION_ERROR:
            self.append(f'  ✕ {event.get("message", "")}')
        elif t == events.LOG:
            level = str(event.get('level', '')).upper()
            message = event.get('message', '')
            prefix = f'{level}  ' if level in ('WARN', 'ERROR') else ''
            for line in str(message).split('\n'):
                self.append(f'  {prefix}{line}')
                prefix = ''
        elif t == events.LOOP_ITERATION:
            self.append(f'    loop iter {event.get("iteration")}')
        elif t == events.BUSY:
            self._set_busy(event)
        elif t == events.INPUT_REQUEST:
            self._ask(event)
        elif t == events.RUN_START:
            self.append(f'▶  {event.get("label", "")}')
        elif t == events.RUN_COMPLETE:
            self.append('✓  complete')
            self._clear_busy()
        elif t == events.RUN_CANCELLED:
            self.append('■  cancelled')
            self._clear_busy()
            self.clear_prompt()
        elif t == events.RUN_ERROR:
            self.append(f'✕  {event.get("message", "")}')
            self._clear_busy()
            self.clear_prompt()


# ── File browser ──────────────────────────────────────────────────────────────

class FileBrowser(QWidget):
    """Browse workflow JSON files on disk."""

    file_selected = Signal(str)

    def __init__(self, roots=None):
        super().__init__()
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel('Workflows')
        title.setFont(QFont('Menlo', 11, QFont.Bold))
        title.setStyleSheet('color: #aed6f1;')
        layout.addWidget(title)

        self._model = QFileSystemModel()
        self._model.setNameFilters(['*.json'])
        self._model.setNameFilterDisables(False)

        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setColumnHidden(1, True)  # size
        self._tree.setColumnHidden(2, True)  # type
        self._tree.setColumnHidden(3, True)  # date
        self._tree.header().setStretchLastSection(True)
        self._tree.setAnimated(True)
        self._tree.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._tree)

        # Set root paths
        self._roots = roots or []
        if self._roots:
            root = self._roots[0]
            self._model.setRootPath(root)
            self._tree.setRootIndex(self._model.index(root))

    def set_root(self, path):
        if os.path.isdir(path):
            self._model.setRootPath(path)
            self._tree.setRootIndex(self._model.index(path))

    def _on_double_click(self, index):
        path = self._model.filePath(index)
        if path.endswith('.json') and os.path.isfile(path):
            self.file_selected.emit(path)


# ── Memory browser ────────────────────────────────────────────────────────────

class MemoryPanel(QWidget):
    """Browse memory namespaces and entries."""

    def __init__(self, memory_root):
        super().__init__()
        self._root = memory_root
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel('Memory')
        title.setFont(QFont('Menlo', 11, QFont.Bold))
        title.setStyleSheet('color: #aed6f1;')
        layout.addWidget(title)

        refresh_btn = QPushButton('↺  Refresh')
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(['Entry', 'Tags'])
        self._tree.setColumnWidth(0, 180)
        layout.addWidget(self._tree)

        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setFont(QFont('Menlo', 9))
        self._detail.setMaximumHeight(120)
        layout.addWidget(self._detail)

        self._tree.itemClicked.connect(self._on_item_clicked)
        self.refresh()

    def refresh(self):
        self._tree.clear()
        if not os.path.isdir(self._root):
            return
        for ns in sorted(os.listdir(self._root)):
            ns_path = os.path.join(self._root, ns)
            if not os.path.isdir(ns_path):
                continue
            ns_item = QTreeWidgetItem(self._tree, [ns, ''])
            ns_item.setData(0, Qt.UserRole, None)
            for fname in sorted(os.listdir(ns_path)):
                if not fname.endswith('.json'):
                    continue
                fpath = os.path.join(ns_path, fname)
                try:
                    with open(fpath) as f:
                        entry = json.load(f)
                    tags = ', '.join(entry.get('tags', []))
                except Exception:
                    tags = ''
                child = QTreeWidgetItem(ns_item, [fname[:-5], tags])
                child.setData(0, Qt.UserRole, fpath)
            ns_item.setExpanded(True)

    def _on_item_clicked(self, item, _col):
        fpath = item.data(0, Qt.UserRole)
        if not fpath:
            self._detail.clear()
            return
        try:
            with open(fpath) as f:
                entry = json.load(f)
            content = entry.get('content', json.dumps(entry, indent=2))
            self._detail.setPlainText(str(content)[:2000])
        except Exception as e:
            self._detail.setPlainText(str(e))
