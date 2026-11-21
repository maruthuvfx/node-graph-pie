"""Blender-style radial menu prototype for the Nuke node graph.

The first version intentionally keeps the action registry separate from the
Qt widget. This lets the menu grow from the prototype into context-aware pies
without hard-coding production actions into the painting code.
"""

from dataclasses import dataclass
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

import studio_pie_create as creation
import studio_pie_customize as customization
from studio_pie_quick_properties import open_panels
import studio_pie_arrange as arrangement
from studio_pie_navigation import Navigation
import studio_pie_selection as selection
import studio_pie_viewer as viewer_tools


_CONTROLLER = None
_ACTIVE_PIE = None
_RECENT_CALLBACK = None
_NAVIGATION = Navigation()


def _node_preferences():
    QtCore, _, _ = _qt()
    return QtCore.QSettings("Studio Nuke", "Node Graph Pie")


def _node_classes(value):
    return list(dict.fromkeys(name for name in re.split(r"[,\s]+", value)
                              if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)))


def _remember_node(nuke, name=None):
    if name is None:
        try:
            node = nuke.thisNode()
            if node is None:
                return
            name = node.Class()
        except ValueError:
            # Some onUserCreate events expose a detached Nuke node wrapper.
            return
    if name in {"Root", "Viewer", "Input", "Output"}:
        return
    settings = _node_preferences()
    recent = _node_classes(settings.value("recent", "", type=str))
    recent = [name] + [item for item in recent if item != name]
    settings.setValue("recent", ",".join(recent[:20]))


def _create_actions(nuke, action):
    settings = _node_preferences()
    favorites = _node_classes(settings.value("favorites", "Grade,Blur,Transform", type=str))
    recent = _node_classes(settings.value("recent", "", type=str))
    visible = favorites + [name for name in recent if name not in favorites]
    _, _, QtWidgets = _qt()

    def pick(title, label, choices, editable=False):
        if not choices:
            return None
        value, accepted = QtWidgets.QInputDialog.getItem(
            QtWidgets.QApplication.activeWindow(), title, label, choices, 0, editable)
        return value.strip() if accepted else None

    def build(recipe, insert=False):
        selected = nuke.selectedNodes()
        source = selected[0] if len(selected) == 1 else None
        edge = None
        if insert:
            if source is None:
                raise ValueError("Select the upstream node of the connection first.")
            edges = {
                "{} → {} [input {}]".format(source.name(), node.name(), index): (node, index)
                for node in nuke.allNodes()
                for index in range(node.inputs()) if node.input(index) == source
            }
            if not edges:
                raise ValueError("The selected node has no downstream connections.")
            label = pick("Insert into Pipe", "Replace this connection:", list(edges))
            if label is None:
                return
            edge = edges[label]
        nodes = creation.create(nuke, recipe, source, edge)
        for node in nodes:
            _remember_node(nuke, node.Class())

    def single(name):
        return [{"class": name, "x": 0, "y": 0}]

    def search(insert=False):
        classes = getattr(nuke, "allNodeClasses", None)
        catalog = sorted(set(classes()) if callable(classes) else set())
        common = ["Read", "Write", "Merge2", "Grade", "Blur", "Transform", "Roto",
                  "Shuffle2", "Premult", "Unpremult", "Dot", "NoOp"]
        choices = list(dict.fromkeys(visible + catalog + common))
        name = pick("Search Nodes", "Search or enter a Nuke node class:", choices, True)
        if name:
            build(single(name), insert=insert)

    def recipes():
        library = creation.recipe_library(settings)
        choices = dict(creation.BUILTINS, **library)
        save, insert, remove = (
            "Save Selection as Recipe…", "Insert Recipe into Pipe…", "Remove Saved Recipe…",
        )
        commands = [save, insert, remove]
        name = pick("Recipes", "Choose a recipe or command:",
                    (commands if library else commands[:2]) + list(choices))
        if name == save:
            recipe = creation.capture(nuke.selectedNodes())
            label, accepted = QtWidgets.QInputDialog.getText(
                QtWidgets.QApplication.activeWindow(), "Save Recipe", "Recipe name:")
            label = label.strip()
            if accepted and label:
                if label in choices or label in commands:
                    raise ValueError("A recipe or command already uses that name.")
                library[label] = recipe
                settings.setValue("recipes", json.dumps(library))
        elif name == insert:
            label = pick("Insert Recipe", "Choose a recipe:", list(choices))
            if label:
                build(choices[label], insert=True)
        elif name == remove:
            label = pick("Remove Saved Recipe", "Choose a personal recipe:", sorted(library))
            if label and nuke.ask("Remove the saved recipe “{}”?".format(label)):
                current = creation.recipe_library(settings)
                if label in current:
                    del current[label]
                    settings.setValue("recipes", json.dumps(current))
        elif name:
            build(choices[name])

    def edit_favorites():
        _, _, QtWidgets = _qt()
        value, accepted = QtWidgets.QInputDialog.getText(
            QtWidgets.QApplication.activeWindow(), "Create Favorites",
            "Up to seven Nuke node classes, in order (comma-separated):",
            text=", ".join(favorites),
        )
        if accepted:
            settings.setValue("favorites", ",".join(_node_classes(value)[:7]))

    entries = [
        action(("★ " if name in favorites else "") + name,
               lambda node_class=name: build(single(node_class)))
        for name in visible[:4]
    ]
    return tuple(entries + [action("Search Nodes…", search), action("Recipes…", recipes),
                            action("Insert Node…", lambda: search(insert=True)),
                            action("Edit favorites…", edit_favorites)])


