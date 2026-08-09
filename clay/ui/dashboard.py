"""Process Management Dashboard — hacker-style multi-agent control center.

Full-screen dashboard showing each running agent in its own card with
live terminal output, metrics, status indicators, and controls.
"""
import time
from PySide6.QtCore import Qt, Signal, Slot, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QScrollArea, QFrame, QSizePolicy,
    QFileDialog, QSplitter, QProgressBar,
)
from PySide6.QtGui import QFont, QColor, QPainter, QPen

from ..run import workspaces
from ..run.renderers.detail import payload_lines, skipped_reason


# ── Metrics bar ──────────────────────────────────────────────────────────────

class MetricsBar(QWidget):
    """Top bar showing aggregate stats across all agents."""

    def __init__(self, manager):
        super().__init__()
        self._mgr = manager
        self.setFixedHeight(52)
        self.setStyleSheet('background: #080e16; border-bottom: 1px solid #1a2738;')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)

        self._title = QLabel('PROCESS DASHBOARD')
        self._title.setStyleSheet(
            'color: #00d4aa; font-family: Menlo; font-size: 14px; font-weight: bold;'
            'letter-spacing: 3px; border: none;'
        )
        layout.addWidget(self._title)
        layout.addStretch()

        self._metric_vals = {}
        for key, label, color in [
            ('total',   'TOTAL',   '#4a7fa5'),
            ('running', 'RUNNING', '#00d4aa'),
            ('done',    'DONE',    '#2ecc71'),
            ('error',   'ERROR',   '#e74c3c'),
            ('stopped', 'STOPPED', '#8e8e8e'),
        ]:
            w, val_lbl = self._make_metric(label, '0', color)
            self._metric_vals[key] = val_lbl
            layout.addWidget(w)

        self._uptime = QLabel('00:00:00')
        self._uptime.setStyleSheet(
            'color: #2e4a63; font-family: Menlo; font-size: 10px; border: none;'
        )
        layout.addWidget(self._uptime)

        self._start_time = time.time()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)

    def _make_metric(self, label, value, color):
        w = QWidget()
        w.setStyleSheet('border: none;')
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 4, 12, 4)
        vl.setSpacing(0)
        val = QLabel(value)
        val.setAlignment(Qt.AlignCenter)
        val.setStyleSheet(f'color: {color}; font-family: Menlo; font-size: 18px; font-weight: bold; border: none;')
        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet('color: #2e4a63; font-family: Menlo; font-size: 8px; letter-spacing: 2px; border: none;')
        vl.addWidget(val)
        vl.addWidget(lbl)
        return w, val

    def _refresh(self):
        rows = self._mgr.model._rows
        counts = {'total': len(rows), 'running': 0, 'done': 0, 'error': 0, 'stopped': 0}
        for r in rows:
            s = r.status
            if s in ('running', 'starting'):
                counts['running'] += 1
            elif s == 'done':
                counts['done'] += 1
            elif s == 'error':
                counts['error'] += 1
            elif s == 'stopped':
                counts['stopped'] += 1
        for key, lbl in self._metric_vals.items():
            lbl.setText(str(counts.get(key, 0)))

        elapsed = int(time.time() - self._start_time)
        h, rem = divmod(elapsed, 3600)
        m, s = divmod(rem, 60)
        self._uptime.setText(f'UP {h:02d}:{m:02d}:{s:02d}')


# ── Agent card ───────────────────────────────────────────────────────────────

