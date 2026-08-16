"""Node editor — visual workflow designer with drag-and-drop, bezier connections."""
import json
import math
from PySide6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsItem, QGraphicsObject,
    QGraphicsRectItem, QGraphicsTextItem, QGraphicsPathItem,
    QGraphicsEllipseItem, QGraphicsProxyWidget, QMenu,
)
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, Property, QMimeData
from PySide6.QtGui import (
    QColor, QPen, QBrush, QFont, QPainter, QPainterPath, QDrag, QCursor,
)


# ── Palette ───────────────────────────────────────────────────────────────────

_C = {
    'scene_bg':      QColor('#0d1520'),
    'grid_major':    QColor('#142030'),
    'grid_minor':    QColor('#0f1a28'),
    'step_bg':       QColor('#1a2a3e'),
    'step_border':   QColor('#4a7fa5'),
    'step_text':     QColor('#aed6f1'),
    'action_bg':     QColor('#141e2b'),
    'action_border': QColor('#2e4a63'),
    'action_text':   QColor('#8ab4cc'),
    'port':          QColor('#4a7fa5'),
    'port_hover':    QColor('#00d4aa'),
    'edge':          QColor('#2e4a63'),
    'edge_active':   QColor('#00d4aa'),
    'active':        QColor('#00d4aa'),
    'done':          QColor('#2ecc71'),
    'error':         QColor('#e74c3c'),
    # Use a dim border to distinguish skipped nodes from nodes not yet reached.
    'skipped':       QColor('#3c4a58'),
    'selected':      QColor('#f39c12'),
}

_NODE_W      = 220
_STEP_H      = 36
_ACTION_H    = 30
_PORT_R      = 5
_GRID_SIZE   = 20

# Default fields for action nodes created through the palette.
_ACTION_TEMPLATES = {
    'scramda2':       {'type': 'scramda2',       'id': '', 'prompt': '', 'model': None, 'modelProfile': None},
    'humanDecision':  {'type': 'humanDecision',  'id': '', 'prompt': ''},
    'loop':           {'type': 'loop',            'id': '', 'file': '', 'iterations': 10},
    'workflow':       {'type': 'workflow',        'id': '', 'file': ''},
    'shell':          {'type': 'shell',           'id': '', 'command': ''},
    'runCode':        {'type': 'runCode',         'id': '', 'language': 'python', 'code': ''},
    'writeFile':      {'type': 'writeFile',       'id': '', 'file': '', 'content': ''},
    'API':            {'type': 'API',             'id': '', 'url': '', 'method': 'GET'},
}


# ── Port ──────────────────────────────────────────────────────────────────────

class Port(QGraphicsEllipseItem):
    """Connection endpoint on a node. port_type = 'in' | 'out'."""

    def __init__(self, parent_node, port_type, index=0):
        r = _PORT_R
        super().__init__(-r, -r, r * 2, r * 2, parent_node)
        self.port_type = port_type
        self.index = index
        self.edges = []
        self.setBrush(QBrush(_C['port']))
        self.setPen(QPen(Qt.NoPen))
        self.setAcceptHoverEvents(True)
        self.setZValue(2)

    def center_scene(self):
        return self.mapToScene(self.boundingRect().center())

    def hoverEnterEvent(self, ev):
        self.setBrush(QBrush(_C['port_hover']))
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev):
        self.setBrush(QBrush(_C['port']))
        super().hoverLeaveEvent(ev)


# ── Edge ──────────────────────────────────────────────────────────────────────

class Edge(QGraphicsPathItem):
    """Bezier connection between two ports."""

    def __init__(self, source_port, dest_port=None):
        super().__init__()
        self.source = source_port
        self.dest = dest_port
        self.drag_end = QPointF(0, 0)
        self.setPen(QPen(_C['edge'], 2))
        self.setZValue(-1)
        if source_port:
            source_port.edges.append(self)
        if dest_port:
            dest_port.edges.append(self)
        self.update_path()

    def update_path(self):
        src = self.source.center_scene() if self.source else self.drag_end
        dst = self.dest.center_scene() if self.dest else self.drag_end
        path = QPainterPath()
        path.moveTo(src)
        dy = abs(dst.y() - src.y()) * 0.5
        dx = max(dy, 40)
        path.cubicTo(src.x(), src.y() + dx,
                     dst.x(), dst.y() - dx,
                     dst.x(), dst.y())
        self.setPath(path)

    def set_active(self, on=True):
        self.setPen(QPen(_C['edge_active'] if on else _C['edge'], 2))

    def detach(self):
        if self.source and self in self.source.edges:
            self.source.edges.remove(self)
        if self.dest and self in self.dest.edges:
            self.dest.edges.remove(self)


# ── Base node ─────────────────────────────────────────────────────────────────

