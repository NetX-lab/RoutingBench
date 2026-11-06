"""Skill: verify-bgp-session."""
from agents.agent_skills.scripts.get_bgp_neighbors import run as get_bgp

def run(before_dir, device, neighbor):
    bgp_dev = get_bgp(before_dir, device)
    bgp_nei = get_bgp(before_dir, neighbor)
    dev_has = any(n["ip"] for n in bgp_dev.get("neighbors", []))
    nei_has = any(n["ip"] for n in bgp_nei.get("neighbors", []))
    return {"device": device, "neighbor": neighbor,
            "device_bgp": bgp_dev, "neighbor_bgp": bgp_nei,
            "mutual": dev_has and nei_has}
