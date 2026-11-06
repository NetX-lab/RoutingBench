"""Skill: determine-route-selection — composite skill."""
from agents.agent_skills.skills import import_skill
from agents.agent_skills.scripts.get_topology_adjacency import run as get_adj
from agents.agent_skills.scripts.get_bgp_neighbors import run as get_bgp
from agents.agent_skills.scripts.get_interface_config import run as get_intf
from agents.agent_skills.scripts.extract_match_set_clauses import run as extract_clauses


def _ip_to_neighbor(before_dir, device, next_hop_ip):
    """Resolve a next-hop IP to a neighbor device name."""
    adj = get_adj(before_dir, device)
    for n in adj.get("neighbors", []):
        intf = get_intf(before_dir, device, n["local_intf"])
        if intf.get("ip") and next_hop_ip in intf["ip"]:
            return n["neighbor"]
        peer_intf = get_intf(before_dir, n["neighbor"], n["remote_intf"])
        if peer_intf.get("ip") and next_hop_ip in peer_intf["ip"]:
            return n["neighbor"]
    return next_hop_ip


def _neighbor_advertises_prefix(before_dir, neighbor_dev, device, prefix):
    """Check if neighbor's route-map OUT toward device permits the prefix."""
    import re
    from agents.agent_skills.scripts import load_cfg
    ncfg = load_cfg(before_dir, neighbor_dev)
    if not ncfg:
        return True  # assume yes if can't check
    # Find the BGP session on neighbor pointing to our device
    # Get our device's IP on the link
    adj = get_adj(before_dir, neighbor_dev)
    our_ip = None
    for n in adj.get("neighbors", []):
        if n["neighbor"] == device:
            ic = get_intf(before_dir, neighbor_dev, n["local_intf"])
            # The peer IP (our device's IP) is on the other end
            pic = get_intf(before_dir, device, n["remote_intf"])
            our_ip = pic.get("ip", "").split()[0] if pic.get("ip") else None
            break
    if not our_ip:
        return True  # can't determine, assume yes
    # Find route-map out for this neighbor session
    rm_out = None
    lines = ncfg.split("\n")
    for line in lines:
        m = re.match(rf"\s+neighbor {re.escape(our_ip)} route-map (\S+) out", line)
        if m:
            rm_out = m.group(1)
            break
    if not rm_out:
        return True  # no outbound filter, all prefixes pass
    # Check if the route-map permits the prefix
    clauses = extract_clauses(before_dir, neighbor_dev, rm_out)
    prefix_net = prefix.split("/")[0]
    for c in clauses.get("clauses", []):
        match_lines = c.get("match", [])
        for ml in match_lines:
            if "ip address prefix-list" in ml:
                pl_name = ml.split("prefix-list")[-1].strip()
                # Check prefix-list
                for line in lines:
                    if f"ip prefix-list {pl_name}" in line and ("permit" in line or "deny" in line):
                        if prefix_net in line:
                            return "permit" in line
                        # Check if it's a range (le/ge)
                        if "le" in line or "ge" in line:
                            # Parse the prefix-list entry
                            parts = line.strip().split()
                            # Find "permit" or "deny" and the prefix
                            try:
                                action_idx = parts.index("permit") if "permit" in parts else parts.index("deny")
                                pl_prefix = parts[action_idx + 1]
                                pl_net, pl_len = pl_prefix.split("/")
                                qnet, qlen = prefix.split("/") if "/" in prefix else (prefix, "24")
                                if pl_net.split(".")[0] == qnet.split(".")[0]:
                                    return parts[action_idx] == "permit"
                            except (ValueError, IndexError):
                                pass
        if not match_lines:
            return True  # permit with no match = permit all
    return False  # default deny


