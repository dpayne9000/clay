"""Connect the Qt UI to the clayd system daemon.

The manager does not spawn subprocesses. It relays events from clayd's Unix
socket to Qt widgets.

All widget access occurs on the main thread. The background EventSubscriber
emits a signal whose connected slot performs updates.
"""
import json
import time
from PySide6.QtCore import (
    Qt, QObject, Signal, Slot, QAbstractTableModel, QModelIndex, QTimer,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableView, QPushButton,
    QHeaderView, QAbstractItemView, QMenu, QSplitter, QLabel,
    QPlainTextEdit, QLineEdit, QTabWidget,
)
from PySide6.QtGui import QColor, QBrush, QFont

from ..daemon.client import DaemonClient, EventSubscriber
from ..run import workspaces
from ..run.renderers.detail import busy_label, payload_lines, skipped_reason


# ── Table model ───────────────────────────────────────────────────────────────

_COLUMNS = ['Name', 'ID', 'Status', 'Runtime', 'Step', 'Action', 'Iters', 'Events']


class _WfRow:
    """Store a local copy of workflow state reported by the daemon."""
    __slots__ = (
        'wf_id', 'name', 'filename', 'pid', 'status', 'started_at',
        'iterations', 'current_step', 'current_action', 'events_received',
        'pending_prompt', 'pending_prompt_id',
    )

    def __init__(self, info):
        self.wf_id = info.get('id', '')
        self.name = info.get('name', '')
        self.filename = info.get('filename', '')
        self.pid = info.get('pid', 0)
        self.status = info.get('status', 'starting')
        self.started_at = info.get('started_at', 0.0)
        self.iterations = info.get('iterations', 0)
        self.current_step = info.get('current_step', '')
        self.current_action = info.get('current_action', '')
        self.events_received = info.get('events_received', 0)
        self.pending_prompt = info.get('pending_prompt', '')
        self.pending_prompt_id = info.get('pending_prompt_id', '')

    def update(self, info):
        for k in self.__slots__:
            if k in info:
                setattr(self, k, info[k])
            elif k == 'wf_id' and 'id' in info:
                self.wf_id = info['id']


