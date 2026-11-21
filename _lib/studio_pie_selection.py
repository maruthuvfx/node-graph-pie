"""Follow explicit input connections within the current Nuke graph."""


def reachable(seeds, edges):
    visited = set(seeds)
    pending = list(visited)
    while pending:
        for neighbor in edges[pending.pop()]:
            if neighbor not in visited:
                visited.add(neighbor)
                pending.append(neighbor)
    return visited


def trace(nuke, mode):
    nodes = list(nuke.allNodes())
    seeds = [node for node in nodes if node.isSelected()]
    if not seeds or (mode == "between" and len(seeds) != 2):
        nuke.message("Select two anchor nodes." if mode == "between" else "Select at least one node.")
        return

    upstream = {node: set() for node in nodes}
    downstream = {node: set() for node in nodes}
    for target in nodes:
        for index in range(target.inputs()):
            source = target.input(index)
            if source in upstream:
                upstream[target].add(source)
                downstream[source].add(target)

    if mode == "between":
        first, last = seeds
        forward = reachable([first], downstream)
        if last not in forward:
            first, last = last, first
            forward = reachable([first], downstream)
        if last not in forward:
            nuke.message("There is no directed input path between the selected anchors.")
            return
        result = forward & reachable([last], upstream)
    elif mode in {"upstream", "reads"}:
        result = reachable(seeds, upstream)
        if mode == "reads":
            result = {node for node in result if node.Class() in {"Read", "DeepRead", "ReadGeo", "ReadGeo2"}}
    else:
        result = reachable(seeds, downstream)
        if mode == "writes":
            result = {node for node in result if node.Class() in {"Write", "DeepWrite", "WriteGeo"}}

    if not result:
        nuke.message("No matching nodes were found along the selected connections.")
        return
    for node in nodes:
        desired = node in result
        if node.isSelected() != desired:
            node.setSelected(desired)