@dataclass(frozen=True)
class PieAction:
    label: str
    callback: object
    enabled: object = True
    icon: str = ""
    children: tuple = ()


@dataclass(frozen=True)
class PieSlice:
    label: str
    actions: tuple
    shortcut: str


def _context_actions(nuke, action, undo):
    """Build explicit commands for the selection captured when the pie opens."""
    nodes = tuple(nuke.selectedNodes())
    classes = {node.Class() for node in nodes}
    commands = []

    def add(label, operation, modifies=True):
        def run():
            if set(nuke.selectedNodes()) != set(nodes):
                nuke.message("Selection changed. Reopen the pie to refresh context.")
                return
            operation()
        commands.append(action(label, undo(label, run) if modifies else run))

    def common_knobs(name):
        knobs = tuple(node.knob(name) for node in nodes)
        return knobs if knobs and all(knob is not None for knob in knobs) else ()

    def set_values(knobs, value):
        for knob in knobs:
            knob.setValue(value)

    if nodes:
        def show_properties():
            open_panels(nodes, _qt())

        add("Quick properties…", show_properties, modifies=False)

    if nodes and classes <= {"Merge", "Merge2"}:
        operations = common_knobs("operation")
        for value in ("over", "plus", "multiply", "screen", "difference"):
            if operations and all(value in knob.values() for knob in operations):
                add("Merge: " + value, lambda value=value: set_values(operations, value))
    if nodes and classes <= {"Transform", "TransformMasked"}:
        rotate = common_knobs("rotate")
        if rotate and all(not knob.isAnimated() for knob in rotate):
            add("Zero rotation", lambda: set_values(rotate, 0))
        pivots = common_knobs("center")
        if pivots and all(not knob.isAnimated() for knob in pivots):
            def center_pivots():
                if any(knob.isAnimated() for knob in pivots):
                    raise ValueError("A selected pivot is animated.")
                points = []
                for node in nodes:
                    source = node.input(0)
                    if source is None:
                        raise ValueError("Connect an image input to each selected Transform.")
                    fmt = source.format()
                    points.append((fmt.width() / 2.0, fmt.height() / 2.0))
                if nuke.ask("Center the selected pivots in their input formats? "
                            "Changing a pivot can change the transformed image."):
                    for knob, point in zip(pivots, points):
                        knob.setValue(point[0], 0)
                        knob.setValue(point[1], 1)

            add("Center input pivot…", center_pivots)
    if nodes and (classes <= {"Read", "DeepRead"} or classes <= {"Write", "DeepWrite"}):
        files = common_knobs("file")
        if files:
            def inspect_media():
                reports = []
                for node, file_knob in zip(nodes, files):
                    lines = [node.name(), file_knob.value() or "(No file path)"]
                    for first_name, last_name, label in (
                        ("first", "last", "Frame range"),
                        ("origfirst", "origlast", "Original range"),
                    ):
                        first, last = node.knob(first_name), node.knob(last_name)
                        if first is not None and last is not None:
                            lines.append("{}: {}–{}".format(label, first.value(), last.value()))
                    reports.append("\n".join(lines))
                nuke.message("\n\n".join(reports))

            add("Inspect file and range", inspect_media, modifies=False)
    if nodes and classes <= {"Read", "ReadGeo", "ReadGeo2"}:
        buttons = common_knobs("reload")
        if buttons and all(callable(getattr(knob, "execute", None)) for knob in buttons):
            def reload_media():
                for button in buttons:
                    button.execute()
            add("Reload media", reload_media)

    disabled = common_knobs("disable")
    if disabled and all(not knob.isAnimated() for knob in disabled):
        add("Enable selected", lambda: set_values(disabled, False))
        add("Disable selected", lambda: set_values(disabled, True))

    return tuple(commands) or (PieAction("No shared commands", None, False),)


