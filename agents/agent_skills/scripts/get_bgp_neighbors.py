"""Tool: get_bgp_neighbors — parse BGP neighbors with peer device names.
Supports both FRR (frr.conf) and Arista EOS (.cfg) formats.
"""
import re
from agents.agent_skills.scripts import load_cfg


def run(before_dir, device):
    cfg = load_cfg(before_dir, device)
    if not cfg:
        return {"error": f"Device {device} not found"}

    is_arista = "template peer" in cfg or "inherit peer" in cfg
    asn = None
    neighbors = []

    m = re.search(r"router bgp (\d+)", cfg)
    if m:
        asn = int(m.group(1))

    if is_arista:
        neighbors = _parse_arista(cfg)
    else:
        neighbors = _parse_frr(cfg)

    # Filter: IPv4 only, with peer_device (= description found)
    result = [n for n in neighbors
              if re.match(r"\d+\.\d+\.\d+\.\d+", n["ip"]) and n.get("peer_device")]

    return {"device": device, "asn": asn, "neighbors": result,
            "all_neighbor_count": len(neighbors), "format": "arista" if is_arista else "frr"}


def _parse_frr(cfg):
    """Parse FRR-style: neighbor X remote-as / peer-group / description on same-level lines."""
    neighbors = []
    for line in cfg.split("\n"):
        m = re.match(r"\s+neighbor (\d+\.\d+\.\d+\.\d+) remote-as (\d+)", line)
        if m:
            neighbors.append({"ip": m.group(1), "remote_as": int(m.group(2)),
                               "peer_group": None, "peer_device": None,
                               "route_map_in": None, "route_map_out": None})
        m = re.match(r"\s+neighbor (\d+\.\d+\.\d+\.\d+) peer-group (\S+)", line)
        if m:
            ip, pg = m.group(1), m.group(2)
            for n in neighbors:
                if n["ip"] == ip:
                    n["peer_group"] = pg
                    break
            else:
                neighbors.append({"ip": ip, "remote_as": None, "peer_group": pg,
                                   "peer_device": None, "route_map_in": None, "route_map_out": None})
        m = re.match(r"\s+neighbor (\d+\.\d+\.\d+\.\d+) description\s+(.+)", line)
        if m:
            ip, desc = m.group(1), m.group(2).strip()
            for n in neighbors:
                if n["ip"] == ip:
                    n["peer_device"] = desc.lower()
                    break
        m = re.match(r"\s+neighbor (\d+\.\d+\.\d+\.\d+) route-map (\S+) (in|out)", line)
        if m:
            ip, rm, d = m.group(1), m.group(2), m.group(3)
            for n in neighbors:
                if n["ip"] == ip:
                    n[f"route_map_{d}"] = rm
                    break
    return neighbors


def _parse_arista(cfg):
    """Parse Arista EOS-style: indented neighbor blocks with description/inherit."""
    neighbors = []
    cur = None
    for line in cfg.split("\n"):
        stripped = line.strip()
        # New neighbor block: "  neighbor 10.x.x.x"
        m = re.match(r"\s{2}neighbor (\d+\.\d+\.\d+\.\d+)\s*$", line)
        if m:
            cur = {"ip": m.group(1), "remote_as": None, "peer_group": None,
                   "peer_device": None, "route_map_in": None, "route_map_out": None}
            neighbors.append(cur)
            continue
        if cur is None:
            continue
        # End of block: less-indented line or new neighbor
        if line and not line.startswith("   ") and not line.startswith("\t"):
            cur = None
            continue
        # Block properties
        m = re.match(r"remote-as (\d+)", stripped)
        if m:
            cur["remote_as"] = int(m.group(1))
        m = re.match(r"description\s+(.+)", stripped)
        if m:
            cur["peer_device"] = m.group(1).strip().lower()
        m = re.match(r"inherit peer (\S+)", stripped)
        if m:
            cur["peer_group"] = m.group(1)
        m = re.match(r"route-map (\S+) (in|out)", stripped)
        if m:
            cur[f"route_map_{m.group(2)}"] = m.group(1)
    return neighbors
