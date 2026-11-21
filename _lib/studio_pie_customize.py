"""Persist and edit the radial menu layout."""

from dataclasses import replace
import json


EDITOR = "Customize Pie…"
DEFAULT_HIGHLIGHT = "#00557f"


def read(settings):
    try:
        value = json.loads(settings.value("custom_layout", "[]", type=str))
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def source_tree(slices, saved):
    """Upgrade legacy sibling-only layouts to command references."""
    def convert(items, rows, parent=()):
        result = []
        for item, row in ordered(items, rows):
            path = (*parent, row["id"])
            children = getattr(item, "actions", ()) or getattr(item, "children", ())
            result.append(dict(row, source=list(path),
                               children=convert(children, row["children"], path)))
        return result

    return saved if saved and all("source" in row for row in saved) else convert(slices, saved)


def catalog(slices):
    result = {}

    def visit(items, parent=()):
        for item in items:
            path = (*parent, item.label)
            result[path] = item
            visit(getattr(item, "actions", ()) or getattr(item, "children", ()), path)

    visit(slices)
    return result


def ordered(items, saved):
    remaining = {item.label: item for item in items}
    for row in saved:
        item = remaining.pop(row["id"], None)
        yield item, row
    for item in remaining.values():
        yield item, {"id": item.label, "label": item.label, "visible": True, "children": []}


def apply(slices, saved, action_factory=None, nuke=None):
    originals = catalog(slices)
    rows = source_tree(slices, saved)
    if action_factory is None:
        action_factory = type(slices[0].actions[0])

    def references(rows):
        return {path for row in rows
                for path in ({tuple(row["source"])} | references(row["children"]))}

    referenced = references(rows)

    def entries(rows):
        result = []
        for row in rows:
            path = tuple(row["source"])
            item = originals.get(path)
            if not row["visible"] and path != ("Edit", EDITOR):
                continue
            label = row["label"]
            children = entries(row["children"])
            if item is not None and item.children:
                children += tuple(child for child in item.children
                                  if (*path, child.label) not in referenced
                                  and child.enabled)
            if children or row.get("kind") == "folder":
                if children:
                    result.append(action_factory(label, None, children=children))
            elif item is not None and not item.children:
                result.append(replace(item, label=label))
            elif row.get("kind") == "native" and nuke is not None:
                root, name = path

                def invoke(root=root, name=name):
                    command = nuke.menu(root).findItem(name)
                    if command is None:
                        raise ValueError("Nuke menu command is unavailable: " + name)
                    command.invoke()

                result.append(action_factory(label, invoke))
        return tuple(result)

    result = []
    slice_type = type(slices[0])
    editor = originals.get(("Edit", EDITOR))
    for row in rows:
        path = tuple(row["source"])
        if not row["visible"] and path != ("Edit",):
            continue
        actions = entries(row["children"])
        if path in {("Create",), ("Context",), ("Viewer",)}:
            actions += tuple(item for item in originals[path].actions
                             if (*path, item.label) not in referenced)
        if path == ("Edit",) and editor is not None and not any(
                tuple(child["source"]) == ("Edit", EDITOR) for child in row["children"]):
            actions += (editor,)
        if not actions:
            continue
        if len(actions) > 8:
            hidden_editor = tuple(item for item in actions[7:] if item.callback == getattr(editor, "callback", None)
                                  and item.callback is not None)
            if hidden_editor:
                actions = tuple(item for item in actions if item not in hidden_editor)
                actions = hidden_editor + actions
            actions = actions[:7] + (action_factory("More", None, children=actions[7:]),)
        result.append(slice_type(row["label"], actions, str(len(result) + 1)))
    return tuple(result[:8])


