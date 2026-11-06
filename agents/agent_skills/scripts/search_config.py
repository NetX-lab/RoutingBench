"""Tool: search_config — regex search across a device's .cfg file."""
import re
from agents.agent_skills.scripts import load_cfg


def run(before_dir, device, regex, context_lines=2):
    cfg = load_cfg(before_dir, device)
    if not cfg:
        return {"error": f"Device {device} not found"}
    lines = cfg.split("\n")
    matches = []
    pat = re.compile(regex, re.IGNORECASE)
    for i, line in enumerate(lines):
        if pat.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            matches.append({"line_num": i + 1, "match": line.strip(),
                             "context": "\n".join(lines[start:end])})
    return {"device": device, "pattern": regex, "matches": matches}