class AgentCard(QFrame):
    """Single agent card with status, terminal, metrics, and controls."""

    stop_requested = Signal(str)
    input_submitted = Signal(str, str)  # wf_id, text

    def __init__(self, wf_id, name, manager):
        super().__init__()
        self.wf_id = wf_id
        self._name = name
        self._mgr = manager
        self._events = 0
        self._iters = 0
        self._step = ''
        self._action = ''
        self._status = 'starting'
        self._started = time.time()

        # Output buffer — flushed by timer to avoid per-line repaints
        self._pending_lines = []

        self.setObjectName('agentCard')
        self.setFrameStyle(QFrame.StyledPanel)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName('cardHeader')
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 6, 10, 6)

        self._status_dot = QLabel('●')
        self._status_dot.setStyleSheet('color: #f39c12; font-size: 10px; border: none;')
        hl.addWidget(self._status_dot)

        self._name_label = QLabel(f' {name}')
        self._name_label.setStyleSheet(
            'color: #aed6f1; font-family: Menlo; font-size: 12px; font-weight: bold; border: none;'
        )
        hl.addWidget(self._name_label)

        self._id_label = QLabel(f'  {wf_id}')
        self._id_label.setStyleSheet('color: #2e4a63; font-family: Menlo; font-size: 10px; border: none;')
        hl.addWidget(self._id_label)
        hl.addStretch()

        self._runtime_label = QLabel('0:00')
        self._runtime_label.setStyleSheet('color: #4a7fa5; font-family: Menlo; font-size: 10px; border: none;')
        hl.addWidget(self._runtime_label)

        self._stop_btn = QPushButton('Kill')
        self._stop_btn.setFixedSize(38, 22)
        self._stop_btn.setStyleSheet(
            'background: #1a0a0a; color: #e74c3c; border: 1px solid #3a1a1a;'
            'border-radius: 3px; font-size: 10px; font-family: Menlo; font-weight: bold;'
        )
        self._stop_btn.setToolTip('Kill agent')
        self._stop_btn.clicked.connect(lambda: self.stop_requested.emit(self.wf_id))
        hl.addWidget(self._stop_btn)

        layout.addWidget(header)

        # ── Stats row ────────────────────────────────────────────────────
        stats = QWidget()
        stats.setObjectName('cardStats')
        sl = QHBoxLayout(stats)
        sl.setContentsMargins(10, 2, 10, 2)
        sl.setSpacing(16)

        # Cache value label references directly — no findChild on every update
        self._step_label,   self._step_val   = self._stat('STEP',   '-')
        self._action_label, self._action_val = self._stat('ACTION', '-')
        self._events_label, self._events_val = self._stat('EVTS',   '0')
        self._iters_label,  self._iters_val  = self._stat('ITERS',  '0')
        sl.addWidget(self._step_label)
        sl.addWidget(self._action_label)
        sl.addStretch()
        sl.addWidget(self._events_label)
        sl.addWidget(self._iters_label)

        layout.addWidget(stats)

        # ── Terminal ─────────────────────────────────────────────────────
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFont('Menlo', 9))
        self._output.setMaximumBlockCount(3000)
        self._output.setObjectName('cardTerminal')
        layout.addWidget(self._output, 1)

        # ── Input bar ────────────────────────────────────────────────────
        self._input_bar = QWidget()
        self._input_bar.setObjectName('cardInput')
        ibl = QHBoxLayout(self._input_bar)
        ibl.setContentsMargins(8, 4, 8, 4)
        self._prompt_label = QLabel('>')
        self._prompt_label.setStyleSheet('color: #f39c12; font-family: Menlo; font-size: 11px; border: none;')
        ibl.addWidget(self._prompt_label)
        self._input = QLineEdit()
        self._input.setPlaceholderText('type response...')
        self._input.setObjectName('cardInputField')
        self._input.returnPressed.connect(self._submit)
        ibl.addWidget(self._input)
        send = QPushButton('↵')
        send.setFixedSize(28, 24)
        send.setStyleSheet(
            'background: #0a2a1a; color: #00d4aa; border: 1px solid #1a3a2a;'
            'border-radius: 3px; font-family: Menlo; font-size: 12px;'
        )
        send.clicked.connect(self._submit)
        ibl.addWidget(send)
        layout.addWidget(self._input_bar)
        self._input_bar.hide()

        self._workspace_bar = QWidget()
        self._workspace_bar.setObjectName('cardWorkspaceInput')
        workspace_layout = QHBoxLayout(self._workspace_bar)
        workspace_layout.setContentsMargins(8, 4, 8, 4)
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

        # ── Status bar ───────────────────────────────────────────────────
        self._status_bar = QLabel('')
        self._status_bar.setObjectName('cardStatusBar')
        self._status_bar.setFixedHeight(18)
        layout.addWidget(self._status_bar)

        self.set_status('starting')

        # ── Output flush timer (50 ms) ───────────────────────────────────
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(50)
        self._flush_timer.timeout.connect(self._flush_output)
        self._flush_timer.start()

    def _stat(self, label, value):
        """Return (container_widget, value_label) — caller stores both."""
        w = QWidget()
        w.setStyleSheet('border: none;')
        hl = QHBoxLayout(w)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        lbl = QLabel(label)
        lbl.setStyleSheet('color: #2e4a63; font-family: Menlo; font-size: 8px; letter-spacing: 1px; border: none;')
        val = QLabel(value)
        val.setStyleSheet('color: #4a7fa5; font-family: Menlo; font-size: 10px; border: none;')
        hl.addWidget(lbl)
        hl.addWidget(val)
        return w, val

    def set_status(self, status):
        self._status = status
        _colors = {
            'starting': ('#f39c12', '#1a1200'),
            'running':  ('#00d4aa', '#0a1a14'),
            'done':     ('#2ecc71', '#0a1a0e'),
            'error':    ('#e74c3c', '#1a0a0a'),
            'stopped':  ('#8e8e8e', '#121212'),
        }
        dot_color, bg_tint = _colors.get(status, ('#4a7fa5', '#0a1018'))
        # Single batch stylesheet update — avoids double repaint
        self._status_dot.setStyleSheet(f'color: {dot_color}; font-size: 10px; border: none;')
        self._status_bar.setStyleSheet(
            f'background: {bg_tint}; color: {dot_color};'
            f'font-family: Menlo; font-size: 8px; letter-spacing: 2px;'
            f'padding-left: 8px; border-top: 1px solid #1a2738;'
        )
        self._status_bar.setText(f'  {status.upper()}')
        if status in ('done', 'error', 'stopped'):
            self._stop_btn.setEnabled(False)
            self._stop_btn.setStyleSheet(
                'background: #0e1520; color: #2e4a63; border: 1px solid #1a2738;'
                'border-radius: 3px; font-size: 10px; font-family: Menlo;'
            )

    def update_runtime(self):
        if self._status in ('starting', 'running'):
            elapsed = int(time.time() - self._started)
            m, s = divmod(elapsed, 60)
            h, m = divmod(m, 60)
            self._runtime_label.setText(f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}')

    # ── Buffered terminal output ──────────────────────────────────────────

    def append_output(self, text):
        """Queue a line — flushed in batch by the 50 ms timer."""
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

    # ── Human-input prompt ───────────────────────────────────────────────

    def show_prompt(self, text, prompt_id=''):
        self._prompt_label.setText(text[:60] + '> ')
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

    # ── Stat updates (direct label reference — no findChild) ─────────────

    def on_step(self, step):
        self._step = step
        self._step_val.setText(str(step)[:30])

    def on_action(self, action):
        self._action = action
        self._action_val.setText(str(action or '-')[:30])

    def on_event_count(self, count):
        self._events = count
        self._events_val.setText(str(count))

    def on_iteration(self, count):
        self._iters = count
        self._iters_val.setText(str(count))

    def _submit(self):
        text = self._input.text().strip()
        if not text:
            return
        self._submit_choice(text)

    def _submit_choice(self, text):
        self.hide_prompt()
        self._pending_lines.append(f'> {text}')
        self.input_submitted.emit(self.wf_id, text)


