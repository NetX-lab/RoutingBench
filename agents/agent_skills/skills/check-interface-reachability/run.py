"""Skill: check-interface-reachability."""
from agents.agent_skills.scripts.get_interface_config import run as get_interface_config

def run(before_dir, device, intf):
    return get_interface_config(before_dir, device, intf)