def _resolve_bgp_winner(before_dir, device, prefix, lp_data, med_data):
    """Resolve which BGP neighbor wins: LP → MED → lowest RID."""
    bgp = get_bgp(before_dir, device)
    if "error" in bgp or not bgp.get("neighbors"):
        return None, None

    # Build per-neighbor LP and MED
    nei_info = []
    for nei in bgp["neighbors"]:
        nip = nei["ip"]
        neighbor_dev = _ip_to_neighbor(before_dir, device, nip)
        # Skip server neighbors
        if "server" in str(neighbor_dev):
            continue
        # Check if this neighbor actually advertises the prefix to us
        if not _neighbor_advertises_prefix(before_dir, neighbor_dev, device, prefix):
            continue
        # Check interface shutdown
        adj = get_adj(before_dir, device)
        intf_down = False
        for n in adj.get("neighbors", []):
            if n["neighbor"] == neighbor_dev:
                ic = get_intf(before_dir, device, n["local_intf"])
                if ic.get("shutdown"):
                    intf_down = True
                break
        if intf_down:
            continue

        # Get LP for this neighbor
        n_lp = 100  # default
        if lp_data.get("lp_entries"):
            for entry in lp_data["lp_entries"]:
                if entry["neighbor"] == nip:
                    n_lp = entry["lp_value"]
                    break
        # Get MED for this neighbor
        n_med = 0  # default
        if med_data.get("med_entries"):
            for entry in med_data["med_entries"]:
                if entry["neighbor"] == nip:
                    n_med = entry["med_value"]
                    break
        # Get RID of the neighbor device (for tiebreak)
        from agents.agent_skills.scripts import load_cfg
        rid = "255.255.255.255"
        ncfg = load_cfg(before_dir, neighbor_dev)
        if ncfg:
            import re
            m = re.search(r"ip address (\S+) 255\.255\.255\.255", ncfg)
            if m:
                rid = m.group(1)

        nei_info.append({
            "neighbor_ip": nip,
            "neighbor_device": neighbor_dev,
            "lp": n_lp,
            "med": n_med,
            "rid": rid,
        })

    if not nei_info:
        return None, None

    # Check LPM: does any neighbor originate the EXACT prefix (/24)?
    # A neighbor originating /24 (via bgp network or static) beats neighbors with only aggregates (/16, /8)
    prefix_net = prefix.split("/")[0] if "/" in prefix else prefix
    for ni in nei_info:
        ni["has_specific_prefix"] = False
        # Check if this neighbor has a bgp network statement or static route for the exact prefix
        nbgp = import_skill("find-bgp-network").run(before_dir, ni["neighbor_device"], prefix)
        nstatic = import_skill("find-static-route").run(before_dir, ni["neighbor_device"], prefix)
        if (nbgp.get("bgp_network") and nbgp["bgp_network"] != "not configured"
                and prefix_net in str(nbgp.get("bgp_network", ""))):
            ni["has_specific_prefix"] = True
        if nstatic.get("static_routes"):
            for sr in nstatic["static_routes"]:
                if sr.get("network") == prefix_net:
                    ni["has_specific_prefix"] = True

    # If any neighbor has the specific /24, filter to only those (LPM wins)
    specific_neis = [ni for ni in nei_info if ni["has_specific_prefix"]]
    if specific_neis:
        nei_info = specific_neis

    # Sort: highest LP → lowest MED → lowest RID
    nei_info.sort(key=lambda x: (-x["lp"], x["med"], tuple(int(o) for o in x["rid"].split("."))))
    winner = nei_info[0]
    return winner["neighbor_device"], winner


def run(before_dir, device, prefix):
    static = import_skill("find-static-route").run(before_dir, device, prefix)
    bgp_net = import_skill("find-bgp-network").run(before_dir, device, prefix)
    lp = import_skill("find-lp-for-prefix").run(before_dir, device, prefix)
    med = import_skill("find-med-for-prefix").run(before_dir, device, prefix)
    agg = import_skill("find-prefix-aggregation").run(before_dir, device, prefix)

    winner = "bgp_default"
    next_hop = None
    next_hop_device = None
    selected_neighbor = None

    if static.get("static_routes"):
        winner = "static_route"
        next_hop = static["static_routes"][0]["next_hop"]
        next_hop_device = _ip_to_neighbor(before_dir, device, next_hop)
    elif bgp_net.get("bgp_network") and bgp_net["bgp_network"] != "not configured":
        winner = "bgp_network"

    # For bgp_default, resolve which neighbor wins
    if winner == "bgp_default":
        resolved_dev, resolved_info = _resolve_bgp_winner(before_dir, device, prefix, lp, med)
        if resolved_dev:
            next_hop_device = resolved_dev
            selected_neighbor = resolved_info

    result = {"device": device, "prefix": prefix, "winner": winner,
              "next_hop": next_hop, "next_hop_device": next_hop_device,
              "static": static, "bgp_network": bgp_net,
              "lp": lp, "med": med, "aggregation": agg}
    if selected_neighbor:
        result["selected_neighbor"] = selected_neighbor
    result["note"] = (f"Traffic for {prefix} on {device}: {winner}"
                      + (f" → {next_hop_device}" if next_hop_device else "")
                      + (f" (LP={selected_neighbor['lp']}, MED={selected_neighbor['med']}, RID={selected_neighbor['rid']})"
                         if selected_neighbor else ""))
    return result
