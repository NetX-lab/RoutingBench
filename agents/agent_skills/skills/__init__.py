"""Skills package — dynamic skill import."""
import importlib


def import_skill(skill_name):
    """Import a skill's run module by name (e.g., 'find-lp-for-prefix')."""
    module_name = f"agents.agent_skills.skills.{skill_name.replace('-', '_')}.run"
    # Try with hyphens as directory name
    import os, sys
    skill_dir = os.path.join(os.path.dirname(__file__), skill_name)
    if os.path.isdir(skill_dir):
        run_path = os.path.join(skill_dir, "run.py")
        if os.path.exists(run_path):
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"skill_{skill_name}", run_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise ImportError(f"Skill {skill_name} not found")