class ProcessModel(QAbstractTableModel):

    def __init__(self):
        super().__init__()
        self._rows = []   # list[_WfRow]

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        p = self._rows[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0: return p.name
            if col == 1: return p.wf_id
            if col == 2: return p.status
            if col == 3:
                if p.started_at:
                    m, s = divmod(int(time.time() - p.started_at), 60)
                    h, m = divmod(m, 60)
                    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'
                return '-'
            if col == 4: return p.current_step
            if col == 5: return p.current_action
            if col == 6: return str(p.iterations)
            if col == 7: return str(p.events_received)
        if role == Qt.ForegroundRole:
            colors = {
                'starting': QColor('#f39c12'),
                'running':  QColor('#00d4aa'),
                'done':     QColor('#2ecc71'),
                'error':    QColor('#e74c3c'),
                'stopped':  QColor('#8e8e8e'),
            }
            if col == 2:
                if p.pending_prompt:
                    return QBrush(QColor('#f39c12'))
                return QBrush(colors.get(p.status, QColor('#8ab4cc')))
        if role == Qt.UserRole:
            return p
        return None

    def add(self, info):
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(_WfRow(info))
        self.endInsertRows()

    def refresh_row(self, wf_id):
        for i, p in enumerate(self._rows):
            if p.wf_id == wf_id:
                self.dataChanged.emit(
                    self.index(i, 0), self.index(i, self.columnCount() - 1),
                    [Qt.DisplayRole, Qt.ForegroundRole],
                )
                return

    def update_row(self, wf_id, info):
        for i, p in enumerate(self._rows):
            if p.wf_id == wf_id:
                p.update(info)
                self.dataChanged.emit(
                    self.index(i, 0), self.index(i, self.columnCount() - 1),
                    [Qt.DisplayRole, Qt.ForegroundRole],
                )
                return

    def remove(self, wf_id):
        for i, p in enumerate(self._rows):
            if p.wf_id == wf_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._rows.pop(i)
                self.endRemoveRows()
                return

    def info_for(self, wf_id):
        for p in self._rows:
            if p.wf_id == wf_id:
                return p
        return None

    def find_or_add(self, wf_id, info):
        existing = self.info_for(wf_id)
        if existing:
            return existing
        self.add(info)
        return self._rows[-1]


# ── Per-daemon terminal ───────────────────────────────────────────────────────

class DaemonTerminal(QWidget):
    """Display one daemon workflow's output and input field."""

    input_submitted = Signal(str, str)   # wf_id, text

    def __init__(self, wf_id):
        super().__init__()
        self.wf_id = wf_id
        self._pending_lines = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont('Menlo', 9))
        self._output.setMaximumBlockCount(5000)
        self._output.setStyleSheet(
            'background: #0a1018; color: #7fb3cc; border: 1px solid #1e2a3a;'
        )
        layout.addWidget(self._output)

        # Busy state shows long model calls without appending persistent output
        # for each status relabel.
        self._busy = QLabel('')
        self._busy.setStyleSheet(
            'color: #7fa8c9; padding: 2px 6px; font-family: Menlo;'
        )
        self._busy.hide()
        layout.addWidget(self._busy)

        # Show the input bar only while a prompt is pending.
        self._input_bar = QWidget()
        ib_layout = QHBoxLayout(self._input_bar)
        ib_layout.setContentsMargins(0, 0, 0, 0)
        self._prompt_label = QLabel('')
        self._prompt_label.setStyleSheet('color: #f39c12; font-family: Menlo; font-size: 11px;')
        ib_layout.addWidget(self._prompt_label)
        self._input = QLineEdit()
        self._input.setStyleSheet(
            'background: #141e2b; color: #aed6f1; border: 1px solid #2e4a63;'
            'padding: 3px 8px; font-family: Menlo; font-size: 11px;'
        )
        self._input.returnPressed.connect(self._submit)
        ib_layout.addWidget(self._input)
        self._send_btn = QPushButton('Send')
        self._send_btn.setStyleSheet(
            'background: #1e2a3a; color: #aed6f1; border: 1px solid #2e4a63;'
            'padding: 3px 12px; font-family: Menlo;'
        )
        self._send_btn.clicked.connect(self._submit)
        ib_layout.addWidget(self._send_btn)
        layout.addWidget(self._input_bar)
        self._input_bar.hide()

        self._workspace_bar = QWidget()
        workspace_layout = QHBoxLayout(self._workspace_bar)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        self._workspace_approve = QPushButton('Approve & Remember')
        self._workspace_approve.clicked.connect(
            lambda: self._submit_choice('y'))
        workspace_layout.addWidget(self._workspace_approve)
        self._workspace_once = QPushButton('Allow Once')
        self._workspace_once.clicked.connect(
            lambda: self._submit_choice('o'))
        workspace_layout.addWidget(self._workspace_once)
        self._workspace_refuse = QPushButton('Refuse')
        self._workspace_refuse.clicked.connect(
            lambda: self._submit_choice('n'))
        workspace_layout.addWidget(self._workspace_refuse)
        workspace_layout.addStretch()
        layout.addWidget(self._workspace_bar)
        self._workspace_bar.hide()

        # Flush buffered output every 50 ms to reduce repaints.
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_output)
        self._flush_timer.start()

    def append_output(self, text):
        """Queue a line for the timer's next batched update."""
        self._pending_lines.append(text)

    def _flush_output(self):
        if not self._pending_lines:
            return
        sb = self._output.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self._output.appendPlainText('\n'.join(self._pending_lines))
        self._pending_lines.clear()
        if at_bottom:
            sb.setValue(sb.maximum())

    def show_prompt(self, prompt_text, prompt_id=''):
        self._prompt_label.setText(prompt_text[:80] + '> ')
        workspace_prompt = prompt_id == workspaces.PROMPT_ID
        self._workspace_bar.setVisible(workspace_prompt)
        self._input_bar.setVisible(not workspace_prompt)
        if workspace_prompt:
            self._workspace_approve.setFocus()
        else:
            self._input.setFocus()

    def hide_prompt(self):
        self._input_bar.hide()
        self._workspace_bar.hide()
        self._input.clear()

    def set_busy(self, event):
        if not event.get('active'):
            self.clear_busy()
            return
        self._busy.setText(f'⠋  {busy_label(event, 72)}')
        self._busy.show()

    def clear_busy(self):
        self._busy.hide()
        self._busy.setText('')

    def _submit(self):
        text = self._input.text().strip()
        if not text:
            return
        self._submit_choice(text)

    def _submit_choice(self, text):
        self._input.clear()
        self.hide_prompt()
        self._pending_lines.append(f'> {text}')
        self.input_submitted.emit(self.wf_id, text)