class BaseNode(QGraphicsObject):
    """Movable, selectable node with input/output ports."""

    position_changed = Signal()

    def __init__(self, label, w, h, bg, border, text_color):
        super().__init__()
        self._w, self._h = w, h
        self._bg, self._border, self._text_color = bg, border, text_color
        self._label = label
        self._state = 'idle'
        self.meta = {}

        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

        self.in_port = None
        self.out_port = None

    def _add_ports(self):
        self.in_port = Port(self, 'in')
        self.in_port.setPos(self._w / 2, 0)
        self.out_port = Port(self, 'out')
        self.out_port.setPos(self._w / 2, self._h)

    def boundingRect(self):
        return QRectF(0, 0, self._w, self._h)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.Antialiasing)
        border = self._border
        if self._state == 'active':
            border = _C['active']
        elif self._state == 'done':
            border = _C['done']
        elif self._state == 'error':
            border = _C['error']
        elif self._state == 'skipped':
            border = _C['skipped']
        if self.isSelected():
            border = _C['selected']

        painter.setBrush(QBrush(self._bg))
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(self.boundingRect(), 4, 4)

        painter.setPen(QPen(self._text_color))
        font = QFont('Menlo', 9)
        if isinstance(self, StepNode):
            font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.boundingRect().adjusted(10, 0, -10, 0),
                         Qt.AlignVCenter | Qt.AlignLeft, self._label)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.position_changed.emit()
            for port in [self.in_port, self.out_port]:
                if port:
                    for edge in port.edges:
                        edge.update_path()
        return super().itemChange(change, value)

    def set_state(self, state):
        self._state = state
        self.update()

    def label(self):
        return self._label


class StepNode(BaseNode):
    def __init__(self, name):
        super().__init__(name, _NODE_W, _STEP_H,
                         _C['step_bg'], _C['step_border'], _C['step_text'])
        self._add_ports()


class ActionNode(BaseNode):
    def __init__(self, action_type, action_id=''):
        label = f'{action_type}  →  {action_id}' if action_id else action_type
        super().__init__(label, _NODE_W, _ACTION_H,
                         _C['action_bg'], _C['action_border'], _C['action_text'])
        self._add_ports()
        self.action_type = action_type
        self.action_id = action_id


# ── Scene ─────────────────────────────────────────────────────────────────────

