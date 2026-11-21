"""Plan and apply undoable Node Graph layout changes."""


def layout(nodes, mode):
    """Return planned positions without modifying the graph."""
    nodes = sorted(nodes, key=lambda node: (node.ypos(), node.xpos(), node.name()))
    if len(nodes) < 2:
        raise ValueError("Select at least two nodes.")

    if mode == "left":
        left = min(node.xpos() for node in nodes)
        return [(node, left, node.ypos()) for node in nodes]
    if mode == "top":
        top = nodes[0].ypos()
        return [(node, node.xpos(), top) for node in nodes]
    if mode == "space":
        if len(nodes) < 3:
            raise ValueError("Select at least three nodes to distribute.")
        span = nodes[-1].ypos() - nodes[0].ypos()
        occupied = sum(node.screenHeight() for node in nodes[:-1])
        gap = (span - occupied) / (len(nodes) - 1)
        if gap < 0:
            raise ValueError("Move the endpoints farther apart before distributing.")
        y = nodes[0].ypos()
        plan = []
        for node in nodes:
            plan.append((node, node.xpos(), round(y)))
            y += node.screenHeight() + gap
        return plan

    successors = {}
    roots = []
    for node in nodes:
        inputs = [node.input(i) for i in range(node.inputs()) if node.input(i) in nodes]
        if not inputs:
            roots.append(node)
        elif len(inputs) != 1 or inputs[0] in successors:
            raise ValueError("Straightening requires one non-branching selection.")
        else:
            successors[inputs[0]] = node
    if len(roots) != 1:
        raise ValueError("Straightening requires one connected chain.")
    root = roots[0]
    center = root.xpos() + root.screenWidth() / 2
    plan = []
    node = root
    y = root.ypos()
    while node is not None and len(plan) < len(nodes):
        y = max(y, node.ypos())
        plan.append((node, round(center - node.screenWidth() / 2), y))
        y += node.screenHeight() + 36
        node = successors.get(node)
    if node is not None or len(plan) != len(nodes):
        raise ValueError("Straightening requires one connected chain.")
    return plan


def actions(nuke, action, undo):
    def apply(label, mode):
        nodes = [node for node in nuke.selectedNodes() if node.Class() != "BackdropNode"]
        plan = [(node, x, y) for node, x, y in layout(nodes, mode)
                if (x, y) != (node.xpos(), node.ypos())]
        if not plan:
            nuke.message("The selected nodes already match this layout.")
            return
        def move():
            for node, x, y in plan:
                node.setXYpos(int(x), int(y))

        undo(label, move)()

    def backdrop():
        nodes = [node for node in nuke.selectedNodes() if node.Class() != "BackdropNode"]
        if not nodes:
            raise ValueError("Select the nodes to put inside the backdrop.")
        left = min(node.xpos() for node in nodes) - 32
        top = min(node.ypos() for node in nodes) - 58
        right = max(node.xpos() + node.screenWidth() for node in nodes) + 32
        bottom = max(node.ypos() + node.screenHeight() for node in nodes) + 32
        label = nuke.getInput("Backdrop label", "")
        if label is not None:
            undo("Fit backdrop", lambda: nuke.nodes.BackdropNode(
                xpos=int(left), ypos=int(top), bdwidth=int(right - left),
                bdheight=int(bottom - top), label=label))()

    entries = (("Align left", "left"), ("Align top", "top"),
               ("Distribute vertically", "space"), ("Straighten branch", "chain"))
    return tuple(action(label, lambda label=label, mode=mode: apply(label, mode))
                 for label, mode in entries) + (action("Fit backdrop…", backdrop),)
