#!/usr/bin/env python3
"""
Generate Advanced Configuration Changes for fat-tree topologies.

Before state (shared, one directory):
  - Base config with `maximum-paths 8` removed (single BGP best path)
  - Explicit LP=200 pinning on every edge inbound from agg0
    → all inter-pod traffic: edge → agg0 → core0 (tiebreak) → dst

Changes (each modifies exactly ONE device):
  Edge-level (shift agg): LP, Static Route, Intf Shutdown
  Agg-level (shift core): MED, BGP Network, Prefix Aggregation

Two non-obvious conventions used by every change generator below:

- ``bgp_network`` change includes an ``ip route`` line.
  Cisco IOS only honors the ``network`` statement under ``router bgp`` if
  the exact prefix is already present in the local routing table (typically
  a static route or a directly connected interface). Without an
  accompanying ``ip route``, the BGP advertisement would silently never
  appear. We therefore emit *both* the ``ip route`` and the
  ``router bgp ... network ...`` line, which is also how operators do it
  in practice. (See ``_gen_bgp_network`` below.)

- Changes are applied by *appending* lines (``add_lines``) rather than
  rewriting blocks. Cisco IOS evaluates configuration in the order it is
  parsed, and the *most recently parsed* statement that matches a flow
  wins (e.g., the latest ``route-map ... permit <seq>``, the latest BGP
  neighbor command, the latest ``ip route`` for the same prefix).
  Operators in production push incremental CLI commands that override
  earlier configuration for the same flow rather than re-pushing a
  complete configuration file. Our ``add_lines`` semantics mirror this:
  each change appends new lines to the existing ``.cfg``, and the
  resulting configuration is what would be running on the box after the
  operator hits Enter.

Usage:
    python -m network.IntraDCNet <k> [--num-pairs 20] [--num-changes 5]
"""

import os, sys, json, shutil, random
from argparse import ArgumentParser
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

from network.TopoBase import (
    p2p_edge_agg_ips, p2p_agg_core_ips,
    asn_edge, asn_agg, asn_core,
    build_links, generate_configs,
)
from network.query_pairs import load_query_pairs

random.seed(42)

@dataclass
class PathSpec:
    src_edge: Tuple[int, int]; dst_edge: Tuple[int, int]
    agg_idx: int; core_idx: int
    def to_node_list(self):
        sp, se = self.src_edge; dp, de = self.dst_edge
        return [f"edge-p{sp}-e{se}", f"agg-p{sp}-a{self.agg_idx}",
                f"core-g{self.agg_idx}-c{self.core_idx}",
                f"agg-p{dp}-a{self.agg_idx}", f"edge-p{dp}-e{de}"]
    def to_node_list_with_servers(self):
        sp, se = self.src_edge; dp, de = self.dst_edge
        return [f"server-p{sp}-e{se}-h0"] + self.to_node_list() + [f"server-p{dp}-e{de}-h0"]
    def to_dict(self):
        return {"agg_idx": self.agg_idx, "core_idx": self.core_idx,
                "node_list": self.to_node_list(),
                "node_list_with_servers": self.to_node_list_with_servers()}

def select_pairs(k, num=20, pairs: Optional[List[Tuple[Tuple[int, int], Tuple[int, int]]]] = None):
    if pairs is not None:
        return pairs
    half = k // 2
    edges = [(p, e) for p in range(k) for e in range(half)]
    inter = [(a, b) for i, a in enumerate(edges) for b in edges[i+1:] if a[0] != b[0]]
    random.shuffle(inter)
    return inter[:num]

def build_link_map(links):
    lm = {}
    for link in links:
        n1, n2 = link["node1"]["hostname"], link["node2"]["hostname"]
        i1, i2 = link["node1"]["interfaceName"], link["node2"]["interfaceName"]
        lm[(n1, n2)] = (i1, i2); lm[(n2, n1)] = (i2, i1)
    return lm

