#!/usr/bin/env python3
"""IPv6 addressing for fat-tree topologies (paper Sec.~3.2).

The IPv4 scheme in :mod:`network.TopoBase` uses one byte per index
field (layer, pod, edge/agg/core), which caps the topology at
``k <= 256``.  This module widens each field to **two bytes** by
mapping the same positional encoding into IPv6 hextets, so the
generator scales beyond ``k=256`` without changing the layout
semantics.  Only the base connectivity configuration is provided
here; advanced change generators continue to use the IPv4 path.

Positional encoding (each hextet = 16 bits):

==================  ==============================================
Link layer          Prefix
==================  ==============================================
Server subnet       ``2001:db8:0001:<pod>:<edge>::/64``
Edge<->Agg P2P      ``2001:db8:0002:<pod>:<agg>:<edge>::/127``
Agg<->Core P2P      ``2001:db8:0003:<pod>:<core>:<agg>::/127``
Loopback (edge)     ``2001:db8:fffe:<pod>:<edge>::1/128``
Loopback (agg)      ``2001:db8:ffff:<pod>:<agg>::1/128``
Loopback (core)     ``2001:db8:cccc:<group>:<core>::1/128``
==================  ==============================================

The /127 split mirrors the IPv4 /31 even/odd convention: the lower
side (``::0``) belongs to the device closer to the edge, and
``::1`` belongs to the upper-tier device.

Usage::

    from network.AddressingV6 import generate_configs_v6
    generate_configs_v6(k=4)
    # writes data/fattree_v6/fattreek004/configs/*.cfg
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Tuple

from network.TopoBase import (
    asn_agg, asn_core, asn_edge,
    build_links, parse_agg_name, parse_core_name, parse_edge_name,
    vlan_id,
)

# ------------------------- IPv6 prefix helpers ----------------------------

_BASE = "2001:db8"

def _h(x: int) -> str:
    """Format a 16-bit field as a lowercase hex hextet (``1`` → ``"1"``)."""
    return f"{x & 0xffff:x}"


def server_subnet_v6(pod: int, edge: int) -> str:
    """Server subnet (``/64``) attached to ``edge-p<pod>-e<edge>``."""
    return f"{_BASE}:1:{_h(pod)}:{_h(edge)}::/64"


def server_gateway_v6(pod: int, edge: int) -> str:
    return f"{_BASE}:1:{_h(pod)}:{_h(edge)}::1"


def server_host_v6(pod: int, edge: int, host: int) -> str:
    return f"{_BASE}:1:{_h(pod)}:{_h(edge)}::{_h(host + 2)}"


def p2p_edge_agg_v6(pod: int, edge: int, agg: int) -> Tuple[str, str]:
    """Returns ``(edge_side, agg_side)`` /127 addresses on an edge-agg link."""
    base = f"{_BASE}:2:{_h(pod)}:{_h(agg)}:{_h(edge)}"
    return f"{base}::0", f"{base}::1"


def p2p_agg_core_v6(pod: int, agg: int, core: int) -> Tuple[str, str]:
    """Returns ``(agg_side, core_side)`` /127 addresses on an agg-core link."""
    base = f"{_BASE}:3:{_h(pod)}:{_h(core)}:{_h(agg)}"
    return f"{base}::0", f"{base}::1"


def loopback_edge_v6(pod: int, edge: int) -> str:
    return f"{_BASE}:fffe:{_h(pod)}:{_h(edge)}::1"


def loopback_agg_v6(pod: int, agg: int) -> str:
    return f"{_BASE}:ffff:{_h(pod)}:{_h(agg)}::1"


def loopback_core_v6(group: int, core: int) -> str:
    return f"{_BASE}:cccc:{_h(group)}:{_h(core)}::1"


# ------------------------- IOS snippet helpers ----------------------------

def _ios_header(hostname: str) -> str:
    return (
        "!\nversion 15.2\n"
        "service timestamps debug datetime msec\n"
        "service timestamps log datetime msec\n!\n"
        f"hostname {hostname}\n!\n"
        "no aaa new-model\nip cef\nipv6 unicast-routing\nipv6 cef\n!\n"
    )


def _ios_tail() -> str:
    return (
        "!\nip forward-protocol nd\n!\n"
        "control-plane\n!\nline con 0\n exec-timeout 0 0\n logging synchronous\n!\n"
        "line vty 0 4\n login\n!\nend\n"
    )


def _iface_l3_v6(name: str, addr: str, desc: str, prefix_len: int = 127) -> str:
    return (
        f"interface {name}\n description {desc}\n no ip address\n"
        f" ipv6 address {addr}/{prefix_len}\n speed 1000\n duplex full\n no shutdown\n!\n"
    )


def _iface_vlan_v6(vid: int, gw: str, desc: str) -> str:
    return (
        f"interface Vlan{vid}\n description {desc}\n no ip address\n"
        f" ipv6 address {gw}/64\n no shutdown\n!\n"
    )


def _iface_access(name: str, vid: int, desc: str) -> str:
    return (
        f"interface {name}\n description {desc}\n switchport mode access\n"
        f" switchport access vlan {vid}\n spanning-tree portfast\n no shutdown\n!\n"
    )


def _bgp_v6_header(asn: int, rid: str) -> str:
    # router-id is still a 32-bit value; we derive it deterministically from the
    # ASN so two devices with different ASNs always have distinct router-ids.
    rid_v4 = ".".join(str((asn >> shift) & 0xff) for shift in (24, 16, 8, 0))
    return (
        f"router bgp {asn}\n bgp router-id {rid_v4}\n"
        " bgp log-neighbor-changes\n no bgp default ipv4-unicast\n !\n"
        " address-family ipv6\n  redistribute connected\n"
    )


def _bgp_v6_neighbor(addr: str, remote_as: int, route_map_out: str | None = None) -> str:
    out = [f"  neighbor {addr} remote-as {remote_as}",
           f"  neighbor {addr} activate"]
    if route_map_out:
        out.append(f"  neighbor {addr} route-map {route_map_out} out")
    return "\n".join(out) + "\n"


def _bgp_v6_footer() -> str:
    return "  maximum-paths 8\n exit-address-family\n!\n"


# ------------------------- Per-device assembly ----------------------------

def _make_edge_v6(host: str, k: int, server_ports: List[str], agg_links: List[Tuple[str, int]],
                  pod: int, edge: int) -> str:
    rid = loopback_edge_v6(pod, edge)
    asn = asn_edge(pod, edge, k)
    vid = vlan_id(pod, edge, k)
    cfg = _ios_header(host)
    cfg += f"interface Loopback0\n no ip address\n ipv6 address {rid}/128\n!\n"
    cfg += _iface_vlan_v6(vid, server_gateway_v6(pod, edge), f"SVI for server subnet pod{pod} edge{edge}")
    for h_idx, p in enumerate(server_ports):
        cfg += _iface_access(p, vid, f"Downlink to server-p{pod}-e{edge}-h{h_idx}")
    nei: List[Tuple[str, int]] = []
    for (iface, agg_idx) in agg_links:
        e_ip, a_ip = p2p_edge_agg_v6(pod, edge, agg_idx)
        cfg += _iface_l3_v6(iface, e_ip, f"Uplink P2P to agg-p{pod}-a{agg_idx}")
        nei.append((a_ip, asn_agg(pod)))
    pl = f"PLV6_E_{pod}_{edge}"
    rm_out = f"RMV6_E_OUT_{pod}_{edge}"
    cfg += (
        f"ipv6 prefix-list {pl} seq 5 permit {server_subnet_v6(pod, edge)}\n!\n"
        f"route-map {rm_out} permit 10\n match ipv6 address prefix-list {pl}\n!\n"
    )
    cfg += _bgp_v6_header(asn, rid)
    for nip, nas in nei:
        cfg += _bgp_v6_neighbor(nip, nas, route_map_out=rm_out)
    sub = server_subnet_v6(pod, edge)
    cfg += f"  aggregate-address {sub} summary-only\n"
    cfg += _bgp_v6_footer() + _ios_tail()
    return cfg


def _make_agg_v6(host: str, k: int, edge_links: List[Tuple[str, int]],
                 core_links: List[Tuple[str, int]], pod: int, agg: int) -> str:
    rid = loopback_agg_v6(pod, agg)
    asn = asn_agg(pod)
    cfg = _ios_header(host)
    cfg += f"interface Loopback0\n no ip address\n ipv6 address {rid}/128\n!\n"
    nei: List[Tuple[str, int]] = []
    for (iface, edge_idx) in edge_links:
        e_ip, a_ip = p2p_edge_agg_v6(pod, edge_idx, agg)
        cfg += _iface_l3_v6(iface, a_ip, f"Downlink P2P to edge-p{pod}-e{edge_idx}")
        nei.append((e_ip, asn_edge(pod, edge_idx, k)))
    for (iface, core_idx) in core_links:
        a_ip, c_ip = p2p_agg_core_v6(pod, agg, core_idx)
        cfg += _iface_l3_v6(iface, a_ip, f"Uplink P2P to core-g{agg}-c{core_idx}")
        nei.append((c_ip, asn_core()))
    pod_pfx = f"{_BASE}:1:{_h(pod)}::/48"
    pl = f"PLV6_P_{pod}"
    rm_out = f"RMV6_A_OUT_{pod}_{agg}"
    cfg += (
        f"ipv6 prefix-list {pl} seq 5 permit {pod_pfx} le 64\n!\n"
        f"route-map {rm_out} permit 10\n match ipv6 address prefix-list {pl}\n!\n"
    )
    cfg += _bgp_v6_header(asn, rid)
    for nip, nas in nei:
        rm = rm_out if nas == asn_core() else None
        cfg += _bgp_v6_neighbor(nip, nas, route_map_out=rm)
    cfg += f"  aggregate-address {pod_pfx} summary-only\n"
    cfg += _bgp_v6_footer() + _ios_tail()
    return cfg


def _make_core_v6(host: str, core_links: List[Tuple[str, Tuple[int, int]]]) -> str:
    group, core_idx = parse_core_name(host)
    rid = loopback_core_v6(group, core_idx)
    asn = asn_core()
    cfg = _ios_header(host)
    cfg += f"interface Loopback0\n no ip address\n ipv6 address {rid}/128\n!\n"
    nei: List[Tuple[str, int]] = []
    for (iface, (pod, agg_idx)) in core_links:
        a_ip, c_ip = p2p_agg_core_v6(pod, agg_idx, core_idx)
        cfg += _iface_l3_v6(iface, c_ip, f"Downlink P2P to agg-p{pod}-a{agg_idx}")
        nei.append((a_ip, asn_agg(pod)))
    all_pfx = f"{_BASE}:1::/32"
    pl = "PLV6_ALL"
    rm_out = f"RMV6_C_OUT_{group}_{core_idx}"
    cfg += (
        f"ipv6 prefix-list {pl} seq 5 permit {all_pfx} le 64\n!\n"
        f"route-map {rm_out} permit 10\n match ipv6 address prefix-list {pl}\n!\n"
    )
    cfg += _bgp_v6_header(asn, rid)
    for nip, nas in nei:
        cfg += _bgp_v6_neighbor(nip, nas, route_map_out=rm_out)
    cfg += f"  aggregate-address {all_pfx} summary-only\n"
    cfg += _bgp_v6_footer() + _ios_tail()
    return cfg


# ------------------------- Public entry point -----------------------------

def generate_configs_v6(k: int, outdir: str | None = None) -> None:
    """Generate the IPv6 base configuration for a fat-tree of size ``k``.

    Output layout mirrors :func:`network.TopoBase.generate_configs` but lives
    under ``data/fattree_v6/fattreek<NNN>/`` by default to avoid clobbering
    the IPv4 dataset.
    """
    if k % 2 != 0 or k < 2:
        raise ValueError("k must be even and >= 2")

    base = outdir or f"data/fattree_v6/fattreek{str(k).zfill(3)}"
    cfg_dir = os.path.join(base, "configs")
    hosts_dir = os.path.join(base, "hosts")
    os.makedirs(cfg_dir, exist_ok=True)
    os.makedirs(hosts_dir, exist_ok=True)

    links = build_links(k)
    with open(os.path.join(base, "example_layer1_topology.json"), "w") as fp:
        json.dump({"edges": links}, fp, indent=2)

    devices: Dict[str, Dict] = {}

    def ensure(d: str) -> None:
        devices.setdefault(d, {"server_ports": [], "edge_to_aggs": [],
                               "agg_to_edges": [], "agg_to_cores": [],
                               "core_to_aggs": []})

    for link in links:
        n1, n2 = link["node1"]["hostname"], link["node2"]["hostname"]
        i1, i2 = link["node1"]["interfaceName"], link["node2"]["interfaceName"]
        ensure(n1); ensure(n2)
        if n1.startswith("edge-") and n2.startswith("server-"):
            devices[n1]["server_ports"].append(i1)
        elif n1.startswith("server-") and n2.startswith("edge-"):
            devices[n2]["server_ports"].append(i2)
        elif n1.startswith("edge-") and n2.startswith("agg-"):
            pod, e = parse_edge_name(n1); _, a = parse_agg_name(n2)
            devices[n1]["edge_to_aggs"].append((i1, a))
            devices[n2]["agg_to_edges"].append((i2, e))
        elif n1.startswith("agg-") and n2.startswith("edge-"):
            pod, e = parse_edge_name(n2); _, a = parse_agg_name(n1)
            devices[n2]["edge_to_aggs"].append((i2, a))
            devices[n1]["agg_to_edges"].append((i1, e))
        elif n1.startswith("agg-") and n2.startswith("core-"):
            pod, a = parse_agg_name(n1); _, c = parse_core_name(n2)
            devices[n1]["agg_to_cores"].append((i1, c))
            devices[n2]["core_to_aggs"].append((i2, (pod, a)))
        elif n1.startswith("core-") and n2.startswith("agg-"):
            pod, a = parse_agg_name(n2); _, c = parse_core_name(n1)
            devices[n2]["agg_to_cores"].append((i2, c))
            devices[n1]["core_to_aggs"].append((i1, (pod, a)))

    n_routers = 0
    for dev, info in devices.items():
        if dev.startswith("edge-"):
            pod, e = parse_edge_name(dev)
            cfg = _make_edge_v6(dev, k, info["server_ports"], info["edge_to_aggs"], pod, e)
        elif dev.startswith("agg-"):
            pod, a = parse_agg_name(dev)
            cfg = _make_agg_v6(dev, k, info["agg_to_edges"], info["agg_to_cores"], pod, a)
        elif dev.startswith("core-"):
            cfg = _make_core_v6(dev, info["core_to_aggs"])
        else:
            continue
        with open(os.path.join(cfg_dir, f"{dev}.cfg"), "w") as fp:
            fp.write(cfg)
        n_routers += 1
    print(f"[OK] wrote {n_routers} IPv6 router configs to {cfg_dir}")

    half = k // 2
    n_hosts = 0
    for pod in range(k):
        for e in range(half):
            for h in range(half):
                hn = f"server-p{pod}-e{e}-h{h}"
                hcfg = {
                    "hostname": hn,
                    "hostInterfaces": {
                        "eth0": {
                            "name": "eth0",
                            "prefix": f"{server_host_v6(pod, e, h)}/64",
                            "gateway": server_gateway_v6(pod, e),
                        }
                    },
                }
                with open(os.path.join(hosts_dir, f"{hn}.json"), "w") as fp:
                    json.dump(hcfg, fp, indent=4)
                n_hosts += 1
    print(f"[OK] wrote {n_hosts} IPv6 server host configs to {hosts_dir}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("k", type=int, help="fat-tree parameter (even, >= 2)")
    parser.add_argument("--outdir", default=None,
                        help="override output directory "
                             "(default: data/fattree_v6/fattreek<NNN>/)")
    args = parser.parse_args()
    generate_configs_v6(args.k, args.outdir)
