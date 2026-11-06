"""Skill: find-layer-devices."""
from agents.agent_skills.scripts.get_layer_devices import run as get_devs

def run(before_dir, layer, scope=None):
    return get_devs(before_dir, layer, scope)
