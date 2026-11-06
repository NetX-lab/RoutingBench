"""Skill: find-bgp-network."""
from agents.agent_skills.scripts.search_config import run as search_config

def run(before_dir, device, prefix):
    prefix_net = prefix.split("/")[0] if "/" in prefix else prefix
    result = search_config(before_dir, device, f"network {prefix_net}")
    matches = result.get("matches", [])
    if not matches:
        return {"device": device, "prefix": prefix, "bgp_network": "not configured"}
    return {"device": device, "prefix": prefix, "bgp_network": matches[0]["context"]}
