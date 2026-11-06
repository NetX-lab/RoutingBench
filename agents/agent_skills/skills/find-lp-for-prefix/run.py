"""Skill: find-lp-for-prefix — determine LP for a prefix on a device."""
from agents.agent_skills.scripts.get_bgp_neighbors import run as get_bgp_neighbors
from agents.agent_skills.scripts.extract_match_set_clauses import run as extract_clauses


def run(before_dir, device, prefix):
    bgp = get_bgp_neighbors(before_dir, device)
    if "error" in bgp:
        return bgp
    results = []
    for nei in bgp.get("neighbors", []):
        rm_in = nei.get("route_map_in")
        if not rm_in:
            continue
        clauses = extract_clauses(before_dir, device, rm_in)
        for c in clauses.get("clauses", []):
            lp_sets = [s for s in c.get("set", []) if "local-preference" in s]
            if lp_sets:
                lp_val = int(lp_sets[0].split()[-1])
                results.append({"neighbor": nei["ip"], "route_map": rm_in,
                                "lp_value": lp_val, "match": c.get("match", []),
                                "seq": c.get("seq")})
    if not results:
        return {"device": device, "prefix": prefix, "lp_value": 100,
                "mechanism": "default (no route-map sets LP)"}
    return {"device": device, "prefix": prefix, "lp_entries": results}