def edit(qt, settings, slices, nuke):
    core, gui, widgets = qt
    dialog = widgets.QDialog(widgets.QApplication.activeWindow())
    dialog.setWindowTitle("Customize Pie")
    dialog.resize(650, 600)
    layout = widgets.QVBoxLayout(dialog)
    layout.addWidget(widgets.QLabel(
        "Drag to reorder or move commands between folders. Double-click to rename.\n"
        "The first eight visible slices are ordered clockwise from the top."))
    role = core.Qt.UserRole

    class LayoutTree(widgets.QTreeWidget):
        def dropEvent(self, event):
            item = self.currentItem()
            target = self.itemAt(event.position().toPoint() if hasattr(event, "position") else event.pos())
            if item is None:
                event.ignore()
                return
            source = item.data(0, role)
            on_item = self.dropIndicatorPosition() == self.OnItem
            parent = target if on_item else target.parent() if target is not None else None
            # Top-level rows are slices; commands and folders stay below them.
            if ((item.parent() is None) != (parent is None)
                    or (on_item and not target.flags() & core.Qt.ItemIsDropEnabled)
                    or (source["source"] == ["Edit", EDITOR]
                        and parent is not item.parent())):
                event.ignore()
                return
            super().dropEvent(event)

    tree = LayoutTree()
    tree.setHeaderLabels(["Menu entry", "Source"])
    tree.setColumnWidth(0, 300)
    tree.setDragDropMode(widgets.QAbstractItemView.InternalMove)
    tree.setDefaultDropAction(core.Qt.MoveAction)
    layout.addWidget(tree)

    def insert(parent, row):
        path = row["source"]
        protected = path in (["Edit"], ["Edit", EDITOR])
        entry = widgets.QTreeWidgetItem(parent, [row["label"], " / ".join(path)])
        entry.setData(0, role, row)
        flags = entry.flags() | core.Qt.ItemIsEditable | core.Qt.ItemIsDragEnabled
        if parent is tree or row["children"] or row.get("kind") == "folder":
            flags |= core.Qt.ItemIsDropEnabled
        else:
            flags &= ~core.Qt.ItemIsDropEnabled
        if protected:
            flags &= ~core.Qt.ItemIsUserCheckable
        else:
            flags |= core.Qt.ItemIsUserCheckable
            entry.setCheckState(0, core.Qt.Checked if row["visible"] else core.Qt.Unchecked)
        entry.setFlags(flags)
        for child in row["children"]:
            insert(entry, child)
        return entry

    def serialize(parent):
        rows = []
        for index in range(parent.childCount()):
            entry = parent.child(index)
            row = entry.data(0, role)
            protected = row["source"] in (["Edit"], ["Edit", EDITOR])
            rows.append(dict(row, label=entry.text(0).strip() or row["label"],
                             visible=protected or entry.checkState(0) == core.Qt.Checked,
                             children=serialize(entry)))
        return rows

    def parent_for_new():
        entry = tree.currentItem()
        if entry is None:
            return tree.topLevelItem(0)
        return entry if entry.flags() & core.Qt.ItemIsDropEnabled else entry.parent()

    def add_folder(new_slice=False):
        label, accepted = widgets.QInputDialog.getText(dialog, "New Menu", "Name:")
        if accepted and label.strip():
            parent = tree if new_slice else parent_for_new()
            if parent is not None:
                entry = insert(parent, {"id": "", "source": [], "label": label.strip(),
                                        "visible": True, "children": [], "kind": "folder"})
                tree.setCurrentItem(entry)
                if parent is not tree:
                    parent.setExpanded(True)

    def add_native():
        parent = parent_for_new()
        if parent is None:
            return
        picker = widgets.QDialog(dialog)
        picker.setWindowTitle("Add Nuke Command")
        picker.resize(430, 500)
        picker_layout = widgets.QVBoxLayout(picker)
        browser = widgets.QTreeWidget()
        browser.setHeaderLabel("Nuke menus")
        picker_layout.addWidget(browser)

        def scan(menu, root, branch, path_prefix=""):
            for item in menu.items():
                name = item.name()
                if not name:
                    continue
                path = path_prefix + "/" + name if path_prefix else name
                row = widgets.QTreeWidgetItem(branch, [name])
                if callable(getattr(item, "items", None)):
                    scan(item, root, row, path)
                else:
                    row.setData(0, role, [root, path, name])

        for root in ("Nuke", "Nodes"):
            menu = nuke.menu(root)
            if menu is not None:
                branch = widgets.QTreeWidgetItem(browser, [root])
                scan(menu, root, branch)
                branch.setExpanded(True)

        buttons = widgets.QDialogButtonBox(widgets.QDialogButtonBox.Ok | widgets.QDialogButtonBox.Cancel)
        add_button = buttons.button(widgets.QDialogButtonBox.Ok)
        add_button.setText("Add Command")
        add_button.setEnabled(False)
        picker_layout.addWidget(buttons)

        def selected_command():
            current = browser.currentItem()
            return current.data(0, role) if current is not None else None

        def accept_command():
            if selected_command() is not None:
                picker.accept()

        browser.currentItemChanged.connect(
            lambda current, previous: add_button.setEnabled(selected_command() is not None))
        browser.itemDoubleClicked.connect(lambda item, column: accept_command())
        buttons.accepted.connect(accept_command)
        buttons.rejected.connect(picker.reject)
        execute = getattr(picker, "exec", None) or picker.exec_
        if execute():
            root, path, name = selected_command()
            entry = insert(parent, {"id": path, "source": [root, path], "label": name,
                                    "visible": True, "children": [], "kind": "native"})
            parent.setExpanded(True)
            tree.setCurrentItem(entry)

    def remove():
        entry = tree.currentItem()
        if entry is not None and entry.data(0, role).get("kind") in {"native", "folder"}:
            parent = entry.parent() or tree.invisibleRootItem()
            if entry.childCount() and not widgets.QMessageBox.question(
                    dialog, "Remove Menu", "Remove this custom menu and all its entries?",
                    widgets.QMessageBox.Yes | widgets.QMessageBox.No) == widgets.QMessageBox.Yes:
                return
            parent.takeChild(parent.indexOfChild(entry))

    def buttons_for(entries):
        row = widgets.QHBoxLayout()
        layout.addLayout(row)
        for label, callback in entries:
            button = widgets.QPushButton(label)
            button.clicked.connect(lambda checked=False, callback=callback: callback())
            row.addWidget(button)

    buttons_for((("New slice", lambda: add_folder(True)), ("New submenu", add_folder),
                 ("Add Nuke command", add_native), ("Remove custom entry", remove)))

    form = widgets.QFormLayout()
    layout.addLayout(form)
    hotkey = widgets.QKeySequenceEdit()
    if hasattr(hotkey, "setMaximumSequenceLength"):
        hotkey.setMaximumSequenceLength(1)
    form.addRow("Activation key", hotkey)
    size = widgets.QSlider(core.Qt.Horizontal)
    size.setRange(60, 125)
    percent = widgets.QLabel()
    size.valueChanged.connect(lambda value: percent.setText("{}%".format(value)))
    size_row = widgets.QHBoxLayout()
    size_row.addWidget(size, 1)
    size_row.addWidget(percent)
    form.addRow("Size", size_row)
    color = [""]
    swatch = widgets.QPushButton()
    palette_color = gui.QColor(DEFAULT_HIGHLIGHT)

    def set_color(value):
        color[0] = value
        swatch.setText(value or DEFAULT_HIGHLIGHT)
        swatch.setStyleSheet("border-left: 14px solid {};".format(value or palette_color.name()))

    def pick_color():
        value = widgets.QColorDialog.getColor(gui.QColor(color[0]) if color[0] else palette_color, dialog)
        if value.isValid():
            set_color(value.name())

    swatch.clicked.connect(pick_color)
    color_row = widgets.QHBoxLayout()
    color_row.addWidget(swatch)
    reset_color = widgets.QPushButton("Use default color")
    reset_color.clicked.connect(lambda: set_color(""))
    color_row.addWidget(reset_color)
    form.addRow("Highlight", color_row)

    def load(data):
        tree.clear()
        for row in source_tree(slices, data.get("layout", [])):
            insert(tree, row)
        hotkey.setKeySequence(gui.QKeySequence.fromString(data.get("key", "Q"), gui.QKeySequence.PortableText))
        size.setValue(data.get("size", 90))
        set_color(data.get("color", ""))

    def snapshot():
        sequence = hotkey.keySequence()
        if sequence.count() != 1:
            widgets.QMessageBox.warning(dialog, "Activation Key", "Enter one key or key combination.")
            return None
        rows = serialize(tree.invisibleRootItem())
        if sum(row["visible"] for row in rows) > 8:
            widgets.QMessageBox.warning(dialog, "Pie Layout", "Show no more than eight main slices.")
            return None
        return {"layout": rows,
                "key": sequence.toString(gui.QKeySequence.PortableText),
                "size": size.value(), "color": color[0]}

    try:
        presets = json.loads(settings.value("pie_presets", "{}", type=str))
    except ValueError:
        presets = {}
    if not isinstance(presets, dict):
        presets = {}

    def persist_presets():
        settings.setValue("pie_presets", json.dumps(presets))

    def save_preset(default=False):
        data = snapshot()
        if data is None:
            return
        if default:
            name = "Default"
        else:
            name, accepted = widgets.QInputDialog.getText(dialog, "Save Preset", "Preset name:")
            name = name.strip()
            if not accepted or not name:
                return
        if name in presets and widgets.QMessageBox.question(
                dialog, "Replace Preset", "Replace “{}”?".format(name)) != widgets.QMessageBox.Yes:
            return
        presets[name] = data
        persist_presets()

    def load_preset():
        if not presets:
            widgets.QMessageBox.information(dialog, "Load Preset", "No saved presets.")
            return
        name, accepted = widgets.QInputDialog.getItem(dialog, "Load Preset", "Preset:", sorted(presets), 0, False)
        if accepted:
            load(presets[name])

    buttons_for((("Save preset", save_preset), ("Load preset", load_preset),
                 ("Save as default", lambda: save_preset(True)),
                 ("Restore defaults", lambda: load(presets.get("Default", {})))))
    load({"layout": read(settings), "key": settings.value("activation_key", "Q", type=str),
          "size": settings.value("pie_size", 90, type=int),
          "color": settings.value("highlight_color", "", type=str)})
    buttons = widgets.QDialogButtonBox(widgets.QDialogButtonBox.Ok | widgets.QDialogButtonBox.Cancel)
    layout.addWidget(buttons)

    def accept():
        data = snapshot()
        if data is not None:
            settings.setValue("custom_layout", json.dumps(data["layout"]))
            settings.setValue("activation_key", data["key"])
            settings.setValue("pie_size", data["size"])
            settings.setValue("highlight_color", data["color"])
            dialog.accept()

    buttons.accepted.connect(accept)
    buttons.rejected.connect(dialog.reject)
    execute = getattr(dialog, "exec", None) or dialog.exec_
    execute()