SLICE_ORDER = (
    ("Navigate", "1"),
    ("Connect", "2"),
    ("Create", "3"),
    ("Arrange", "4"),
    ("Edit", "5"),
    ("Select", "6"),
    ("Viewer", "7"),
    ("Context", "8"),
)


def build_default_slices(nuke):
    """Return the stable v1 pie layout and conservative Nuke actions."""
    def action(label, callback):
        return PieAction(label, callback)

    def submenu(label, children, empty):
        return PieAction(label, None, children=children or (PieAction(empty, None, False),))

    def selected_or_warn():
        nodes = list(nuke.selectedNodes())
        if not nodes:
            nuke.message("Select at least one node.")
        return nodes

    def undo(label, callback):
        def run():
            begin = getattr(nuke, "Undo", None)
            if begin is not None:
                with begin(label):
                    callback()
            else:
                callback()
        return run

    def duplicate():
        originals = selected_or_warn()
        if not originals:
            return
        before = set(nuke.allNodes())
        with TemporaryDirectory(prefix="nuke-pie-") as folder:
            path = str(Path(folder) / "branch.nk")
            nuke.nodeCopy(path)
            try:
                for node in originals:
                    node.setSelected(False)
                nuke.nodePaste(path)
                copies = [node for node in nuke.allNodes() if node not in before]
                if not copies:
                    raise ValueError("Nuke did not paste any duplicate nodes.")
                for node in copies:
                    node.setSelected(True)
            except Exception:
                for node in reversed(nuke.allNodes()):
                    if node not in before:
                        nuke.delete(node)
                for node in originals:
                    node.setSelected(True)
                raise

    def batch_rename():
        nodes = sorted(selected_or_warn(), key=lambda node: (node.ypos(), node.xpos(), node.name()))
        if not nodes:
            return
        prefix = nuke.getInput("Name prefix (adds _01, _02, …)", "")
        if prefix is None:
            return
        prefix = prefix.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", prefix):
            raise ValueError("Use a name prefix containing letters, digits, or underscores.")
        plan = [(node, node.name(), "{}_{:02d}".format(prefix, i))
                for i, node in enumerate(nodes, 1)]
        plan = [(node, old, new) for node, old, new in plan if old != new]
        if not plan:
            return

        def validate():
            existing = {node.name(): node for node in nuke.allNodes()}
            for node, old, new in plan:
                if existing.get(old) != node:
                    raise ValueError("The selection changed. Open the menu again.")
                if new in existing:
                    raise ValueError("A node already uses the name {}.".format(new))

        validate()
        preview = "\n".join("{} → {}".format(old, new) for _, old, new in plan[:10])
        if len(plan) > 10:
            preview += "\n… and {} more".format(len(plan) - 10)
        if not nuke.ask("Rename {} node(s)?\n\n{}".format(len(plan), preview)):
            return
        validate()

        def rename():
            changed = []
            try:
                for node, old, new in plan:
                    changed.append((node, old))
                    node.setName(new)
                    if node.name() != new:
                        raise ValueError("Nuke did not apply the name {}.".format(new))
            except Exception:
                for node, old in reversed(changed):
                    node.setName(old)
                raise

        undo("Batch rename nodes", rename)()

    def delete():
        for node in selected_or_warn():
            nuke.delete(node)

    def set_disabled(state):
        nodes = selected_or_warn()
        for node in nodes:
            knob = node.knob("disable")
            if knob is not None and not knob.isAnimated():
                knob.setValue(state)

    def copy():
        if selected_or_warn():
            nuke.nodeCopy("%clipboard%")

    def paste():
        nuke.nodePaste("%clipboard%")

    def select_connected():
        nodes = selected_or_warn()
        if not nodes:
            return
        for node in nodes:
            for input_node in (node.input(i) for i in range(node.inputs())):
                if input_node is not None:
                    input_node.setSelected(True)

    def tidy():
        for node in selected_or_warn():
            nuke.autoplace(node)

    def connect():
        nodes = selected_or_warn()
        if len(nodes) != 2:
            nuke.message("Select exactly two nodes to connect.")
            return
        source, target = sorted(nodes, key=lambda node: node.ypos())
        if (source.ypos() == target.ypos() or not target.maxInputs()
                or target.input(0) is not None or not target.canSetInput(0, source)):
            nuke.message("Select nodes in top-to-bottom order with a free destination input.")
            return
        target.setInput(0, source)

    def choose_wire(title, wires):
        if not wires:
            nuke.message("No connected inputs match the current selection.")
            return None
        _, _, widgets = _qt()
        choices = {
            "{} → {} [input {}]".format(source.name(), target.name(), index):
                (source, target, index)
            for source, target, index in wires
        }
        label, accepted = widgets.QInputDialog.getItem(
            widgets.QApplication.activeWindow(), title, "Choose the connection:",
            list(choices), 0, False)
        return choices[label] if accepted else None

    def insert_dot():
        nodes = list(nuke.selectedNodes())
        if len(nodes) != 1:
            nuke.message("Select one upstream node first.")
            return
        source = nodes[0]
        wire = choose_wire("Insert Dot", [
            (source, target, index) for target in nuke.allNodes()
            for index in range(target.inputs()) if target.input(index) == source
        ])
        if wire:
            source, target, index = wire
            creation.create(nuke, [{"class": "Dot", "x": 0, "y": 0}], source, (target, index))

    def disconnect():
        wire = choose_wire("Disconnect Input", [
            (target.input(index), target, index) for target in nuke.selectedNodes()
            for index in range(target.inputs()) if target.input(index) is not None
        ])
        if wire:
            source, target, index = wire
            if target.input(index) != source:
                raise ValueError("That connection changed. Open the menu again.")
            undo("Disconnect input", lambda: target.setInput(index, None))()

    def swap_merge():
        nodes = list(nuke.selectedNodes())
        if len(nodes) != 1 or nodes[0].Class() not in {"Merge", "Merge2"}:
            nuke.message("Select one Merge node.")
            return
        node = nodes[0]
        first, second = node.input(0), node.input(1)
        if first is None or second is None:
            nuke.message("Connect both Merge inputs before swapping them.")
            return
        if not node.canSetInput(0, second) or not node.canSetInput(1, first):
            raise ValueError("Nuke rejected the proposed input swap.")
        if not nuke.ask("Swap A/B on {}?\n{} ⇄ {}".format(
                node.name(), first.name(), second.name())):
            return
        if (node.input(0), node.input(1)) != (first, second):
            raise ValueError("The Merge wiring changed. Open the menu again.")
        try:
            node.setInput(0, second)
            node.setInput(1, first)
            if (node.input(0), node.input(1)) != (second, first):
                raise ValueError("Nuke did not complete the input swap.")
        except Exception:
            node.setInput(0, first)
            node.setInput(1, second)
            raise

    actions = {
        "Navigate": _NAVIGATION.actions(nuke, _qt()[2], action, submenu),
        "Create": _create_actions(nuke, action),
        "Connect": (
            action("Connect pair", undo("Connect nodes", connect)),
            action("Insert Dot…", insert_dot),
            action("Disconnect input…", disconnect),
            action("Swap Merge A/B…", undo("Swap Merge A/B", swap_merge)),
        ),
        "Arrange": arrangement.actions(nuke, action, undo) + (
            action("Auto-place selected", undo("Auto-place selected", tidy)),
        ),
        "Edit": (
            action("Duplicate branch", undo("Duplicate branch", duplicate)),
            action("Batch rename…", batch_rename),
            action("Delete", undo("Delete nodes", delete)),
            action("Disable selected", undo("Disable selected", lambda: set_disabled(True))),
            action("Enable selected", undo("Enable selected", lambda: set_disabled(False))),
            action("Copy", copy),
            action("Paste", paste),
            action(customization.EDITOR, lambda: customization.edit(_qt(), _node_preferences(), slices, nuke)),
        ),
        "Select": (
            action("Add direct inputs", select_connected),
            action("Trace upstream", lambda: selection.trace(nuke, "upstream")),
            action("Trace downstream", lambda: selection.trace(nuke, "downstream")),
            action("Find source Reads", lambda: selection.trace(nuke, "reads")),
            action("Find output Writes", lambda: selection.trace(nuke, "writes")),
            action("Between two anchors", lambda: selection.trace(nuke, "between")),
        ),
        "Viewer": viewer_tools.actions(nuke, _qt()[2], action, undo) or (
            PieAction("No active Viewer", None, False),
        ),
        "Context": _context_actions(nuke, action, undo),
    }
    slices = tuple(
        PieSlice(label, actions[label], shortcut)
        for label, shortcut in SLICE_ORDER
    )
    return slices


