"""Tool: find_references — return config lines referencing a symbol."""
from agents.agent_skills.scripts import load_cfg


def run(before_dir, device, symbol):
    cfg = load_cfg(before_dir, device)
    if not cfg:
        return {"error": f"Device {device} not found"}
    refs = []
    for i, line in enumerate(cfg.split("\n")):
        if symbol in line:
            refs.append({"line_num": i + 1, "line": line.strip()})
    return {"device": device, "symbol": symbol, "references": refs}