# ── Manager (daemon client) ─────────────────────────────────────────────────

class WorkflowManager(QObject):
    """Connect to clayd and relay events to Qt models and widgets.

    EventSubscriber runs on a background thread. _raw_event carries serialized
    JSON across the thread boundary, and _handle_event updates widgets on the
    main thread.
    """

    # Public signals
    daemon_event = Signal(str, dict)     # wf_id, event_dict
    daemon_finished = Signal(str)        # wf_id
    connection_lost = Signal()

    # Serialized JSON crosses the Qt thread boundary more reliably than dict.
    _raw_event = Signal(str)

    def __init__(self):
        super().__init__()
        self.model = ProcessModel()
        self._terminals = {}     # wf_id → DaemonTerminal
        self._subscriber = None
        self._connected = False

        # Route background events to the main-thread handler.
        self._raw_event.connect(self._handle_event, Qt.QueuedConnection)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._refresh_runtimes)
        self._tick.start(1000)

        # Retry daemon connections every five seconds.
        self._reconnect = QTimer(self)
        self._reconnect.timeout.connect(self._try_connect)
        self._reconnect.start(5000)

        # Attempt the initial connection after UI initialization.
        QTimer.singleShot(100, self._try_connect)

    def _try_connect(self):
        if self._connected:
            return
        try:
            with DaemonClient() as c:
                c.ping()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            return

        try:
            self._subscriber = EventSubscriber()
            self._subscriber.on_event(self._on_subscriber_event)
            self._subscriber.start()
            self._connected = True
            self._sync_list()
        except (ConnectionRefusedError, FileNotFoundError, OSError):
            self._subscriber = None

    def _sync_list(self):
        """Load the current daemon workflow list on the main thread."""
        try:
            with DaemonClient() as c:
                workflows = c.list_workflows()
            for info in workflows:
                wf_id = info.get('id', '')
                self.model.find_or_add(wf_id, info)
                if wf_id not in self._terminals:
                    term = DaemonTerminal(wf_id)
                    term.input_submitted.connect(self._on_input)
                    self._terminals[wf_id] = term
        except Exception:
            pass

    # ── Thread-safe event bridge ─────────────────────────────────────────

    def _on_subscriber_event(self, event):
        """Serialize a background event and emit it to the main thread."""
        try:
            self._raw_event.emit(json.dumps(event, default=str))
        except Exception:
            pass

    @Slot(str)
    def _handle_event(self, raw):
        """Process a serialized event on the main Qt thread."""
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            return

        ev = event.get('event', '')
        wf_id = event.get('id', '')

        if not wf_id:
            if ev == 'daemon-stopping':
                self._connected = False
                self.connection_lost.emit()
            return

        # Ensure the workflow has a model row and terminal.
        if ev == 'started':
            self.model.find_or_add(wf_id, event)
            if wf_id not in self._terminals:
                term = DaemonTerminal(wf_id)
                term.input_submitted.connect(self._on_input)
                self._terminals[wf_id] = term

        # Update model state from daemon status events.
        if ev in ('started', 'status'):
            self.model.update_row(wf_id, event)

        # Render the event in the workflow terminal.
        term = self._terminals.get(wf_id)
        if ev == 'stdout' and term:
            term.append_output(event.get('line', ''))
        elif ev == 'stderr' and term:
            term.append_output(f'[stderr] {event.get("line", "")}')
        elif ev == 'prompt' and term:
            term.show_prompt(
                event.get('text', ''), event.get('prompt_id', ''))
        elif ev == 'workflow':
            data = event.get('data', {})
            t = data.get('type', '')
            row = self.model.info_for(wf_id)
            if row:
                row.events_received += 1
                if t == 'step.start':
                    row.current_step = data.get('step', '')
                elif t == 'action.start':
                    row.current_action = f"{data.get('action_type', '')}:{data.get('id', '')}"
                elif t == 'action.complete':
                    row.current_action = ''
                elif t == 'loop.iteration':
                    row.iterations += 1
                self.model.refresh_row(wf_id)
            if term:
                if t == 'step.start':
                    term.append_output(f'\n── {data.get("step", "")} ──')
                elif t == 'action.start':
                    term.append_output(f'  ▸ {data.get("action_type", "")}  →  {data.get("id", "")}')
                elif t == 'action.complete' and data.get('action_type') == 'scramda2':
                    term.append_output(data.get('data') or '')
                elif t == 'action.complete':
                    ms = data.get('duration_ms', '')
                    term.append_output(f'    done  {ms}ms' if ms else '    done')
                    term.clear_busy()
                elif t in ('action.error', 'run.error'):
                    term.append_output(f'  !! {data.get("message", "")}')
                    term.clear_busy()
                elif t == 'action.output':
                    # Structured output events now carry content that previously
                    # arrived through log events.
                    term.append_output(payload_lines(data))
                elif t == 'action.skipped':
                    term.append_output(f'  ▸ skipped  {data.get("id", "")}  '
                                       f'({skipped_reason(data)})')
                elif t == 'log':
                    term.append_output(f'  {data.get("message", "")}')
                elif t == 'loop.iteration':
                    term.append_output(f'    loop iter {data.get("iteration")}')
                elif t == 'busy':
                    term.set_busy(data)
        elif ev == 'finished':
            row = self.model.info_for(wf_id)
            if row:
                row.status = event.get('status', 'done')
                self.model.refresh_row(wf_id)
            if term:
                term.hide_prompt()
                term.clear_busy()
                term.append_output(f'\n✓  process exited ({event.get("exit_code", "?")})')
            self.daemon_finished.emit(wf_id)

        self.daemon_event.emit(wf_id, event)

    # ── Commands (use short-lived DaemonClient connections) ──────────────

    def start_daemon(self, filename, auto=True, daemon_mode=True):
        """Ask clayd to start a workflow and return (workflow ID, error)."""
        if not self._connected:
            self._try_connect()
        if not self._connected:
            return None, 'Not connected to clayd'
        try:
            with DaemonClient() as c:
                resp = c.start_workflow(filename, auto=auto, daemon_mode=daemon_mode)
            if resp.get('ok'):
                wf_id = resp['id']
                self.model.add({
                    'id': wf_id, 'name': resp.get('name', ''),
                    'pid': resp.get('pid', 0), 'status': resp.get('status', 'starting'),
                    'filename': filename, 'started_at': time.time(),
                })
                term = DaemonTerminal(wf_id)
                term.input_submitted.connect(self._on_input)
                self._terminals[wf_id] = term
                return wf_id, None
            else:
                return None, resp.get('error', 'unknown error')
        except Exception as e:
            return None, str(e)

    def stop_daemon(self, wf_id):
        if not self._connected:
            return
        try:
            with DaemonClient() as c:
                resp = c.stop_workflow(wf_id)
            row = self.model.info_for(wf_id)
            if row and resp.get('ok'):
                row.status = 'stopped'
                self.model.refresh_row(wf_id)
                term = self._terminals.get(wf_id)
                if term:
                    term.append_output('\n■  stopped')
        except Exception:
            pass

    def stop_all(self):
        for row in self.model._rows:
            if row.status in ('running', 'starting'):
                self.stop_daemon(row.wf_id)
        if self._subscriber:
            self._subscriber.stop()
            self._subscriber = None
            self._connected = False

    def terminal(self, wf_id):
        return self._terminals.get(wf_id)

    @Slot(str, str)
    def _on_input(self, wf_id, text):
        """Relay terminal input to the daemon."""
        self.send_input(wf_id, text)

    def send_input(self, wf_id, text) -> bool:
        """Relay input to one daemon workflow; usable outside its terminal."""
        if not self._connected:
            return False
        try:
            with DaemonClient() as c:
                return bool(c.send_input(wf_id, text).get('ok'))
        except Exception:
            return False

    def _refresh_runtimes(self):
        for i, p in enumerate(self.model._rows):
            if p.status in ('starting', 'running'):
                idx = self.model.index(i, 3)
                self.model.dataChanged.emit(idx, idx, [Qt.DisplayRole])

    def cleanup_finished(self):
        to_remove = [p.wf_id for p in self.model._rows
                     if p.status in ('done', 'error', 'stopped')]
        for wf_id in to_remove:
            self._terminals.pop(wf_id, None)
            self.model.remove(wf_id)


