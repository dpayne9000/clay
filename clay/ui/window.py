"""PySide6/Qt desktop UI; every workflow executes through clayd."""
import json
import os
import time
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTabWidget, QDockWidget, QToolBar, QFileDialog, QStatusBar,
    QLabel, QInputDialog, QMessageBox, QToolButton, QMenu,
    QStackedWidget,
)
from PySide6.QtCore import Qt, QSize, QSettings
from PySide6.QtGui import QAction, QKeySequence, QFont, QIcon

from ..run import events
from .graph import GraphScene, GraphView, ActionNode
from .editor import JsonEditor
from .panels import InspectorPanel, LogPanel, FileBrowser, MemoryPanel
from .palette import PalettePanel
from .manager import WorkflowManager, ProcessPanel
from .dashboard import ProcessDashboard


from ..lib import config
from ..lib import paths as _paths

#: The writable workflow folder. Via config so $CLAY_HOME is honoured — the
#: hardcoded ~/.clay meant the UI and the CLI disagreed about where a user's
#: workflows live whenever CLAY_HOME was set.
_USER_WF_DIR = _paths.workflow_folder()


class WorkflowWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('clay — Qt Desktop')
        self.resize(1600, 900)
        self.setStyleSheet("""
            QMainWindow { background: #0d1520; }
            QMainWindow::separator { background: #1e2a3a; width: 2px; height: 2px; }
            QTabWidget::pane { border: 1px solid #1e2a3a; background: #0d1520; }
            QTabBar::tab {
                background: #141e2b; color: #4a7fa5; border: 1px solid #1e2a3a;
                padding: 5px 14px; margin-right: 1px;
                font-family: Menlo; font-size: 11px;
            }
            QTabBar::tab:selected { background: #1e2a3a; color: #aed6f1; border-bottom: 2px solid #00d4aa; }
            QTabBar::tab:hover { background: #1e2a3a; }
            QDockWidget { color: #8ab4cc; font-family: Menlo; font-size: 11px; }
            QDockWidget::title {
                background: #141e2b; padding: 4px 8px;
                border-bottom: 1px solid #2e4a63;
            }
            QToolBar {
                background: #0e1825; border-bottom: 1px solid #1e2a3a;
                spacing: 4px; padding: 2px 4px;
            }
            QToolButton {
                background: transparent; color: #8ab4cc; border: none;
                padding: 4px 8px; border-radius: 3px;
                font-family: Menlo; font-size: 11px;
            }
            QToolButton:hover { background: #1e2a3a; }
            QToolButton:pressed { background: #2e4a63; }
        """)

        self._open_files = {}          # tab_index → filepath
        self._tab_scenes = {}          # tab_index → (scene, view, data)
        self._current_wf_id = None
        self._active_step = ''

        # Core paths. The packaged workflows are the fallback behind the user's
        # own, not "the project's" — walking up from __file__ found them only
        # while clay was run from its own checkout.
        self._project_wf_dir = config.data_path('workflows')
        self._memory_root = config.user_path('memory')
        os.makedirs(_USER_WF_DIR, exist_ok=True)

        self._mgr = WorkflowManager()

        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_central()
        self._build_docks()
        self._build_status_bar()
        self._wire_signals()

        self._restore_state()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _build_actions(self):
        self.act_new       = QAction('New workflow', self)
        self.act_new.setShortcut(QKeySequence.New)

        self.act_open      = QAction('Open…', self)
        self.act_open.setShortcut(QKeySequence.Open)

        self.act_save      = QAction('Save', self)
        self.act_save.setShortcut(QKeySequence.Save)

        self.act_save_as   = QAction('Save as…', self)
        self.act_save_as.setShortcut(QKeySequence('Ctrl+Shift+S'))

        self.act_run       = QAction('▶  Run interactive (clayd)', self)
        self.act_run.setShortcut(QKeySequence('Ctrl+R'))

        self.act_run_auto  = QAction('▶  Run auto (clayd)', self)
        self.act_run_auto.setShortcut(QKeySequence('Ctrl+Shift+R'))

        self.act_daemon    = QAction('◈  Run unattended (clayd)', self)
        self.act_daemon.setShortcut(QKeySequence('Ctrl+D'))

        self.act_stop      = QAction('■  Stop', self)
        self.act_stop.setEnabled(False)

        self.act_add_step  = QAction('+ Step', self)
        self.act_delete    = QAction('Delete', self)
        self.act_delete.setShortcut(QKeySequence.Delete)

        self.act_fit       = QAction('Fit', self)

        self.act_dashboard = QAction('◉  Dashboard', self)
        self.act_dashboard.setShortcut(QKeySequence('Ctrl+Shift+D'))
        self.act_dashboard.setCheckable(True)

    # ── Menus ─────────────────────────────────────────────────────────────────

    def _build_menus(self):
        mb = self.menuBar()
        mb.setStyleSheet("""
            QMenuBar { background: #0e1825; color: #8ab4cc; font-family: Menlo; font-size: 11px; }
            QMenuBar::item:selected { background: #1e2a3a; }
            QMenu { background: #141e2b; color: #8ab4cc; border: 1px solid #2e4a63; font-family: Menlo; }
            QMenu::item:selected { background: #1e3a52; }
            QMenu::separator { background: #2e4a63; height: 1px; }
        """)

        file_m = mb.addMenu('File')
        file_m.addAction(self.act_new)
        file_m.addAction(self.act_open)
        file_m.addSeparator()
        file_m.addAction(self.act_save)
        file_m.addAction(self.act_save_as)

        run_m = mb.addMenu('Run')
        run_m.addAction(self.act_run)
        run_m.addAction(self.act_run_auto)
        run_m.addAction(self.act_daemon)
        run_m.addSeparator()
        run_m.addAction(self.act_stop)

        edit_m = mb.addMenu('Edit')
        edit_m.addAction(self.act_add_step)
        edit_m.addAction(self.act_delete)

        view_m = mb.addMenu('View')
        view_m.addAction(self.act_dashboard)
        view_m.addSeparator()
        view_m.addAction(self.act_fit)
        view_m.addSeparator()
        # Dock toggles added after docks are created
        self._view_menu = view_m

    # ── Toolbars ──────────────────────────────────────────────────────────────

    def _build_toolbars(self):
        tb_file = QToolBar('File')
        tb_file.setObjectName('FileToolbar')
        tb_file.setIconSize(QSize(16, 16))
        tb_file.addAction(self.act_new)
        tb_file.addAction(self.act_open)
        tb_file.addAction(self.act_save)
        self.addToolBar(Qt.TopToolBarArea, tb_file)

        tb_run = QToolBar('Run')
        tb_run.setObjectName('RunToolbar')
        tb_run.addAction(self.act_run)
        tb_run.addAction(self.act_run_auto)
        tb_run.addAction(self.act_daemon)
        tb_run.addSeparator()
        tb_run.addAction(self.act_stop)
        tb_run.addSeparator()
        tb_run.addAction(self.act_dashboard)
        self.addToolBar(Qt.TopToolBarArea, tb_run)

        tb_edit = QToolBar('Edit')
        tb_edit.setObjectName('EditToolbar')
        tb_edit.addAction(self.act_add_step)
        tb_edit.addAction(self.act_delete)
        tb_edit.addSeparator()
        tb_edit.addAction(self.act_fit)
        self.addToolBar(Qt.TopToolBarArea, tb_edit)

    # ── Central: stacked widget (editor view / dashboard view) ────────────────

    def _build_central(self):
        self._stack = QStackedWidget()

        # ── Page 0: Editor view ──────────────────────────────────────────
        editor_page = QWidget()
        layout = QVBoxLayout(editor_page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top: workflow editor tabs
        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        # Bottom: output tabs (log + processes)
        self._output_tabs = QTabWidget()
        self._output_tabs.setDocumentMode(True)
        self._output_tabs.setMaximumHeight(260)

        self._log_panel = LogPanel()
        self._output_tabs.addTab(self._log_panel, 'Output')

        self._process_panel = ProcessPanel(self._mgr)
        self._process_panel.open_workflow_requested.connect(self.load_workflow)
        self._output_tabs.addTab(self._process_panel, 'Processes')

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._tabs)
        splitter.addWidget(self._output_tabs)
        splitter.setSizes([640, 220])
        layout.addWidget(splitter)

        self._stack.addWidget(editor_page)   # index 0

        # ── Page 1: Dashboard view ───────────────────────────────────────
        self._dashboard = ProcessDashboard(self._mgr)
        self._dashboard.open_workflow_requested.connect(self.load_workflow)
        self._stack.addWidget(self._dashboard)  # index 1

        self.setCentralWidget(self._stack)

    # ── Docks ─────────────────────────────────────────────────────────────────

    def _build_docks(self):
        # Left: file browser
        self._file_browser = FileBrowser()
        self._file_browser.set_root(self._project_wf_dir)
        self._file_browser.file_selected.connect(self.load_workflow)
        dock_files = QDockWidget('Workflows', self)
        dock_files.setObjectName('WorkflowsDock')
        dock_files.setWidget(self._file_browser)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_files)

        # Left: action palette
        self._palette = PalettePanel()
        dock_palette = QDockWidget('Actions', self)
        dock_palette.setObjectName('ActionsDock')
        dock_palette.setWidget(self._palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock_palette)
        self.tabifyDockWidget(dock_files, dock_palette)
        dock_files.raise_()

        # Right: inspector
        self._inspector = InspectorPanel()
        dock_inspector = QDockWidget('Inspector', self)
        dock_inspector.setObjectName('InspectorDock')
        dock_inspector.setWidget(self._inspector)
        self.addDockWidget(Qt.RightDockWidgetArea, dock_inspector)

        # Right: memory
        self._memory = MemoryPanel(self._memory_root)
        dock_memory = QDockWidget('Memory', self)
        dock_memory.setObjectName('MemoryDock')
        dock_memory.setWidget(self._memory)
        self.addDockWidget(Qt.RightDockWidgetArea, dock_memory)
        self.tabifyDockWidget(dock_inspector, dock_memory)
        dock_inspector.raise_()

        # Add dock toggle actions to View menu
        for dock in [dock_files, dock_palette, dock_inspector, dock_memory]:
            self._view_menu.addAction(dock.toggleViewAction())

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_status_bar(self):
        self._status = QLabel('Ready')
        self._status.setStyleSheet('color: #4a7fa5; font-family: Menlo; font-size: 10px; padding: 2px 8px;')
        sb = self.statusBar()
        sb.addWidget(self._status)
        sb.setStyleSheet('background: #0a1018; border-top: 1px solid #1e2a3a;')

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _wire_signals(self):
        self.act_new.triggered.connect(self._new_workflow)
        self.act_open.triggered.connect(self._open_file)
        self.act_save.triggered.connect(self._save)
        self.act_save_as.triggered.connect(self._save_as)
        self.act_run.triggered.connect(lambda: self._run_current(auto=False))
        self.act_run_auto.triggered.connect(lambda: self._run_current(auto=True))
        self.act_daemon.triggered.connect(self._run_daemon)
        self.act_stop.triggered.connect(self._stop_current)
        self.act_add_step.triggered.connect(self._add_step)
        self.act_delete.triggered.connect(self._delete_selected)
        self.act_fit.triggered.connect(self._fit_view)
        self.act_dashboard.triggered.connect(self._toggle_dashboard)
        # Connected once, not per run: a connection made in _run_current would
        # be remade on every run and the same answer delivered n times.
        self._log_panel.input_submitted.connect(self._on_input_submitted)
        self._mgr.daemon_event.connect(self._on_daemon_event)
        self._mgr.daemon_finished.connect(self._on_daemon_finished)

    # ── Dashboard toggle ─────────────────────────────────────────────────────

    def _toggle_dashboard(self, checked):
        if checked:
            self._stack.setCurrentIndex(1)
            self._status.setText('Process Dashboard')
        else:
            self._stack.setCurrentIndex(0)
            fp = self._current_filepath()
            self._status.setText(fp or 'Editor')

    # ── Tab management ────────────────────────────────────────────────────────

    def _make_tab(self, data, filepath=None):
        """Create a new tab with graph + editor for a workflow."""
        scene = GraphScene()
        scene.node_selected.connect(self._on_node_selected)
        view = GraphView(scene)
        view.drop_node.connect(lambda t, i, p: self._on_drop_node(scene, t, i, p))

        editor = JsonEditor()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(view)
        splitter.addWidget(editor)
        splitter.setSizes([700, 300])

        if data:
            scene.load_workflow(data)
            editor.set_json(data)

        # Sync: editor changes → reload graph
        def _on_editor_valid(d):
            scene.load_workflow(d)
        editor.valid_json.connect(_on_editor_valid)

        # Sync: graph changes → update editor
        def _on_graph_changed():
            d = scene.export_workflow()
            editor.set_json(d)
        scene.scene_modified.connect(_on_graph_changed)

        name = os.path.basename(filepath) if filepath else 'untitled.json'
        idx = self._tabs.addTab(splitter, name)
        self._tabs.setCurrentIndex(idx)
        self._open_files[idx] = filepath
        self._tab_scenes[idx] = (scene, view, data)
        return idx

    def _close_tab(self, idx):
        self._open_files.pop(idx, None)
        self._tab_scenes.pop(idx, None)
        self._tabs.removeTab(idx)
        # Re-index remaining tabs
        new_files = {}
        new_scenes = {}
        for i in range(self._tabs.count()):
            for old_idx, fp in list(self._open_files.items()):
                w = self._tabs.widget(i)
                # Just rebuild from scratch on close
                pass
        self._open_files = {}
        self._tab_scenes = {}
        for i in range(self._tabs.count()):
            # Lookup by widget identity is more reliable
            pass

    def _on_tab_changed(self, idx):
        info = self._tab_scenes.get(idx)
        if info:
            _, view, _ = info
            self._status.setText(self._open_files.get(idx, 'untitled'))

    def _current_scene(self):
        idx = self._tabs.currentIndex()
        info = self._tab_scenes.get(idx)
        return info[0] if info else None

    def _current_view(self):
        idx = self._tabs.currentIndex()
        info = self._tab_scenes.get(idx)
        return info[1] if info else None

    def _current_filepath(self):
        return self._open_files.get(self._tabs.currentIndex())

    def _current_editor(self):
        w = self._tabs.currentWidget()
        if w:
            splitter = w
            if splitter.count() >= 2:
                editor = splitter.widget(1)
                if isinstance(editor, JsonEditor):
                    return editor
        return None

    # ── File operations ───────────────────────────────────────────────────────

    def _new_workflow(self):
        data = {
            'workflow': {'steps': []},
            'actionSets': {},
        }
        self._make_tab(data)
        self._status.setText('New workflow')

    def _open_file(self):
        start_dir = self._project_wf_dir
        path, _ = QFileDialog.getOpenFileName(
            self, 'Open workflow', start_dir, 'JSON files (*.json)',
        )
        if path:
            self.load_workflow(path)

    def load_workflow(self, path):
        # Check if already open
        for idx, fp in self._open_files.items():
            if fp == path:
                self._tabs.setCurrentIndex(idx)
                return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            self._status.setText(f'Error: {e}')
            return
        self._make_tab(data, filepath=path)
        self._status.setText(path)

    def _save(self):
        filepath = self._current_filepath()
        if filepath:
            self._write_file(filepath)
        else:
            self._save_as()

    def _save_as(self):
        start_dir = _USER_WF_DIR
        path, _ = QFileDialog.getSaveFileName(
            self, 'Save workflow', start_dir, 'JSON files (*.json)',
        )
        if path:
            if not path.endswith('.json'):
                path += '.json'
            self._write_file(path)
            idx = self._tabs.currentIndex()
            self._open_files[idx] = path
            self._tabs.setTabText(idx, os.path.basename(path))

    def _write_file(self, path):
        editor = self._current_editor()
        if not editor:
            return
        data = editor.get_json()
        if data is None:
            self._status.setText('Cannot save — invalid JSON')
            return
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=4)
        self._status.setText(f'Saved → {path}')

    # ── Run ───────────────────────────────────────────────────────────────────

    def _run_current(self, auto=False):
        self._start_clayd(auto=auto, daemon_mode=False)

    def _run_daemon(self):
        self._start_clayd(auto=True, daemon_mode=True)

    def _start_clayd(self, *, auto, daemon_mode):
        """Launch the current workflow in its own clayd-managed subprocess."""
        filepath = self._current_filepath()
        if not filepath:
            self._status.setText('Save the workflow first')
            return
        wf_id, err = self._mgr.start_daemon(
            filepath, auto=auto, daemon_mode=daemon_mode)
        if wf_id:
            mode = ('unattended' if daemon_mode else
                    ('auto' if auto else 'interactive'))
            self._current_wf_id = wf_id
            self._status.setText(f'clayd {mode} run started: {wf_id}')
            self._log_panel.append(
                f'\n◈  clayd {wf_id} [{mode}]: {os.path.basename(filepath)}')
            self.act_stop.setEnabled(True)
            self._stack.setCurrentIndex(1)
            self.act_dashboard.setChecked(True)
        else:
            self._status.setText(f'clayd launch failed: {err}')
            self._log_panel.append(f'✕  clayd launch failed: {err}')

    def _stop_current(self):
        wf_id = self._current_wf_id
        if not wf_id:
            return
        self.act_stop.setEnabled(False)
        self._log_panel.append(f'■  stopping clayd run {wf_id}…')
        self._mgr.stop_daemon(wf_id)

    def _on_input_submitted(self, prompt_id, text):
        """Hand local log-panel input to the selected clayd workflow."""
        wf_id = self._current_wf_id
        if wf_id is None or not self._mgr.send_input(wf_id, text):
            self._log_panel.append('✕  nothing is waiting for that answer')

    def _on_daemon_event(self, wf_id, envelope):
        """Mirror the selected clayd run into the editor graph/log panel."""
        if wf_id != self._current_wf_id:
            return
        if envelope.get('event') == 'workflow':
            self._on_run_event(envelope.get('data', {}))
        elif envelope.get('event') == 'prompt':
            self._on_run_event({
                'type': events.INPUT_REQUEST,
                'id': envelope.get('prompt_id', ''),
                'prompt': envelope.get('text', ''),
            })

    def _on_run_event(self, event):
        self._log_panel.on_event(event)

        # Animate graph nodes
        scene = self._current_scene()
        if not scene:
            return
        t = event.get('type', '')
        if t == events.STEP_START:
            # There is no step.complete event — the branch that waited for one
            # never fired, so every step stayed 'active' for the whole run. A
            # step is finished when the next one starts, or when the run ends.
            self._finish_step(scene)
            self._active_step = event.get('step', '')
            node = scene.step_node(self._active_step)
            if node:
                node.set_state('active')
        elif t == events.ACTION_START:
            self._set_action_state(scene, event, 'active')
        elif t == events.ACTION_DONE:
            self._set_action_state(scene, event, 'done')
        elif t == events.ACTION_ERROR:
            self._set_action_state(scene, event, 'error')
        elif t == events.ACTION_SKIPPED:
            self._set_action_state(scene, event, 'skipped')
        elif t == events.RUN_COMPLETE:
            self._finish_step(scene)
        elif t == events.RUN_ERROR:
            self._finish_step(scene, 'error')
        elif t == events.RUN_CANCELLED:
            self._finish_step(scene, 'idle')

    def _set_action_state(self, scene, event, state):
        """Colour the action node the event names, if it is on this canvas.

        Action ids are only unique within a step, so the lookup is keyed on the
        step that is currently running.
        """
        node = scene.action_node_by_id(self._active_step, event.get('id', ''))
        if node:
            node.set_state(state)

    def _finish_step(self, scene, state='done'):
        if not self._active_step:
            return
        node = scene.step_node(self._active_step)
        if node:
            node.set_state(state)
        self._active_step = ''

    def _on_daemon_finished(self, wf_id):
        """Finish only the selected run; other clayd workflows stay active."""
        if wf_id != self._current_wf_id:
            return
        self.act_stop.setEnabled(False)
        self._current_wf_id = None
        self._log_panel.clear_prompt()
        self._log_panel.append(f'✓  clayd run {wf_id} finished\n')
        self._status.setText('clayd run complete')

    # ── Node editing ──────────────────────────────────────────────────────────

    def _add_step(self):
        name, ok = QInputDialog.getText(self, 'Add step', 'Step name:')
        if ok and name:
            scene = self._current_scene()
            if scene:
                scene.add_step_node(name)

    def _delete_selected(self):
        scene = self._current_scene()
        if scene:
            scene.delete_selected()

    def _fit_view(self):
        view = self._current_view()
        scene = self._current_scene()
        if view and scene:
            view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)

    def _on_node_selected(self, node):
        self._inspector.show_node(node)

    def _on_drop_node(self, scene, action_type, action_id, pos):
        """Handle drop from palette onto canvas."""
        if not action_id:
            action_id, ok = QInputDialog.getText(self, 'Action ID',
                                                  f'ID for {action_type}:')
            if not ok:
                return
        scene.add_action_node(action_type, action_id, pos=pos)

    # ── Layout persistence ────────────────────────────────────────────────────

    def _restore_state(self):
        s = QSettings('clay', 'ui')
        geo = s.value('geometry')
        if geo:
            self.restoreGeometry(geo)
        state = s.value('windowState')
        if state:
            self.restoreState(state, 1)

    def closeEvent(self, event):
        self._mgr.stop_all()
        s = QSettings('clay', 'ui')
        s.setValue('geometry', self.saveGeometry())
        s.setValue('windowState', self.saveState(1))
        super().closeEvent(event)
