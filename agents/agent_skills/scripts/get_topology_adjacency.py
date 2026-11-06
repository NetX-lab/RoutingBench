"""Tool: get_topology_adjacency — return neighbors from topology JSON."""
from agents.agent_skills.scripts import load_topo


def run(before_dir, device):
    topo = load_topo(before_dir)
    if not topo:
        return {"error": "Topology not found"}
    neighbors = []
    for edge in topo.get("edges", []):
        n1, n2 = edge["node1"], edge["node2"]
        if n1["hostname"] == device and "server" not in n2["hostname"]:
            neighbors.append({"neighbor": n2["hostname"],
                               "local_intf": n1["interfaceName"],
                               "remote_intf": n2["interfaceName"]})
        elif n2["hostname"] == device and "server" not in n1["hostname"]:
            neighbors.append({"neighbor": n1["hostname"],
                               "local_intf": n2["interfaceName"],
                               "remote_intf": n1["interfaceName"]})
    return {"device": device, "neighbors": neighbors}