# ── Process panel widget ──────────────────────────────────────────────────────

class ProcessPanel(QWidget):
    """Display daemon workflows and their terminal tabs."""

    open_workflow_requested = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self._mgr = manager
        self.setStyleSheet(_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # Place the workflow table on the left.
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self._table = QTableView()
        self._table.setModel(manager.model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        stop_btn = QPushButton('■  Stop')
        stop_btn.clicked.connect(self._stop_selected)
        clear_btn = QPushButton('Clear finished')
        clear_btn.clicked.connect(lambda: manager.cleanup_finished())
        btn_row.addWidget(stop_btn)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        left_layout.addLayout(btn_row)

        splitter.addWidget(left)

        # Place workflow terminals on the right.
        self._term_tabs = QTabWidget()
        self._term_tabs.setDocumentMode(True)
        self._term_tabs.setTabsClosable(False)
        self._term_tabs.setStyleSheet("""
            QTabBar::tab {
                background: #141e2b; color: #4a7fa5; border: 1px solid #1e2a3a;
                padding: 4px 10px; font-family: Menlo; font-size: 10px;
            }
            QTabBar::tab:selected { background: #1e2a3a; color: #aed6f1; }
        """)
        splitter.addWidget(self._term_tabs)
        splitter.setSizes([400, 600])

        layout.addWidget(splitter)

        # Create terminal tabs as daemon events arrive.
        self._tabbed_ids = set()   # O(1) check — avoids scanning tabs on every event
        manager.daemon_event.connect(self._ensure_tab)

    def _ensure_tab(self, wf_id, _event):
        """Create terminal tab for workflow if it doesn't exist yet."""
        if wf_id in self._tabbed_ids:
            return
        term = self._mgr.terminal(wf_id)
        if not term:
            return
        info = self._mgr.model.info_for(wf_id)
        label = info.name if info else wf_id
        self._term_tabs.addTab(term, label)
        self._term_tabs.setCurrentWidget(term)
        self._tabbed_ids.add(wf_id)

    def _selected_wf_id(self):
        idxs = self._table.selectionModel().selectedRows()
        if idxs:
            info = self._mgr.model.data(idxs[0], Qt.UserRole)
            if info:
                return info.wf_id
        return None

    def _stop_selected(self):
        wf_id = self._selected_wf_id()
        if wf_id:
            self._mgr.stop_daemon(wf_id)

    def _on_selection_changed(self, selected, _deselected):
        """Switch to the terminal tab when a row is selected."""
        wf_id = self._selected_wf_id()
        if not wf_id:
            return
        term = self._mgr.terminal(wf_id)
        if not term:
            return
        for i in range(self._term_tabs.count()):
            if self._term_tabs.widget(i) is term:
                self._term_tabs.setCurrentIndex(i)
                return

    def _context_menu(self, pos):
        wf_id = self._selected_wf_id()
        if not wf_id:
            return
        info = self._mgr.model.info_for(wf_id)
        if not info:
            return
        menu = QMenu(self)
        if info.status in ('running', 'starting'):
            menu.addAction('Stop', lambda: self._mgr.stop_daemon(wf_id))
        if info.filename:
            menu.addAction('Open workflow', lambda: self.open_workflow_requested.emit(info.filename))
        if info.status in ('done', 'error', 'stopped'):
            menu.addAction('Remove', lambda: self._mgr.model.remove(wf_id))
        menu.exec(self._table.viewport().mapToGlobal(pos))


_STYLE = """
QWidget { background: #0d1520; color: #8ab4cc; font-family: Menlo, monospace; font-size: 11px; }
QTableView {
    background: #0a1018; alternate-background-color: #0e1825;
    color: #8ab4cc; border: 1px solid #1e2a3a; gridline-color: #1e2a3a;
    selection-background-color: #1e3a52;
}
QHeaderView::section {
    background: #141e2b; color: #4a7fa5; border: none;
    border-bottom: 1px solid #2e4a63; padding: 3px 6px; font-weight: bold;
}
QPushButton {
    background: #1e2a3a; color: #aed6f1; border: 1px solid #2e4a63;
    padding: 4px 12px; border-radius: 3px;
}
QPushButton:hover { background: #2e4a63; }
"""
