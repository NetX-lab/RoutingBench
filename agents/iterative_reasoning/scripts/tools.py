"""Multi-round tools: get_topology and get_device_config."""
import os, json


def get_topology(before_dir):
    """Return topology as structured text (router links only, no servers)."""
    topo_file = os.path.join(before_dir, "example_layer1_topology.json")
    with open(topo_file) as f:
        topo = json.load(f)
    lines = []
    for edge in topo.get("edges", []):
        n1, n2 = edge["node1"], edge["node2"]
        if "server" in n1["hostname"] or "server" in n2["hostname"]:
            continue
        lines.append(f"{n1['hostname']}({n1['interfaceName']}) <-> {n2['hostname']}({n2['interfaceName']})")
    return "\n".join(lines)


def get_device_config(before_dir, device_name, change_diffs=None, phase="before"):
    """Return full .cfg for a device. If phase='after', apply change_diffs first."""
    cfg_file = os.path.join(before_dir, "configs", f"{device_name}.cfg")
    if not os.path.exists(cfg_file):
        return f"[ERROR] Device '{device_name}' not found."
    with open(cfg_file) as f:
        content = f.read()
    
    if phase == "after" and change_diffs:
        for d in change_diffs:
            if d["device"] == device_name:
                lines = content.rstrip().split("\n")
                idx = len(lines)
                for i in range(len(lines)-1, -1, -1):
                    if lines[i].strip() == "end":
                        idx = i; break
                lines = lines[:idx] + ["!"] + d["add_lines"] + ["!"] + lines[idx:]
                content = "\n".join(lines) + "\n"
    
    return content
