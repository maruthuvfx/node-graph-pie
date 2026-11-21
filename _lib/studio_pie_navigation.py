"""Spatial navigation for the active Node Graph."""

from collections import deque


class Navigation:
    def __init__(self):
        self.graphs = {}

    def actions(self, nuke, widgets, action, submenu):
        def search_nodes():
            # Match the native Node Graph "/" command in Nuke's menu.py.
            with nuke.lastHitGroup():
                nuke.selectPattern()

        def graph_state():
            key = (nuke.root().name(), nuke.thisGroup().fullName())
            return self.graphs.setdefault(key, ({}, deque(maxlen=30)))

        def jump(point):
            _, history = graph_state()
            previous = tuple(nuke.center())
            nuke.zoom(nuke.zoom(), point)
            if previous != point:
                history.append(previous)

        def frame(nodes):
            if not nodes:
                nuke.message("There are no nodes to center on.")
                return
            centers = []
            for node in nodes:
                if node.Class() == "BackdropNode":
                    width = node["bdwidth"].value()
                    height = node["bdheight"].value()
                else:
                    width, height = node.screenWidth(), node.screenHeight()
                centers.append((node.xpos() + width / 2, node.ypos() + height / 2))
            jump(tuple(sum(axis) / len(centers) for axis in zip(*centers)))

        def bookmarked(node):
            flag = node.knob("bookmark")
            return flag is not None and bool(flag.value())

        def node_entries(bookmarks_only):
            entries = []
            nodes = nuke.allNodes() if bookmarks_only else nuke.allNodes("BackdropNode")
            for node in nodes:
                marked = bookmarked(node)
                if bookmarks_only and not marked:
                    continue
                knob = node.knob("label")
                label = " ".join(knob.value().split()) if knob is not None else ""
                name = "{} [{}]".format(label, node.name()) if label else node.name()
                if marked and not bookmarks_only:
                    name = "★ " + name

                def go(target=node):
                    if target not in nuke.allNodes() or (bookmarks_only and not bookmarked(target)):
                        raise ValueError("This navigation target is no longer available.")
                    frame([target])

                entries.append(action(name, go))
            return tuple(sorted(entries, key=lambda entry: entry.label.casefold()))

        def save():
            bookmarks, _ = graph_state()
            point = tuple(nuke.center())
            name, accepted = widgets.QInputDialog.getText(
                widgets.QApplication.activeWindow(), "Save Graph Bookmark", "Bookmark name:")
            name = name.strip()
            if accepted and name:
                if name in bookmarks and not nuke.ask("Replace bookmark “{}”?".format(name)):
                    return
                bookmarks[name] = point

        def bookmark():
            bookmarks, _ = graph_state()
            locations = tuple(action("Location: " + name, lambda point=point: jump(point))
                              for name, point in sorted(bookmarks.items()))
            return node_entries(bookmarks_only=True) + locations

        def back():
            _, history = graph_state()
            if history:
                nuke.zoom(nuke.zoom(), history[-1])
                history.pop()
            else:
                nuke.message("There are no previous pie navigation locations.")

        return (
            action("Search nodes (/)", search_nodes),
            submenu("Jump to backdrop", node_entries(bookmarks_only=False), "No backdrops"),
            submenu("Jump to bookmark", bookmark(), "No bookmarks"),
            action("Save bookmark…", save),
            action("Previous location", back),
            action("Center on selection", lambda: frame(nuke.selectedNodes())),
        )