def create_before_dir(k):
    base = f"data/fattree/fattreek{str(k).zfill(3)}"
    before = os.path.join(base, "before")
    if os.path.exists(before): shutil.rmtree(before)
    half = k // 2
    cfg_src = os.path.join(base, "configs"); cfg_dst = os.path.join(before, "configs")
    os.makedirs(cfg_dst)
    for fn in os.listdir(cfg_src):
        with open(os.path.join(cfg_src, fn)) as f: content = f.read()
        content = content.replace("  maximum-paths 8\n", "")
        if fn.startswith("edge-") and fn.endswith(".cfg"):
            hostname = fn[:-4]; parts = hostname.split("-")
            pod = int(parts[1][1:]); eidx = int(parts[2][1:])
            _, agg0_ip = p2p_edge_agg_ips(pod, eidx, 0)
            asn = asn_edge(pod, eidx, k)
            pin = ["!", "route-map RM_PIN permit 10", " set local-preference 200",
                   "route-map RM_PIN permit 20", "!",
                   f"router bgp {asn}", " address-family ipv4",
                   f"  neighbor {agg0_ip} route-map RM_PIN in", "!"]
            lines = content.rstrip().split("\n")
            idx = len(lines)
            for i in range(len(lines)-1,-1,-1):
                if lines[i].strip() == "end": idx = i; break
            lines = lines[:idx] + pin + lines[idx:]
            content = "\n".join(lines) + "\n"
        with open(os.path.join(cfg_dst, fn), "w") as f: f.write(content)
    hosts_src = os.path.join(base, "hosts"); hosts_dst = os.path.join(before, "hosts")
    if os.path.isdir(hosts_src): shutil.copytree(hosts_src, hosts_dst)
    topo = os.path.join(base, "example_layer1_topology.json")
    if os.path.exists(topo): shutil.copy2(topo, os.path.join(before, "example_layer1_topology.json"))
    print(f"[OK] Created before/ with LP=200 pinning on all edges → agg0")

# ── 6 Change generators (single device each) ──

def _gen_lp(src_edge, dst_edge, k):
    sp, se = src_edge; half = k // 2; out = []
    for a in range(1, half):
        _, agg_ip = p2p_edge_agg_ips(sp, se, a)
        rm = f"RM_LP_AGG{a}"
        out.append({"after": (a, 0), "diff": {"device": f"edge-p{sp}-e{se}",
            "add_lines": [f"route-map {rm} permit 10", f" set local-preference 300",
                f"route-map {rm} permit 20", f"!",
                f"router bgp {asn_edge(sp, se, k)}", f" address-family ipv4",
                f"  neighbor {agg_ip} route-map {rm} in"],
            "description": f"LP=300 on edge inbound from agg{a} → shift to agg{a}"}})
    for c in range(1, half):
        _, core_ip = p2p_agg_core_ips(sp, 0, c)
        rm = f"RM_LP_CORE{c}"
        out.append({"after": (0, c), "diff": {"device": f"agg-p{sp}-a0",
            "add_lines": [f"route-map {rm} permit 10", f" set local-preference 200",
                f"route-map {rm} permit 20", f"!",
                f"router bgp {asn_agg(sp)}", f" address-family ipv4",
                f"  neighbor {core_ip} route-map {rm} in"],
            "description": f"LP=200 on agg0 inbound from core{c} → shift to core{c}"}})
    return out

def _gen_med(src_edge, dst_edge, k):
    sp, se = src_edge; half = k // 2; out = []
    if half < 2: return out
    _, core0_ip = p2p_agg_core_ips(sp, 0, 0)
    rm = "RM_MED_CORE0"
    out.append({"after": (0, 1), "diff": {"device": f"agg-p{sp}-a0",
        "add_lines": [f"route-map {rm} permit 10", f" set metric 9999",
            f"route-map {rm} permit 20", f"!",
            f"router bgp {asn_agg(sp)}", f" address-family ipv4",
            f"  neighbor {core0_ip} route-map {rm} in"],
        "description": "MED=9999 on agg0 inbound from core0 → shift to core1"}})
    return out

