"""Skill: find-static-route."""
from agents.agent_skills.scripts.search_config import run as search_config

def run(before_dir, device, prefix):
    prefix_net = prefix.split("/")[0] if "/" in prefix else prefix
    result = search_config(before_dir, device, f"ip route {prefix_net}")
    matches = result.get("matches", [])
    if not matches:
        return {"device": device, "prefix": prefix, "static_route": "not configured"}
    entries = []
    for m in matches:
        parts = m["match"].split()
        if len(parts) >= 5:
            entries.append({"network": parts[2], "mask": parts[3], "next_hop": parts[4]})
    return {"device": device, "prefix": prefix, "static_routes": entries}