# ── Dashboard ────────────────────────────────────────────────────────────────

class ProcessDashboard(QWidget):
    """Full-screen process management dashboard."""

    open_workflow_requested = Signal(str)

    def __init__(self, manager):
        super().__init__()
        self._mgr = manager
        self._cards = {}            # wf_id → AgentCard
        self._card_positions = {}   # AgentCard → (row, col) currently in grid
        self._cols = 1
        self.setStyleSheet(_DASH_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top metrics bar ──────────────────────────────────────────────
        self._metrics = MetricsBar(manager)
        layout.addWidget(self._metrics)

        # ── Toolbar ──────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName('dashToolbar')
        toolbar.setFixedHeight(36)
        tbl = QHBoxLayout(toolbar)
        tbl.setContentsMargins(12, 0, 12, 0)

        btn_launch = QPushButton('+ Launch Agent')
        btn_launch.setObjectName('launchBtn')
        btn_launch.clicked.connect(self._launch_agent)
        tbl.addWidget(btn_launch)

        btn_stop_all = QPushButton('Kill All')
        btn_stop_all.setObjectName('stopAllBtn')
        btn_stop_all.clicked.connect(self._stop_all)
        tbl.addWidget(btn_stop_all)

        btn_clear = QPushButton('Clear Finished')
        btn_clear.setObjectName('clearBtn')
        btn_clear.clicked.connect(self._clear_finished)
        tbl.addWidget(btn_clear)

        tbl.addStretch()

        self._agent_count = QLabel('0 agents')
        self._agent_count.setStyleSheet(
            'color: #2e4a63; font-family: Menlo; font-size: 10px; border: none;'
        )
        tbl.addWidget(self._agent_count)

        layout.addWidget(toolbar)

        # ── Card grid (scrollable) ───────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName('cardScroll')
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._grid_widget = QWidget()
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(8, 8, 8, 8)
        self._grid_layout.setSpacing(8)
        scroll.setWidget(self._grid_widget)
        layout.addWidget(scroll, 1)

        # ── Empty state ──────────────────────────────────────────────────
        self._empty = QLabel('NO ACTIVE AGENTS\n\nClick "+ Launch Agent" or use the Daemon button in the editor')
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setStyleSheet(
            'color: #1e3a52; font-family: Menlo; font-size: 14px;'
            'letter-spacing: 2px; border: none;'
        )
        self._grid_layout.addWidget(self._empty, 0, 0, 1, 2, Qt.AlignCenter)
        self._empty_in_grid = True

        # ── Wire signals ─────────────────────────────────────────────────
        manager.daemon_event.connect(self._on_event)
        manager.daemon_finished.connect(self._on_finished)

        # Runtime ticker
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._tick_runtimes)
        self._tick.start(1000)

        # Sync existing agents
        self._sync()

    # ── Sync with daemon state ───────────────────────────────────────────

    def _sync(self):
        """Create cards for any existing agents."""
        for row in self._mgr.model._rows:
            self._ensure_card(row.wf_id, row.name)
            card = self._cards.get(row.wf_id)
            if card:
                card.set_status(row.status)
                card._started = row.started_at or time.time()
        self._relayout()

    def _ensure_card(self, wf_id, name=''):
        if wf_id in self._cards:
            return self._cards[wf_id]
        card = AgentCard(wf_id, name or wf_id, self._mgr)
        card.stop_requested.connect(self._on_stop)
        card.input_submitted.connect(self._on_input)
        self._cards[wf_id] = card
        self._relayout()
        return card

    def _relayout(self):
        """Reflow cards into a 1- or 2-column grid with minimal widget moves.

        Only cards whose target position differs from their current position
        are touched, so existing cards never flicker when a new one is added.
        """
        cards = list(self._cards.values())
        target_cols = 2 if len(cards) > 1 else 1
        desired = {card: (i // target_cols, i % target_cols) for i, card in enumerate(cards)}

        # Remove cards that are displaced (gone from _cards or need to move)
        for card, old_pos in list(self._card_positions.items()):
            if card not in desired or desired[card] != old_pos:
                self._grid_layout.removeWidget(card)
                del self._card_positions[card]

        # Add / place cards at their target positions
        for card, pos in desired.items():
            if self._card_positions.get(card) != pos:
                self._grid_layout.addWidget(card, pos[0], pos[1])
                card.show()
                self._card_positions[card] = pos

        self._cols = target_cols

        # Empty-state label
        if cards:
            if self._empty_in_grid:
                self._grid_layout.removeWidget(self._empty)
                self._empty_in_grid = False
            self._empty.hide()
        else:
            self._empty.show()
            if not self._empty_in_grid:
                self._grid_layout.addWidget(self._empty, 0, 0, 1, 2, Qt.AlignCenter)
                self._empty_in_grid = True

        self._agent_count.setText(f'{len(cards)} agent{"s" if len(cards) != 1 else ""}')

    # ── Event handlers (main thread via manager signals) ─────────────────

    @Slot(str, dict)
    def _on_event(self, wf_id, event):
        ev = event.get('event', '')

        if ev == 'started':
            name = event.get('name', wf_id)
            card = self._ensure_card(wf_id, name)
            card.set_status('running')
            card._started = time.time()
            return

        card = self._cards.get(wf_id)
        if not card:
            return

        if ev == 'stdout':
            card.append_output(event.get('line', ''))
        elif ev == 'stderr':
            card.append_output(f'[stderr] {event.get("line", "")}')
        elif ev == 'prompt':
            card.show_prompt(
                event.get('text', ''), event.get('prompt_id', ''))
        elif ev == 'workflow':
            data = event.get('data', {})
            t = data.get('type', '')
            row = self._mgr.model.info_for(wf_id)
            if t == 'step.start':
                card.on_step(data.get('step', ''))
                card.set_status('running')
                card.append_output(f'\n── {data.get("step", "")} ──')
            elif t == 'action.start':
                action_str = f"{data.get('action_type', '')}:{data.get('id', '')}"
                card.on_action(action_str)
                card.append_output(f'  ▸ {data.get("action_type", "")}  →  {data.get("id", "")}')
            elif t == 'action.complete' and data.get('action_type') == 'scramda2':
                card.on_action('')
                card.append_output(data.get('data') or '')
            elif t == 'action.complete':
                card.on_action('')
                ms = data.get('duration_ms', '')
                card.append_output(f'    done  {ms}ms' if ms else '    done')
            elif t in ('action.error', 'run.error'):
                card.append_output(f'  !! {data.get("message", "")}')
            elif t == 'action.output':
                # File contents, command output and model prompts used to
                # arrive as log events and were drawn by the branch below.
                card.append_output(payload_lines(data))
            elif t == 'action.skipped':
                card.append_output(f'  ▸ skipped  {data.get("id", "")}  '
                                   f'({skipped_reason(data)})')
            elif t == 'log':
                card.append_output(f'  {data.get("message", "")}')
            elif t == 'loop.iteration':
                if row:
                    card.on_iteration(row.iterations)
                card.append_output(f'    loop iter {data.get("iteration")}')
            if row:
                card.on_event_count(row.events_received)

    @Slot(str)
    def _on_finished(self, wf_id):
        card = self._cards.get(wf_id)
        if not card:
            return
        row = self._mgr.model.info_for(wf_id)
        status = row.status if row else 'done'
        card.set_status(status)
        card.hide_prompt()
        card.append_output('\n✓  process exited')

    # ── Controls ─────────────────────────────────────────────────────────

    def _on_stop(self, wf_id):
        self._mgr.stop_daemon(wf_id)
        card = self._cards.get(wf_id)
        if card:
            card.set_status('stopped')
            card.append_output('\n■  stopped')

    def _on_input(self, wf_id, text):
        self._mgr._on_input(wf_id, text)

    def _launch_agent(self):
        # Opens on the writable workflow folder — the workflows a person has.
        # This walked up from __file__ to clay's own checkout, which is only
        # the right directory when clay is run from source.
        from ..lib import paths as _paths
        path, _ = QFileDialog.getOpenFileName(
            self, 'Select workflow to launch', _paths.workflow_folder(),
            'JSON files (*.json)',
        )
        if path:
            self._mgr.start_daemon(path, auto=True, daemon_mode=True)

    def _stop_all(self):
        for wf_id, card in list(self._cards.items()):
            if card._status in ('running', 'starting'):
                self._mgr.stop_daemon(wf_id)
                card.set_status('stopped')
                card.append_output('\n■  stopped')

    def _clear_finished(self):
        to_remove = [wf_id for wf_id, card in self._cards.items()
                     if card._status in ('done', 'error', 'stopped')]
        for wf_id in to_remove:
            card = self._cards.pop(wf_id)
            self._card_positions.pop(card, None)
            card.setParent(None)
            card.deleteLater()
        self._mgr.cleanup_finished()
        self._relayout()

    def _tick_runtimes(self):
        for card in self._cards.values():
            card.update_runtime()


# ── Stylesheet ───────────────────────────────────────────────────────────────

_DASH_STYLE = """
QWidget {
    background: #0a0f16;
    color: #8ab4cc;
    font-family: Menlo, monospace;
    font-size: 11px;
}

/* Toolbar */
#dashToolbar {
    background: #0c1420;
    border-bottom: 1px solid #1a2738;
}
#launchBtn {
    background: #0a2a1a; color: #00d4aa; border: 1px solid #1a3a2a;
    padding: 4px 14px; border-radius: 3px; font-family: Menlo; font-size: 11px;
    font-weight: bold;
}
#launchBtn:hover { background: #0f3a24; border-color: #00d4aa; }
#stopAllBtn {
    background: #1a0a0a; color: #e74c3c; border: 1px solid #3a1a1a;
    padding: 4px 14px; border-radius: 3px; font-family: Menlo; font-size: 11px;
}
#stopAllBtn:hover { background: #2a1010; border-color: #e74c3c; }
#clearBtn {
    background: #141e2b; color: #4a7fa5; border: 1px solid #1e2a3a;
    padding: 4px 14px; border-radius: 3px; font-family: Menlo; font-size: 11px;
}
#clearBtn:hover { background: #1e2a3a; }

/* Scroll area */
#cardScroll {
    background: #0a0f16;
    border: none;
}

/* Agent cards */
#agentCard {
    background: #0c1420;
    border: 1px solid #1a2738;
    border-radius: 4px;
}
#cardHeader {
    background: #0e1825;
    border-bottom: 1px solid #1a2738;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
#cardStats {
    background: #0b1018;
    border-bottom: 1px solid #111a24;
}
#cardTerminal {
    background: #060a10;
    color: #5a9ab5;
    border: none;
    border-left: 2px solid #0e1825;
    selection-background-color: #1e3a52;
}
#cardInput {
    background: #0b1018;
    border-top: 1px solid #1a2738;
}
#cardInputField {
    background: #0e1520;
    color: #aed6f1;
    border: 1px solid #1e2a3a;
    padding: 3px 8px;
    font-family: Menlo;
    font-size: 11px;
    border-radius: 2px;
}
#cardInputField:focus {
    border-color: #00d4aa;
}

/* Scrollbar */
QScrollBar:vertical {
    background: #0a0f16; width: 8px; border: none;
}
QScrollBar::handle:vertical {
    background: #1a2738; border-radius: 4px; min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #2e4a63; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
"""