def install(nuke):
    """Install the global Q command and a visible menu entry."""
    global _RECENT_CALLBACK
    if not getattr(nuke, "GUI", False):
        return

    callback = lambda: show(nuke)
    customize = lambda: customization.edit(_qt(), _node_preferences(), build_default_slices(nuke), nuke)

    # The Nodes menu is a toolbar/menu context in Nuke and does not reliably
    # own keyboard shortcuts when the DAG has focus. Register Q on the main
    # Nuke menu, whose commands are global to the GUI session.
    nuke_menu = nuke.menu("Nuke")
    studio_menu = nuke_menu.findItem("Studio") or nuke_menu.addMenu("Studio")
    if studio_menu.findItem("Pie Menu") is None:
        studio_menu.addCommand("Pie Menu", callback)
    if studio_menu.findItem("Customize Pie") is None:
        studio_menu.addCommand("Customize Pie", customize)

    nodes_menu = nuke.menu("Nodes")
    nodes_studio = nodes_menu.findItem("Studio") or nodes_menu.addMenu("Studio")
    if nodes_studio.findItem("Pie Menu") is None:
        nodes_studio.addCommand("Pie Menu", callback)

    _install_event_filter(nuke)
    if _RECENT_CALLBACK is None:
        def remember():
            _remember_node(nuke)

        nuke.addOnUserCreate(remember)
        _RECENT_CALLBACK = remember


