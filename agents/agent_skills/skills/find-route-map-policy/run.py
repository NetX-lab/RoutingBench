"""Skill: find-route-map-policy."""
from agents.agent_skills.scripts.get_bgp_neighbors import run as get_bgp_neighbors
from agents.agent_skills.scripts.extract_match_set_clauses import run as extract_clauses

def run(before_dir, device, neighbor_ip):
    bgp = get_bgp_neighbors(before_dir, device)
    if "error" in bgp:
        return bgp
    for nei in bgp.get("neighbors", []):
        if nei["ip"] == neighbor_ip:
            policies = {"neighbor": neighbor_ip, "remote_as": nei["remote_as"]}
            for d in ["in", "out"]:
                rm = nei.get(f"route_map_{d}")
                if rm:
                    clauses = extract_clauses(before_dir, device, rm)
                    policies[f"route_map_{d}"] = {"name": rm, "clauses": clauses.get("clauses", [])}
            return {"device": device, **policies}
    return {"device": device, "neighbor": neighbor_ip, "error": "neighbor not found"}
