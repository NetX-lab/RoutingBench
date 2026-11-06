"""Skill: verify-link."""
from agents.agent_skills.scripts.get_topology_adjacency import run as get_adj
from agents.agent_skills.scripts.get_interface_config import run as get_intf

def run(before_dir, device1, device2):
    adj = get_adj(before_dir, device1)
    link = None
    for n in adj.get("neighbors", []):
        if n["neighbor"] == device2:
            link = n
            break
    if not link:
        return {"device1": device1, "device2": device2, "exists": False}
    intf1 = get_intf(before_dir, device1, link["local_intf"])
    intf2 = get_intf(before_dir, device2, link["remote_intf"])
    return {"device1": device1, "device2": device2, "exists": True,
            "intf1": link["local_intf"], "intf2": link["remote_intf"],
            "intf1_shutdown": intf1.get("shutdown", False),
            "intf2_shutdown": intf2.get("shutdown", False),
            "both_up": not intf1.get("shutdown") and not intf2.get("shutdown")}
