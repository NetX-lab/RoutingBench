"""Skill: find-candidate-paths."""
from agents.agent_skills.scripts.get_topology_paths import run as get_paths

def run(before_dir, src, dst, prefix=None):
    paths_result = get_paths(before_dir, src, dst)
    if "error" in paths_result:
        return paths_result
    feasible = []
    for p in paths_result.get("paths", []):
        if len(p) in (3, 5, 8):  # intra-pod(3), inter-pod(5), cross-DC(8)
            feasible.append({"path": p, "hops": len(p), "feasible": True})
    return {"src": src, "dst": dst, "candidate_paths": feasible[:10]}
