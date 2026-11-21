"""Display and comparison commands for the active Viewer."""


def compare(nuke, viewer):
    sources = sorted(nuke.selectedNodes(), key=lambda node: (node.xpos(), node.ypos(), node.name()))
    if len(sources) != 2:
        raise ValueError("Select two image nodes to compare.")
    node = viewer.node()
    available = list(range(node.maxInputs()))
    slots = []
    for source in sources:
        existing = [i for i in available if node.input(i) == source]
        free = [i for i in available if node.input(i) is None and node.canSetInput(i, source)]
        candidates = existing or free
        if not candidates:
            raise ValueError("The Viewer has no compatible free input for {}.".format(source.name()))
        slots.append(candidates[0])
        available.remove(candidates[0])
    if not nuke.ask("Compare in {}?\nA: {}\nB: {}".format(
            node.name(), sources[0].name(), sources[1].name())):
        return
    previous = [viewer.activeInput(False), viewer.activeInput(True)]
    connected = []
    try:
        for slot, source in zip(slots, sources):
            if node.input(slot) == source:
                continue
            if node.input(slot) is not None:
                raise ValueError("A Viewer input changed. Reopen the pie.")
            connected.append(slot)
            node.setInput(slot, source)
            if node.input(slot) != source:
                raise ValueError("Nuke did not connect the Viewer input.")
        viewer.activateInput(slots[0])
        viewer.activateInput(slots[1], True)
    except Exception:
        for slot in connected:
            node.setInput(slot, None)
        for secondary, slot in enumerate(previous):
            if slot is not None and node.input(slot) is not None:
                viewer.activateInput(slot, bool(secondary))
        raise


def actions(nuke, widgets, action, undo):
    viewer = nuke.activeViewer()
    if viewer is None:
        return ()
    node = viewer.node()
    entries = [action("Compare selected A/B…", undo("Connect Viewer A/B", lambda: compare(nuke, viewer)))]

    channels = node.knob("channels")
    if callable(getattr(channels, "values", None)):
        def choose_channel():
            values = list(channels.values())
            if not values:
                raise ValueError("The Viewer has no available channels.")
            current = channels.value()
            value, accepted = widgets.QInputDialog.getItem(
                widgets.QApplication.activeWindow(), "Viewer Channels", "Display:",
                values, values.index(current) if current in values else 0, False)
            if accepted:
                channels.setValue(value)

        entries.append(action("Display channels…", choose_channel))

    controls = [node.knob(name) for name in ("gain", "gamma")]
    if all(knob is not None for knob in controls):
        def reset():
            if any(knob.isAnimated() for knob in controls):
                raise ValueError("Gain or gamma is animated. Reset it directly in the Viewer.")
            for knob in controls:
                knob.setValue(1.0)

        entries.append(action("Reset gain and gamma", undo("Reset Viewer display", reset)))

    if callable(getattr(viewer, "isOverlayShown", None)) and callable(getattr(viewer, "showOverlay", None)):
        entries.append(action("Toggle overlays", lambda: viewer.showOverlay(not viewer.isOverlayShown())))
    return tuple(entries)