def _gen_static(src_edge, dst_edge, k):
    sp, se = src_edge; dp, de = dst_edge; half = k // 2
    dst_net = f"1.{dp}.{de}.0"; out = []
    for a in range(1, half):
        _, agg_ip = p2p_edge_agg_ips(sp, se, a)
        out.append({"after": (a, 0), "diff": {"device": f"edge-p{sp}-e{se}",
            "add_lines": [f"ip route {dst_net} 255.255.255.0 {agg_ip}"],
            "description": f"Static /24 on edge → agg{a}"}})
    for c in range(1, half):
        _, core_ip = p2p_agg_core_ips(sp, 0, c)
        out.append({"after": (0, c), "diff": {"device": f"agg-p{sp}-a0",
            "add_lines": [f"ip route {dst_net} 255.255.255.0 {core_ip}"],
            "description": f"Static /24 on agg0 → core{c}"}})
    return out

def _gen_bgp_network(src_edge, dst_edge, k):
    # Cisco IOS only advertises a ``network ...`` statement if the exact
    # prefix is already in the routing table, so we pair it with an
    # ``ip route`` line. See module docstring for the full rationale.
    sp, se = src_edge; dp, de = dst_edge; half = k // 2
    dst_net = f"1.{dp}.{de}.0"; out = []
    for a in range(half):
        for c in range(half):
            if a == 0 and c == 0: continue
            _, core_ip = p2p_agg_core_ips(sp, a, c)
            agg = f"agg-p{sp}-a{a}"
            out.append({"after": (a, c), "diff": {"device": agg,
                "add_lines": [f"ip route {dst_net} 255.255.255.0 {core_ip}", f"!",
                    f"router bgp {asn_agg(sp)}", f" address-family ipv4",
                    f"  network {dst_net} mask 255.255.255.0"],
                "description": f"BGP network /24 + static on {agg} → core-g{a}-c{c}"}})
    return out

def _gen_prefix_agg(src_edge, dst_edge, k):
    sp, se = src_edge; dp, de = dst_edge; half = k // 2
    dst_net = f"1.{dp}.{de}.0"; out = []
    for a in range(half):
        for c in range(half):
            if a == 0 and c == 0: continue
            _, core_ip = p2p_agg_core_ips(sp, a, c)
            agg = f"agg-p{sp}-a{a}"
            out.append({"after": (a, c), "diff": {"device": agg,
                "add_lines": [f"ip route {dst_net} 255.255.255.0 {core_ip}", f"!",
                    f"router bgp {asn_agg(sp)}", f" address-family ipv4",
                    f"  network {dst_net} mask 255.255.255.0",
                    f"  aggregate-address {dst_net} 255.255.255.0 as-set"],
                "description": f"Prefix agg /24 + network + static on {agg} → core-g{a}-c{c}"}})
    return out

def _gen_intf_shutdown(src_edge, dst_edge, k, link_map):
    sp, se = src_edge; half = k // 2; out = []
    if half < 2: return out
    edge = f"edge-p{sp}-e{se}"; agg0 = f"agg-p{sp}-a0"
    intf_e = link_map.get((edge, agg0), (None,))[0]
    if intf_e:
        out.append({"after": (1, 0), "diff": {"device": edge,
            "add_lines": [f"interface {intf_e}", f" shutdown"],
            "description": f"Shutdown {intf_e} on {edge} (→agg0) → shift to agg1"}})
    core0 = f"core-g0-c0"
    intf_a = link_map.get((agg0, core0), (None,))[0]
    if intf_a:
        out.append({"after": (0, 1), "diff": {"device": agg0,
            "add_lines": [f"interface {intf_a}", f" shutdown"],
            "description": f"Shutdown {intf_a} on {agg0} (→core0) → shift to core1"}})
    return out

CHANGE_TYPES = ["local_preference", "med", "static_route",
                "bgp_network", "prefix_aggregation", "interface_shutdown"]
