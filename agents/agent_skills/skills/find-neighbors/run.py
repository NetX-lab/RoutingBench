"""Skill: find-neighbors."""
from agents.agent_skills.scripts.get_topology_adjacency import run as get_topo_adj
from agents.agent_skills.scripts.get_interface_config import run as get_intf

def run(before_dir, device):
    adj = get_topo_adj(before_dir, device)
    if "error" in adj:
        return adj
    enriched = []
    for n in adj.get("neighbors", []):
        intf_info = get_intf(before_dir, device, n["local_intf"])
        enriched.append({**n, "ip": intf_info.get("ip"), "shutdown": intf_info.get("shutdown", False)})
    return {"device": device, "neighbors": enriched}