def _install_event_filter(nuke):
    """Install a real press-and-hold handler on QApplication.

    Nuke menu shortcuts are focus-sensitive in some releases. The event
    filter is attached to QApplication instead, so Q works while the DAG has
    focus and does not depend on a menu item being invoked.
    """
    global _CONTROLLER
    QtCore, QtGui, QtWidgets = _qt()
    app = QtWidgets.QApplication.instance()
    if app is None or _CONTROLLER is not None:
        return

    def in_node_graph(widget):
        while isinstance(widget, QtWidgets.QWidget):
            if isinstance(widget, (QtWidgets.QLineEdit, QtWidgets.QTextEdit,
                                   QtWidgets.QPlainTextEdit, QtWidgets.QAbstractSpinBox)):
                return False
            name = widget.objectName()
            if name == "DAG" or name.startswith("DAG."):
                return True
            widget = widget.parentWidget()
        return False

    class Controller(QtCore.QObject):
        owned_key = None

        def eventFilter(self, watched, event):
            kind = event.type()
            pie = _ACTIVE_PIE
            if kind == QtCore.QEvent.ApplicationDeactivate:
                self.owned_key = None
                if pie is not None:
                    QtCore.QTimer.singleShot(0, lambda: pie.close() if _ACTIVE_PIE is pie else None)
                return False
            # Qt also delivers mouse events to the native QWindow before
            # forwarding them to its QWidget. Let that forwarding happen.
            if pie is not None and watched is not pie and isinstance(watched, QtWidgets.QWidget):
                if kind == QtCore.QEvent.MouseMove:
                    pie.track(pie.mapFromGlobal(QtGui.QCursor.pos()))
                elif kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                    if kind == QtCore.QEvent.MouseButtonPress:
                        pie.close()
                    return True
                elif kind == QtCore.QEvent.KeyPress and (
                        event.key() == QtCore.Qt.Key_Escape
                        or int(QtCore.Qt.Key_1) <= event.key() <= int(QtCore.Qt.Key_8)):
                    pie.keyPressEvent(event)
                    return True
            if kind not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress,
                            QtCore.QEvent.KeyRelease):
                return False
            key = event.key()
            if kind == QtCore.QEvent.KeyRelease:
                if key != self.owned_key:
                    return False
                if not event.isAutoRepeat():
                    self.owned_key = None
                    if _ACTIVE_PIE is not None and _ACTIVE_PIE.selected is not None:
                        _ACTIVE_PIE.track(_ACTIVE_PIE.mapFromGlobal(QtGui.QCursor.pos()))
                        _ACTIVE_PIE.release_hotkey()
                return True
            if key != self.owned_key:
                if (self.owned_key is not None
                        or app.activeModalWidget() is not None
                        or not in_node_graph(app.focusWidget() or watched)):
                    return False
                modifiers = event.modifiers()
                combo = QtGui.QKeySequence(key | int(getattr(modifiers, "value", modifiers)))
                configured = QtGui.QKeySequence.fromString(
                    _node_preferences().value("activation_key", "Q", type=str),
                    QtGui.QKeySequence.PortableText)
                if combo != configured:
                    return False
            if kind == QtCore.QEvent.ShortcutOverride:
                # Qt resolves native shortcuts before it delivers KeyPress.
                event.accept()
            elif not event.isAutoRepeat() and self.owned_key is None:
                self.owned_key = key
                show(nuke)
            return True

    _CONTROLLER = Controller(app)
    app.installEventFilter(_CONTROLLER)


