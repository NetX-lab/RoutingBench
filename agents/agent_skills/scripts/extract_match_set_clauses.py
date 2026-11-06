"""Tool: extract_match_set_clauses — extract match/set from a route-map."""
import re
from agents.agent_skills.scripts import load_cfg


def run(before_dir, device, route_map):
    cfg = load_cfg(before_dir, device)
    if not cfg:
        return {"error": f"Device {device} not found"}
    clauses = []
    current = None
    for line in cfg.split("\n"):
        m = re.match(rf"route-map {re.escape(route_map)} (\S+) (\d+)", line)
        if m:
            if current:
                clauses.append(current)
            current = {"action": m.group(1), "seq": int(m.group(2)), "match": [], "set": []}
        elif current:
            s = line.strip()
            if s.startswith("match "):
                current["match"].append(s)
            elif s.startswith("set "):
                current["set"].append(s)
            elif s == "!" or (line and not line.startswith(" ")):
                clauses.append(current)
                current = None
    if current:
        clauses.append(current)
    return {"device": device, "route_map": route_map, "clauses": clauses}
