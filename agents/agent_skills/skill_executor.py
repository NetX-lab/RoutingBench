"""Skill executor: dispatches skill invocations to skills/{name}/run.py.

Each skill folder contains:
  - SKILL.md: documentation for LLM (what the skill does, what tools it uses)
  - run.py: executable script that calls scripts/ tools and returns structured result
"""
import os
from agents.agent_skills.skills import import_skill

_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


def execute_skill(skill_name, before_dir, **kwargs):
    """Execute a skill by importing its run.py and calling run()."""
    try:
        mod = import_skill(skill_name)
        return mod.run(before_dir, **kwargs)
    except Exception as e:
        return {"error": f"Skill {skill_name} failed: {e}"}


def get_skill_descriptions():
    """Read SKILL.md files to build skill descriptions for the agent prompt."""
    lines = []
    for name in sorted(os.listdir(_SKILLS_DIR)):
        skill_dir = os.path.join(_SKILLS_DIR, name)
        if not os.path.isdir(skill_dir) or name.startswith("_"):
            continue
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if os.path.exists(skill_md):
            with open(skill_md) as f:
                content = f.read()
            desc = ""
            for line in content.split("\n"):
                if line.startswith("description:"):
                    desc = line.replace("description:", "").strip()
                    break
            if desc:
                lines.append(f"  - **{name}**: {desc}")
    return "Available skills:\n" + "\n".join(lines)