def _qt():
    """Use the studio Qt shim when available, with a PySide fallback."""
    try:
        from Qt import QtCore, QtGui, QtWidgets
    except ImportError:
        try:
            from PySide2 import QtCore, QtGui, QtWidgets
        except ImportError:
            from PySide6 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def show(nuke):
    """Open the modal radial widget at the current cursor position."""
    try:
        QtCore, QtGui, QtWidgets = _qt()
        app = QtWidgets.QApplication.instance()
        if app is None:
            nuke.message("Pie Menu: no Qt application is available.")
            return
        _create_pie(nuke, QtCore, QtGui, QtWidgets)
    except Exception as error:
        nuke.message("Pie Menu could not open:\n{}".format(error))


def _create_pie(nuke, QtCore, QtGui, QtWidgets):
    global _ACTIVE_PIE
    if _ACTIVE_PIE is not None:
        _ACTIVE_PIE.close()
    settings = _node_preferences()
    slices = customization.apply(build_default_slices(nuke), customization.read(settings), PieAction, nuke)
    cursor = QtGui.QCursor.pos()
    scale = max(60, min(125, settings.value("pie_size", 90, type=int))) / 100
    color = QtGui.QColor(settings.value("highlight_color", "", type=str)
                         or customization.DEFAULT_HIGHLIGHT)
    widget = _PieWidget(nuke, slices, QtCore, QtGui, QtWidgets, scale, color)
    screen = QtGui.QGuiApplication.screenAt(cursor) or QtGui.QGuiApplication.primaryScreen()
    area = screen.availableGeometry()
    widget.move(
        max(area.left(), min(cursor.x() - round(widget.radius * widget.scale),
                             area.right() - widget.width() + 1)),
        max(area.top(), min(cursor.y() - round(widget.center_y * widget.scale),
                            area.bottom() - widget.height() + 1)),
    )
    widget.show()
    widget.raise_()
    _ACTIVE_PIE = widget
    return widget


