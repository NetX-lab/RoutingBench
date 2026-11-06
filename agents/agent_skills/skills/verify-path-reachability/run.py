"""Skill: verify-path-reachability."""
from agents.agent_skills.skills import import_skill

def run(before_dir, path):
    verify_link = import_skill("verify-link")
    for i in range(len(path) - 1):
        link = verify_link.run(before_dir, path[i], path[i + 1])
        if not link.get("exists") or not link.get("both_up"):
            return {"path": path, "reachable": False,
                    "broken_at": (path[i], path[i + 1]), "details": link}
    return {"path": path, "reachable": True}
