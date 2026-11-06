"""Skill: find-med-for-prefix — determine MED for a prefix on a device."""
from agents.agent_skills.scripts.get_bgp_neighbors import run as get_bgp_neighbors
from agents.agent_skills.scripts.extract_match_set_clauses import run as extract_clauses


def run(before_dir, device, prefix):
    bgp = get_bgp_neighbors(before_dir, device)
    if "error" in bgp:
        return bgp
    results = []
    for nei in bgp.get("neighbors", []):
        for direction in ["route_map_in", "route_map_out"]:
            rm = nei.get(direction)
            if not rm:
                continue
            clauses = extract_clauses(before_dir, device, rm)
            for c in clauses.get("clauses", []):
                med_sets = [s for s in c.get("set", []) if "metric" in s.lower() and "local" not in s.lower()]
                if med_sets:
                    med_val = int(med_sets[0].split()[-1])
                    results.append({"neighbor": nei["ip"], "route_map": rm,
                                    "direction": direction.replace("route_map_", ""),
                                    "med_value": med_val})
    if not results:
        return {"device": device, "prefix": prefix, "med": "not configured"}
    return {"device": device, "prefix": prefix, "med_entries": results}
