"""Create nodes and reusable linear recipes without replacing existing wiring by default."""

import json
import re


BUILTINS = {
    "Unpremult → Grade → Premult": [
        {"class": name, "x": 0, "y": index * 90}
        for index, name in enumerate(("Unpremult", "Grade", "Premult"))
    ],
    "Dot → Grade": [{"class": "Dot", "x": 0, "y": 0},
                    {"class": "Grade", "x": 0, "y": 90}],
}

SKIP = {"name", "xpos", "ypos", "selected", "file", "proxy", "cached"}
PATH_KNOBS = {"File_Knob", "ReadFile_Knob", "WriteFile_Knob", "Path_Knob"}


def capture(nodes):
    """Capture a single linear chain connected through input zero."""
    nodes = list(nodes)
    if not nodes:
        raise ValueError("Select a node or a connected chain first.")
    links = {}
    starts = []
    for node in nodes:
        if node.Class() in {"Group", "LiveGroup", "Gizmo", "Root", "Viewer", "Input", "Output"}:
            raise ValueError("This node class cannot be saved as a linear recipe.")
        internal = [(i, node.input(i)) for i in range(node.inputs()) if node.input(i) in nodes]
        if not internal:
            starts.append(node)
        elif len(internal) != 1 or internal[0][0] != 0 or internal[0][1] in links:
            raise ValueError("Select one linear chain connected through input zero.")
        else:
            links[internal[0][1]] = node
    if len(starts) != 1:
        raise ValueError("The selection needs exactly one entry node.")
    origin = node = starts[0]
    result = []
    while node is not None:
        knobs = {
            name: knob.toScript() for name, knob in node.knobs().items()
            if name not in SKIP and knob.Class() not in PATH_KNOBS
            and not knob.Class().endswith(("Script_Knob", "Tab_Knob"))
        }
        result.append({"class": node.Class(), "x": node.xpos() - origin.xpos(),
                       "y": node.ypos() - origin.ypos(), "knobs": knobs, "personal": True})
        node = links.get(node)
    if len(result) != len(nodes):
        raise ValueError("The selection contains disconnected nodes.")
    return result


def create(nuke, recipe, source=None, edge=None):
    """Create a recipe as one undo step, with optional explicit pipe insertion."""
    factories = []
    for entry in recipe:
        name = entry["class"]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
            raise ValueError("Invalid Nuke node class.")
        factories.append(getattr(nuke.nodes, name))
    if edge and edge[0].input(edge[1]) != source:
        raise ValueError("The selected connection has changed.")
    selected = list(nuke.selectedNodes())
    x, y = nuke.center()
    if source is not None:
        x, y = source.xpos(), source.ypos() + source.screenHeight() + 70
    created = []
    undo = nuke.Undo()
    undo.begin("Create from Node Graph Pie")
    try:
        for node in selected:
            node.setSelected(False)
        for factory, entry in zip(factories, recipe):
            node = factory()
            created.append(node)
            node.setSelected(False)
            # Factory creation must not carry implicit graph connections.
            for index in range(node.inputs()):
                if node.input(index) is not None:
                    node.setInput(index, None)
            node.setXYpos(int(x + entry["x"]), int(y + entry["y"]))
            for name, script in entry.get("knobs", {}).items():
                knob = node.knob(name)
                if knob is not None and name not in SKIP and knob.Class() not in PATH_KNOBS:
                    knob.fromScript(script)
            if entry.get("personal"):
                for name, knob in node.knobs().items():
                    if name in {"file", "proxy"} or knob.Class() in PATH_KNOBS:
                        knob.clearAnimated()
                        knob.setValue("")
        for upstream, downstream in zip(created, created[1:]):
            if not downstream.canSetInput(0, upstream):
                raise ValueError("The recipe has incompatible internal inputs.")
            downstream.setInput(0, upstream)
            if downstream.input(0) != upstream:
                raise ValueError("Nuke did not connect the recipe chain.")
        if source is not None and created[0].maxInputs() and created[0].canSetInput(0, source):
            created[0].setInput(0, source)
        if edge:
            target, index = edge
            if created[0].input(0) != source or not target.canSetInput(index, created[-1]):
                raise ValueError("The recipe is incompatible with that connection.")
            target.setInput(index, created[-1])
            if target.input(index) != created[-1]:
                raise ValueError("Nuke did not replace the selected connection.")
        for node in created:
            node.setSelected(True)
    except Exception:
        if edge and edge[0].input(edge[1]) != source:
            edge[0].setInput(edge[1], source)
        for node in reversed(created):
            nuke.delete(node)
        for node in selected:
            node.setSelected(True)
        raise
    finally:
        undo.end()
    return created


def recipe_library(settings):
    try:
        saved = json.loads(settings.value("recipes", "{}", type=str))
    except ValueError:
        saved = {}
    return saved if isinstance(saved, dict) else {}