class GraphScene(QGraphicsScene):
    node_selected = Signal(object)
    scene_modified = Signal()

    def __init__(self):
        super().__init__()
        self.setBackgroundBrush(QBrush(_C['scene_bg']))
        self._step_nodes = {}        # step_name → StepNode
        self._action_nodes = {}      # (step, idx) → ActionNode
        self._edges = []
        self._drag_edge = None
        self._drag_source_port = None

    # ── Load existing workflow ────────────────────────────────────────────────

    def load_workflow(self, data):
        self.clear()
        self._step_nodes.clear()
        self._action_nodes.clear()
        self._edges.clear()

        steps = data.get('workflow', {}).get('steps', [])
        action_sets = data.get('actionSets', {})

        x = 40
        for step_name in steps:
            y = 40
            sn = StepNode(step_name)
            sn.setPos(x, y)
            self.addItem(sn)
            self._step_nodes[step_name] = sn
            y += _STEP_H + 16

            prev_node = sn
            actions = action_sets.get(step_name, [])
            for i, action in enumerate(actions):
                an = ActionNode(action.get('type', '?'), action.get('id', ''))
                an.setPos(x, y)
                an.meta['config'] = action
                self.addItem(an)
                self._action_nodes[(step_name, i)] = an

                edge = Edge(prev_node.out_port, an.in_port)
                self.addItem(edge)
                self._edges.append(edge)
                prev_node = an
                y += _ACTION_H + 8

            x += _NODE_W + 70

        self.setSceneRect(self.itemsBoundingRect().adjusted(-40, -40, 80, 80))

    # ── Export to workflow JSON ────────────────────────────────────────────────

    def export_workflow(self):
        """Convert the current graph into a workflow JSON dict."""
        # Gather steps in left-to-right order
        sorted_steps = sorted(self._step_nodes.items(),
                              key=lambda kv: kv[1].pos().x())
        steps = [name for name, _ in sorted_steps]
        action_sets = {}
        for name in steps:
            actions = []
            step_actions = sorted(
                ((k, v) for k, v in self._action_nodes.items() if k[0] == name),
                key=lambda kv: kv[1].pos().y(),
            )
            for (_, _idx), node in step_actions:
                cfg = dict(node.meta.get('config', {}))
                if not cfg.get('type'):
                    cfg['type'] = node.action_type
                if not cfg.get('id') and node.action_id:
                    cfg['id'] = node.action_id
                actions.append(cfg)
            action_sets[name] = actions
        return {'workflow': {'steps': steps}, 'actionSets': action_sets}

    # ── Mind-map: add nodes interactively ─────────────────────────────────────

    def add_step_node(self, name, pos=None):
        sn = StepNode(name)
        if pos:
            sn.setPos(pos)
        else:
            # Place to the right of existing steps
            max_x = max((n.pos().x() for n in self._step_nodes.values()), default=-30)
            sn.setPos(max_x + _NODE_W + 70, 40)
        self.addItem(sn)
        self._step_nodes[name] = sn
        self.scene_modified.emit()
        return sn

    def add_action_node(self, action_type, action_id='', step_name=None, pos=None):
        an = ActionNode(action_type, action_id)
        template = dict(_ACTION_TEMPLATES.get(action_type, {'type': action_type, 'id': action_id}))
        if action_id:
            template['id'] = action_id
        an.meta['config'] = template
        if pos:
            an.setPos(pos)
        self.addItem(an)
        if step_name:
            idx = sum(1 for k in self._action_nodes if k[0] == step_name)
            self._action_nodes[(step_name, idx)] = an
        self.scene_modified.emit()
        return an

    def connect_nodes(self, src, dst):
        if src.out_port and dst.in_port:
            edge = Edge(src.out_port, dst.in_port)
            self.addItem(edge)
            self._edges.append(edge)
            self.scene_modified.emit()

    # ── Drag edge (interactive connection creation) ───────────────────────────

    def start_edge_drag(self, port):
        self._drag_source_port = port
        self._drag_edge = Edge(port, None)
        self._drag_edge.drag_end = port.center_scene()
        self.addItem(self._drag_edge)

    def update_edge_drag(self, scene_pos):
        if self._drag_edge:
            self._drag_edge.drag_end = scene_pos
            self._drag_edge.update_path()

    def finish_edge_drag(self, scene_pos):
        if not self._drag_edge:
            return
        # Find target port under cursor
        items = self.items(scene_pos)
        target_port = None
        for item in items:
            if isinstance(item, Port) and item is not self._drag_source_port:
                if item.port_type != self._drag_source_port.port_type:
                    target_port = item
                    break
        if target_port:
            self._drag_edge.dest = target_port
            target_port.edges.append(self._drag_edge)
            self._drag_edge.update_path()
            self._edges.append(self._drag_edge)
            self.scene_modified.emit()
        else:
            self.removeItem(self._drag_edge)
            self._drag_edge.detach()
        self._drag_edge = None
        self._drag_source_port = None

    def cancel_edge_drag(self):
        if self._drag_edge:
            self.removeItem(self._drag_edge)
            self._drag_edge.detach()
            self._drag_edge = None
            self._drag_source_port = None

    # ── Delete selected ───────────────────────────────────────────────────────

    def delete_selected(self):
        for item in self.selectedItems():
            if isinstance(item, BaseNode):
                for port in [item.in_port, item.out_port]:
                    if port:
                        for edge in list(port.edges):
                            edge.detach()
                            if edge in self._edges:
                                self._edges.remove(edge)
                            self.removeItem(edge)
                # Remove from dicts
                self._step_nodes = {k: v for k, v in self._step_nodes.items() if v is not item}
                self._action_nodes = {k: v for k, v in self._action_nodes.items() if v is not item}
                self.removeItem(item)
        self.scene_modified.emit()

    # ── Live execution: node lookups ──────────────────────────────────────────

    def step_node(self, name):
        return self._step_nodes.get(name)

    def action_node_by_id(self, step, action_id):
        for (s, _), node in self._action_nodes.items():
            if s == step and node.action_id == action_id:
                return node
        return None

    # ── Selection ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        item = self.itemAt(event.scenePos(), self.views()[0].transform() if self.views() else __import__('PySide6.QtGui', fromlist=['QTransform']).QTransform())
        if isinstance(item, Port) and event.button() == Qt.LeftButton:
            self.start_edge_drag(item)
            return
        super().mousePressEvent(event)
        sel = self.selectedItems()
        if sel:
            self.node_selected.emit(sel[0])

    def mouseMoveEvent(self, event):
        if self._drag_edge:
            self.update_edge_drag(event.scenePos())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_edge:
            self.finish_edge_drag(event.scenePos())
            return
        super().mouseReleaseEvent(event)

    # ── Grid painting ─────────────────────────────────────────────────────────

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        gs = _GRID_SIZE
        left = int(rect.left()) - (int(rect.left()) % gs)
        top = int(rect.top()) - (int(rect.top()) % gs)

        painter.setPen(QPen(_C['grid_minor'], 0.5))
        x = left
        while x < rect.right():
            painter.drawLine(int(x), int(rect.top()), int(x), int(rect.bottom()))
            x += gs
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))
            y += gs


# ── View ──────────────────────────────────────────────────────────────────────

class GraphView(QGraphicsView):
    drop_node = Signal(str, str, QPointF)   # action_type, action_id, scene_pos

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setAcceptDrops(True)
        self.setStyleSheet('background: #0d1520; border: none;')

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.scene().delete_selected()
        elif event.key() == Qt.Key_Escape:
            self.scene().cancel_edge_drag()
        else:
            super().keyPressEvent(event)

    # ── Drop from palette ─────────────────────────────────────────────────────

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat('application/x-clay-action'):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat('application/x-clay-action'):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat('application/x-clay-action'):
            data = bytes(event.mimeData().data('application/x-clay-action')).decode()
            scene_pos = self.mapToScene(event.position().toPoint())
            self.drop_node.emit(data, '', scene_pos)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
