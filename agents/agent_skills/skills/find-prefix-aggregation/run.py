"""Skill: find-prefix-aggregation."""
from agents.agent_skills.scripts.search_config import run as search_config

def run(before_dir, device, prefix):
    result = search_config(before_dir, device, "aggregate-address")
    matches = result.get("matches", [])
    if not matches:
        return {"device": device, "prefix": prefix, "aggregation": "not configured"}
    aggs = [{"line": m["match"], "summary_only": "summary-only" in m["match"]} for m in matches]
    return {"device": device, "prefix": prefix, "aggregates": aggs}
