"""Tool: read_config_block — extract a named config block."""
import re
from agents.agent_skills.scripts import load_cfg


def run(before_dir, device, block_type, name):
    cfg = load_cfg(before_dir, device)
    if not cfg:
        return {"error": f"Device {device} not found"}
    lines = cfg.split("\n")
    result_lines = []

    if block_type == "route-map":
        target = f"route-map {name}"
        in_block = False
        for line in lines:
            if line.startswith(target):
                in_block = True
            if in_block:
                result_lines.append(line)
                if line.strip() == "!" or (line.startswith("route-map") and not line.startswith(target) and result_lines):
                    if line.startswith("route-map") and not line.startswith(target):
                        result_lines.pop()
                    break
    elif block_type == "prefix-list":
        for line in lines:
            if f"ip prefix-list {name}" in line:
                result_lines.append(line)
    elif block_type == "router bgp":
        in_block = False
        for line in lines:
            if line.startswith("router bgp"):
                in_block = True
            if in_block:
                result_lines.append(line)
                if line.strip() == "!" and len(result_lines) > 1:
                    break
    elif block_type == "community-list":
        for line in lines:
            if f"ip community-list {name}" in line:
                result_lines.append(line)

    return {"device": device, "block_type": block_type, "name": name,
            "content": "\n".join(result_lines) if result_lines else "[not found]"}