class _PieWidget:
    """Paint and hit-test the same card and submenu geometry."""

    def __new__(cls, nuke, slices, QtCore, QtGui, QtWidgets, scale=0.9, highlight=None):
        class Pie(QtWidgets.QWidget):
            logical_width = 1000
            logical_height = 565
            radius = 500
            center_y = 188

            def __init__(self):
                super().__init__(None)
                self.scale = scale
                self.selected = self.row = None
                self.child = None
                self.child_offset = 0
                self.pressed_row = None
                self.setFixedSize(round(self.logical_width * self.scale),
                                  round(self.logical_height * self.scale))
                self.setWindowFlags(QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)
                self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
                self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
                self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
                self.setMouseTracking(True)

            def card(self, index):
                offsets = ((0, -130), (154, -80), (174, 0), (154, 80),
                           (0, 130), (-154, 80), (-174, 0), (-154, -80))
                x, y = offsets[index]
                return QtCore.QRectF(self.radius + x - 65, self.center_y + y - 19, 130, 38)

            def menu_font(self):
                font = QtWidgets.QApplication.font()
                # Match the application text size after the painter scales
                # the menu geometry.
                if font.pointSizeF() > 0:
                    font.setPointSizeF(font.pointSizeF() / self.scale)
                elif font.pixelSize() > 0:
                    font.setPixelSize(round(font.pixelSize() / self.scale))
                return font

            def panel(self):
                if self.selected is None or not slices[self.selected].actions:
                    return None
                card = self.card(self.selected)
                actions = slices[self.selected].actions
                metrics = QtGui.QFontMetrics(self.menu_font())
                width = max(160, max(metrics.horizontalAdvance(item.label)
                                     + (50 if item.children else 38) for item in actions))
                left = card.left()
                reserved = 160 if any(item.children for item in actions) else 0
                width = min(width, self.logical_width - left - reserved - 6)
                height = 8 + 26 * len(actions)
                return QtCore.QRectF(left, card.bottom(), width, height)

            def row_rect(self, panel, index):
                return QtCore.QRectF(panel.left() + 4, panel.top() + 4 + index * 26,
                                     panel.width() - 8, 26)

            def children(self):
                if self.selected is None or self.row is None:
                    return ()
                return slices[self.selected].actions[self.row].children

            def flyout(self, panel):
                children = self.children()
                if not children:
                    return None
                anchor = self.row_rect(panel, self.row)
                metrics = QtGui.QFontMetrics(self.menu_font())
                width = max(160, max(metrics.horizontalAdvance(item.label)
                                     + (50 if item.children else 38) for item in children))
                width = min(width, self.logical_width - panel.right() - 6)
                height = 8 + 26 * min(8, len(children))
                top = min(anchor.top() - 4, self.logical_height - height - 6)
                return QtCore.QRectF(panel.right(), top, width, height)

            def visible_children(self):
                return self.children()[self.child_offset:self.child_offset + 8]

            def track(self, point):
                point = self.logical_point(point)
                panel = self.panel()
                flyout = self.flyout(panel)
                self.child = None
                if flyout is not None and flyout.contains(point):
                    self.child = next((i for i in range(len(self.visible_children()))
                                       if self.row_rect(flyout, i).contains(point)), None)
                    self.update()
                    return
                previous = (self.selected, self.row)
                self.row = None
                if panel is not None and panel.contains(point):
                    self.row = next((i for i in range(len(slices[self.selected].actions))
                                     if self.row_rect(panel, i).contains(point)), None)
                else:
                    self.selected = next((i for i in range(len(slices)) if self.card(i).contains(point)), None)
                if previous != (self.selected, self.row):
                    self.child_offset = 0
                self.update()

            def logical_point(self, point):
                return QtCore.QPointF(point.x() / self.scale, point.y() / self.scale)

            def wheelEvent(self, event):
                panel = self.flyout(self.panel())
                point = event.position() if hasattr(event, "position") else event.pos()
                if panel is None or not panel.contains(self.logical_point(point)):
                    return
                delta = event.angleDelta().y()
                if delta:
                    self.child_offset = max(0, min(len(self.children()) - 8,
                                                   self.child_offset + (-1 if delta > 0 else 1)))
                    self.track(point)

            def mouseMoveEvent(self, event):
                self.track(event.pos())

            def leaveEvent(self, event):
                # The translucent portions of the overlay can pass mouse
                # events through to the graph, including when leaving Nuke.
                self.track(self.mapFromGlobal(QtGui.QCursor.pos()))
                super().leaveEvent(event)

            def mousePressEvent(self, event):
                self.track(event.pos())
                self.pressed_row = (self.selected, self.row, self.child, self.child_offset)

            def mouseReleaseEvent(self, event):
                if event.button() != QtCore.Qt.LeftButton:
                    self.close()
                    return
                self.track(event.pos())
                if self.pressed_row == (self.selected, self.row, self.child, self.child_offset):
                    self.release_hotkey()
                self.pressed_row = None

            def release_hotkey(self):
                if self.selected is None:
                    self.close()
                    return
                actions = slices[self.selected].actions
                if self.child is not None:
                    self.activate(self.visible_children()[self.child])
                elif self.children():
                    return
                elif self.row is not None:
                    self.activate(actions[self.row])
                elif not actions:
                    self.close()

            def keyPressEvent(self, event):
                if event.isAutoRepeat():
                    return
                if event.key() == QtCore.Qt.Key_Escape:
                    self.close()
                    return
                key = int(event.key()) - int(QtCore.Qt.Key_1)
                if 0 <= key < 8:
                    if self.children():
                        children = self.visible_children()
                        if key < len(children):
                            self.activate(children[key])
                    elif self.panel() is not None:
                        actions = slices[self.selected].actions
                        if key < len(actions):
                            if actions[key].children:
                                self.row, self.child, self.child_offset = key, None, 0
                                self.update()
                            else:
                                self.activate(actions[key])
                    elif key < len(slices):
                        self.selected, self.row = key, None
                        self.update()

            def closeEvent(self, event):
                global _ACTIVE_PIE
                if _ACTIVE_PIE is self:
                    _ACTIVE_PIE = None
                super().closeEvent(event)

            def activate(self, action):
                if not action.enabled:
                    self.close()
                    return
                self.close()

                def invoke():
                    try:
                        if action.children:
                            menu = QtWidgets.QMenu()
                            if highlight is not None and highlight.isValid():
                                menu.setStyleSheet("QMenu::item:selected { background: %s; }"
                                                   % highlight.name())
                            callbacks = {}

                            def append(parent, entries):
                                for entry in entries:
                                    if entry.children:
                                        append(parent.addMenu(entry.label), entry.children)
                                    else:
                                        command = parent.addAction(entry.label)
                                        command.setEnabled(bool(entry.enabled))
                                        callbacks[command] = entry.callback

                            append(menu, action.children)
                            execute = getattr(menu, "exec", None) or menu.exec_
                            chosen = execute(QtGui.QCursor.pos())
                            if chosen in callbacks:
                                callbacks[chosen]()
                        else:
                            action.callback()
                    except Exception as error:
                        nuke.message("{} failed.\\n{}".format(action.label, error))

                QtCore.QTimer.singleShot(0, invoke)

            def paintEvent(self, event):
                painter = QtGui.QPainter(self)
                painter.scale(self.scale, self.scale)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                painter.setFont(self.menu_font())
                accent = (highlight if highlight is not None and highlight.isValid()
                          else QtGui.QColor(customization.DEFAULT_HIGHLIGHT))
                selected_text = "#171717" if accent.lightness() > 160 else "#ededed"
                middle = QtCore.Qt.AlignVCenter

                def box(rect, active=False):
                    painter.setPen(QtGui.QColor("#292929"))
                    painter.setBrush(accent if active else QtGui.QColor("#191919"))
                    painter.drawRoundedRect(rect, 5, 5)

                def label(rect, value, align, color="#ededed"):
                    painter.setPen(QtGui.QColor(color))
                    painter.drawText(rect, middle | align, value)

                panel = self.panel()
                painter.save()
                if panel is not None:
                    painter.setOpacity(0.2)
                for i, item in enumerate(slices):
                    card = self.card(i)
                    box(card, i == self.selected)
                    label(card.adjusted(12, 0, -27, 0), item.label, QtCore.Qt.AlignLeft,
                          selected_text if i == self.selected else "#ededed")
                    label(card.adjusted(0, 0, -12, 0), item.shortcut, QtCore.Qt.AlignRight, "#aaaaaa")
                painter.restore()

                x, y = self.radius, self.center_y
                ring = QtCore.QRectF(x - 22, y - 22, 44, 44)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(QtGui.QPen(QtGui.QColor("#191919"), 8))
                painter.drawEllipse(ring)
                if self.selected is not None:
                    painter.setPen(QtGui.QPen(accent, 8))
                    painter.drawArc(ring, int((102 - self.selected * 45) * 16), 24 * 16)
                label(QtCore.QRectF(x - 100, y - 65, 200, 27), "Node Graph Pie",
                      QtCore.Qt.AlignHCenter, "#bcbcbc")

                def paint_rows(panel, actions, selected):
                    box(panel)
                    for i, action in enumerate(actions):
                        row = self.row_rect(panel, i)
                        if i == selected:
                            box(row, True)
                        text_rect = row.adjusted(7, 0, -32 if action.children else -21, 0)
                        name = painter.fontMetrics().elidedText(
                            action.label, QtCore.Qt.ElideRight, int(text_rect.width()))
                        label(text_rect, name, QtCore.Qt.AlignLeft,
                              (selected_text if i == selected else "#ededed")
                              if action.enabled else "#888888")
                        shortcut = "{} ›".format(i + 1) if action.children else str(i + 1)
                        label(row.adjusted(0, 0, -6, 0), shortcut,
                              QtCore.Qt.AlignRight, "#aaaaaa")

                if panel is not None:
                    paint_rows(panel, slices[self.selected].actions, self.row)
                    flyout = self.flyout(panel)
                    if flyout is not None:
                        paint_rows(flyout, self.visible_children(), self.child)
                painter.end()

        return Pie()
