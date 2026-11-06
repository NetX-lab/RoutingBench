"""Tool: get_interface_config — return interface config block."""
from agents.agent_skills.scripts import load_cfg


def run(before_dir, device, intf=None, interface=None, interface_name=None):
    iface = intf or interface or interface_name
    if not iface:
        return {"error": "Missing interface argument (use 'intf', 'interface', or 'interface_name')"}
    cfg = load_cfg(before_dir, device)
    if not cfg:
        return {"error": f"Device {device} not found"}
    lines = cfg.split("\n")
    result = {"device": device, "interface": iface, "ip": None, "shutdown": False, "description": None}
    in_intf = False
    # Scan ALL occurrences of this interface block (IOS merges them)
    for line in lines:
        if line.startswith(f"interface {iface}"):
            in_intf = True
            continue
        if in_intf:
            if line.startswith("interface ") or line.strip() == "!" or (line and not line[0].isspace() and line.strip() not in ("", "!")):
                in_intf = False
                continue
            if "ip address" in line:
                parts = line.strip().split()
                if len(parts) >= 4:
                    result["ip"] = f"{parts[2]} {parts[3]}"
            if "shutdown" in line and "no shutdown" not in line:
                result["shutdown"] = True
            if "description" in line:
                result["description"] = line.strip().replace("description ", "")
    return result
