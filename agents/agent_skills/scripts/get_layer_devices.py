"""Tool: get_layer_devices — list devices in a topology layer."""
from agents.agent_skills.scripts import load_topo


def run(before_dir, layer, scope=None):
    topo = load_topo(before_dir)
    if not topo:
        return {"error": "Topology not found"}
    devices = set()
    for edge in topo.get("edges", []):
        for node in [edge["node1"], edge["node2"]]:
            h = node["hostname"]
            if "server" in h:
                continue
            if layer == "edge" and h.startswith("edge-"):
                if scope is None or f"-p{scope}-" in h:
                    devices.add(h)
            elif layer == "agg" and h.startswith("agg-"):
                if scope is None or f"-p{scope}-" in h:
                    devices.add(h)
            elif layer == "core" and h.startswith("core-"):
                devices.add(h)
    return {"layer": layer, "scope": scope, "devices": sorted(devices)}