_GENERATORS = {
    "local_preference":   lambda s,d,k,lm: _gen_lp(s,d,k),
    "med":                lambda s,d,k,lm: _gen_med(s,d,k),
    "static_route":       lambda s,d,k,lm: _gen_static(s,d,k),
    "bgp_network":        lambda s,d,k,lm: _gen_bgp_network(s,d,k),
    "prefix_aggregation": lambda s,d,k,lm: _gen_prefix_agg(s,d,k),
    "interface_shutdown": lambda s,d,k,lm: _gen_intf_shutdown(s,d,k,lm),
}

def generate_advanced_configs(k, num_pairs=20, num_changes=5, pairs=None):
    base = f"data/fattree/fattreek{str(k).zfill(3)}"
    if not os.path.exists(os.path.join(base, "configs")):
        print(f"[INFO] Generating base configs for k={k}..."); generate_configs(k)
    create_before_dir(k)
    links = build_links(k); link_map = build_link_map(links)
    user_pairs = pairs is not None
    pairs = select_pairs(k, num_pairs, pairs)
    source = "user-specified" if user_pairs else "random inter-pod"
    print(f"[OK] Selected {len(pairs)} {source} pairs for k={k}")
    for ct in CHANGE_TYPES:
        p = os.path.join(base, ct)
        if os.path.exists(p): shutil.rmtree(p)
    all_instances = []
    for pid, (src_edge, dst_edge) in enumerate(pairs):
        sp, se = src_edge; dp, de = dst_edge
        before_path = PathSpec(src_edge, dst_edge, 0, 0)
        for ct in CHANGE_TYPES:
            avail = _GENERATORS[ct](src_edge, dst_edge, k, link_map)
            selected = [avail[i % len(avail)] for i in range(num_changes)]
            for cid, chg in enumerate(selected):
                a, c = chg["after"]
                after_path = PathSpec(src_edge, dst_edge, a, c)
                change_dir = os.path.join(base, ct, f"pair{pid}_change{cid}")
                os.makedirs(change_dir, exist_ok=True)
                with open(os.path.join(change_dir, "change.json"), "w") as f:
                    json.dump([chg["diff"]], f, indent=2)
                all_instances.append({
                    "pair_id": pid, "change_type": ct, "change_id": cid,
                    "src_edge": list(src_edge), "dst_edge": list(dst_edge),
                    "dst_prefix": f"1.{dp}.{de}.0/24",
                    "before_path": before_path.to_dict(), "after_path": after_path.to_dict(),
                    "change_device": chg["diff"]["device"],
                    "change_description": chg["diff"]["description"]})
        print(f"  Pair {pid}: edge-p{sp}-e{se} → edge-p{dp}-e{de}")
    with open(os.path.join(base, "ground_truth.json"), "w") as f:
        json.dump(all_instances, f, indent=2)
    with open(os.path.join(base, "endpoint_pairs.json"), "w") as f:
        json.dump([{"pair_id": i, "src_edge": list(s), "dst_edge": list(d)}
                    for i, (s, d) in enumerate(pairs)], f, indent=2)
    for ct in CHANGE_TYPES:
        ct_inst = [x for x in all_instances if x["change_type"] == ct]
        with open(os.path.join(base, f"ground_truth_{ct}.json"), "w") as f:
            json.dump(ct_inst, f, indent=2)
        print(f"  {ct}: {len(ct_inst)} instances")
    print(f"[OK] Total: {len(all_instances)} instances")
    return all_instances


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("k", type=int)
    parser.add_argument("--num-pairs", type=int, default=20)
    parser.add_argument("--num-changes", type=int, default=5)
    parser.add_argument("--pairs-file", help="JSON file with user-specified query pairs.")
    args = parser.parse_args()
    k = args.k
    if k % 2 != 0 or k < 4:
        print("k must be even and >= 4")
        sys.exit(1)
    pairs = load_query_pairs(args.pairs_file, k, "fattree") if args.pairs_file else None
    generate_advanced_configs(k, args.num_pairs, args.num_changes, pairs=pairs)
