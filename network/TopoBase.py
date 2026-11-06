#!/usr/bin/env python3
"""
Generate Cisco-like configs for a fat-tree topology (edge / agg / core) based on the
naming and addressing scheme shown in the diagram and the user's topology generator.

Usage:
    python generate_fattree_configs.py <k> [--outdir <dir>] [--from-file]

- <k> must be even and >= 2.
- If --from-file is provided, the script will try to load
  data/fattree/fattreek<k padded to 3>/example_layer1_topology.json.
  Otherwise, it will re-generate the same link structure in-memory using
  the same naming and interface allocation rules.
- Output configs will be saved under:
    data/fattree/fattreek<k padded>/configs/<hostname>.cfg
  (or under the directory provided by --outdir)

Addressing and policy assumptions (from the diagram):
- Server subnets:           1.<pod>.<edge>.0/24, gateway = 1.<pod>.<edge>.1
- Edge <-> Agg links:       2.<pod>.<agg>.<edge*2>/31 (edge gets even, agg gets odd)
- Agg  <-> Core links:      3.<pod>.<core>.<agg*2>/31 (agg gets even, core gets odd)
- ASN mapping:
    * Edge: 100000 + pod*k + edge
    * Agg:  20000 + pod
    * Core: 30000
- BGP Communities (for downstream server prefixes):
    * Edge: set community  (65000 + pod):edge       (applied when advertising to aggs)
    * Agg:  set community  (66000 + pod):agg        (applied when advertising to cores)
    * Core: set community  (67000 + group):core     (applied when advertising to aggs)

Implementation notes:
- We treat server-facing ports on edges as access ports in a VLAN unique to (pod, edge).
    The VLAN ID is computed as vid = 1000 + pod*(k//2) + edge (<= 4094 for typical lab k).
    SVI interface Vlan<vid> has the gateway IP 1.<pod>.<edge>.1/24.
- We use directly connected eBGP sessions over /31 point-to-point links.
- Loopback0 is assigned deterministically per device for router-id (in a separate 10.x.x.x space):
        * Edge:  10.<pod>.0.<edge>     /32
        * Agg:   10.<pod>.1.<agg>      /32
        * Core:  10.255.<group>.<core> /32

This script generates reasonably standard Cisco IOS-style configurations modeled
on the user's example, with minimal, consistent settings.
"""

import os
import sys
import json
from argparse import ArgumentParser
from typing import Dict, List, Tuple

# ------------------------- Helpers to parse names --------------------------

def parse_edge_name(name: str) -> Tuple[int, int]:
    # edge-p{pod}-e{edge}
    parts = name.split('-')
    pod = int(parts[1][1:])
    edge = int(parts[2][1:])
    return pod, edge


def parse_agg_name(name: str) -> Tuple[int, int]:
    # agg-p{pod}-a{agg}
    parts = name.split('-')
    pod = int(parts[1][1:])
    agg = int(parts[2][1:])
    return pod, agg


def parse_core_name(name: str) -> Tuple[int, int]:
    # core-g{group}-c{idx}
    parts = name.split('-')
    group = int(parts[1][1:])
    core = int(parts[2][1:])
    return group, core


# ------------------------- Addressing functions ---------------------------

def ip_edge_loopback(pod: int, edge: int) -> str:
    return f"10.{pod}.0.{edge}"


def ip_agg_loopback(pod: int, agg: int) -> str:
    return f"10.{pod}.1.{agg}"


def ip_core_loopback(group: int, core: int) -> str:
    return f"10.255.{group}.{core}"


def vlan_id(pod: int, edge: int, k: int) -> int:
    return 1000 + pod * (k // 2) + edge


def server_gateway_ip(pod: int, edge: int) -> str:
    return f"1.{pod}.{edge}.1"


def server_network(pod: int, edge: int) -> str:
    return f"1.{pod}.{edge}.0"


def p2p_edge_agg_ips(pod: int, edge: int, agg: int) -> Tuple[str, str]:
    # base: 2.<pod>.<agg>.<edge*2>/31
    base_last = edge * 2
    edge_ip = f"2.{pod}.{agg}.{base_last}"
    agg_ip = f"2.{pod}.{agg}.{base_last + 1}"
    return edge_ip, agg_ip


def p2p_agg_core_ips(pod: int, agg: int, core: int) -> Tuple[str, str]:
    # base: 3.<pod>.<core>.<agg*2>/31
    base_last = agg * 2
    agg_ip = f"3.{pod}.{core}.{base_last}"
    core_ip = f"3.{pod}.{core}.{base_last + 1}"
    return agg_ip, core_ip


def asn_edge(pod: int, edge: int, k: int) -> int:
    return 100000 + pod * k // 2 + edge


def asn_agg(pod: int) -> int:
    return 20000 + pod


def asn_core() -> int:
    return 30000


def community_edge(pod: int, edge: int) -> str:
    return f"{65000 + pod}:{edge}"


def community_agg(pod: int, agg: int) -> str:
    return f"{66000 + pod}:{agg}"


def community_core(group: int, core: int) -> str:
    return f"{67000 + group}:{core}"


# ------------------------- Topology generation ----------------------------

def next_port(device_port_counters: Dict[str, int], hostname: str) -> str:
    # same as user's generator: GigabitEthernet{slot}/0/{port}, slot increases every 48 ports
    device_port_counters.setdefault(hostname, 1)
    p = device_port_counters[hostname]
    device_port_counters[hostname] = p + 1
    slot = (p - 1) // 48 + 1
    port = (p - 1) % 48 + 1
    return f"GigabitEthernet{slot}/0/{port}"


def build_links(k: int) -> List[Dict]:
    pods = k
    edge_per_pod = k // 2
    agg_per_pod = k // 2
    core_groups = k // 2
    core_per_group = k // 2

    device_port_counters: Dict[str, int] = {}
    links: List[Dict] = []

    # servers <-> edge
    for pod in range(pods):
        for edge_idx in range(edge_per_pod):
            edge_name = f"edge-p{pod}-e{edge_idx}"
            for host_idx in range(edge_per_pod):
                server_name = f"server-p{pod}-e{edge_idx}-h{host_idx}"
                links.append({
                    "node1": {"hostname": edge_name, "interfaceName": next_port(device_port_counters, edge_name)},
                    "node2": {"hostname": server_name, "interfaceName": "eth0"},
                })

    # edge <-> agg
    for pod in range(pods):
        agg_names = [f"agg-p{pod}-a{a}" for a in range(agg_per_pod)]
        edge_names = [f"edge-p{pod}-e{e}" for e in range(edge_per_pod)]
        for edge_name in edge_names:
            for agg_name in agg_names:
                links.append({
                    "node1": {"hostname": edge_name, "interfaceName": next_port(device_port_counters, edge_name)},
                    "node2": {"hostname": agg_name,  "interfaceName": next_port(device_port_counters, agg_name)},
                })

    # agg <-> core
    for pod in range(pods):
        for a in range(agg_per_pod):
            agg_name = f"agg-p{pod}-a{a}"
            group = a
            for i in range(core_per_group):
                core_name = f"core-g{group}-c{i}"
                links.append({
                    "node1": {"hostname": agg_name, "interfaceName": next_port(device_port_counters, agg_name)},
                    "node2": {"hostname": core_name, "interfaceName": next_port(device_port_counters, core_name)},
                })
    return links


def load_or_build_links(k: int, use_file: bool) -> List[Dict]:
    if use_file:
        dir_path = f"data/fattree/fattreek{str(k).zfill(3)}"
        topo_path = os.path.join(dir_path, "example_layer1_topology.json")
        if os.path.exists(topo_path):
            with open(topo_path, "r") as f:
                data = json.load(f)
            return data.get("edges", [])
        else:
            # store the link file
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            link_dict = {"edges": build_links(k)}
            json.dump(link_dict, open(topo_path, "w"), indent=2)
            print(f"[WARN] Topology file not found at {topo_path}, regenerating links in-memory.")
            print(f"[OK] Generated and saved link file to {topo_path}, total {len(link_dict['edges'])} links.")
    return build_links(k)


# ------------------------- Config generation ------------------------------

def ios_header(hostname: str) -> str:
    """Common IOS prefix ("header") used by all devices."""
    return f"""!
version 15.2
service timestamps debug datetime msec
service timestamps log datetime msec
!
hostname {hostname}
!
boot-start-marker
boot-end-marker
!
no aaa new-model
no ip icmp rate-limit unreachable
ip cef
!
no ip domain lookup
ip domain name lab.local
no ipv6 cef
!
multilink bundle-name authenticated
!
ip tcp synwait-time 5
!
"""


def ios_common_tail() -> str:
    """Common IOS trailer used by all devices."""
    return """ip forward-protocol nd
ip bgp-community new-format
!
no ip http server
no ip http secure-server
!
control-plane
!
line con 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
 stopbits 1
line aux 0
 exec-timeout 0 0
 privilege level 15
 logging synchronous
 stopbits 1
line vty 0 4
 login
!
end
"""


def iface_ge_ip(name: str, ip: str, desc: str, mask: str = "255.255.255.254") -> str:
    """L3 P2P interface, typically /31 for edge-agg and agg-core links.

    desc should describe direction and peer layer, e.g. "Uplink P2P to aggregation"
    or "Downlink P2P to edge".
    """
    return f"""interface {name}
 description {desc}
 ip address {ip} {mask}
 speed 1000
 duplex full
 negotiation auto
!
"""


def iface_vlan(vid: int, ip: str, pod: int, edge: int) -> str:
    """SVI for server VLANs on edge switches."""
    return f"""interface Vlan{vid}
 description Access SVI for p{pod}e{edge} servers
 ip address {ip} 255.255.255.0
 no shutdown
!
"""


def iface_access_port(name: str, vid: int, desc: str) -> str:
    """Access port towards a server, in VLAN vid."""
    return f"""interface {name}
 description {desc}
 switchport mode access
 switchport access vlan {vid}
 spanning-tree portfast
 no shutdown
!
"""


def router_bgp_header(asn: int, rid_ip: str) -> str:
    """Start of BGP process & ipv4 address-family with connected redistribution."""
    return f"""router bgp {asn}
 bgp router-id {rid_ip}
 bgp log-neighbor-changes
 !
 address-family ipv4
  redistribute connected
"""


def router_bgp_neighbor(nei_ip: str, remote_as: int, route_map_out: str = None, route_map_in: str = None) -> str:
    lines = [f"  neighbor {nei_ip} remote-as {remote_as}"]
    lines.append(f"  neighbor {nei_ip} activate")
    if route_map_in:
        lines.append(f"  neighbor {nei_ip} route-map {route_map_in} in")
    if route_map_out:
        lines.append(f"  neighbor {nei_ip} route-map {route_map_out} out")
    return "\n".join(lines) + "\n"


def router_bgp_footer() -> str:
    return """  maximum-paths 8
 exit-address-family
!
"""


def make_edge_config(hostname: str, k: int, server_ports: List[str], agg_links: List[Tuple[str, int]], pod: int, edge: int) -> str:
    """Generate edge switch/router config.

    Order: header -> interfaces -> ACLs -> static routes -> route-maps/communities -> BGP -> tail.
    """
    rid = ip_edge_loopback(pod, edge)
    asn = asn_edge(pod, edge, k)
    vid = vlan_id(pod, edge, k)
    gw_ip = server_gateway_ip(pod, edge)

    cfg = ios_header(hostname)

    # Interfaces
    cfg += "!\n!\n"
    cfg += f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"
    cfg += iface_vlan(vid, gw_ip, pod, edge)
    for idx, p in enumerate(server_ports):
        desc = f"Downlink access to server-p{pod}-e{edge}-h{idx}"
        cfg += iface_access_port(p, vid, desc)

    nei_cfgs: List[Tuple[str, int]] = []
    for (edge_if, agg_idx) in agg_links:
        edge_ip, agg_ip = p2p_edge_agg_ips(pod, edge, agg_idx)
        cfg += iface_ge_ip(edge_if, edge_ip, "Uplink P2P to aggregation")
        nei_cfgs.append((agg_ip, asn_agg(pod)))

    # Route-maps & communities
    cfg += "!\n!\n"
    pl_name = f"PL_EDGE_{pod}_{edge}"
    cfg += f"ip prefix-list {pl_name} seq 5 permit {server_network(pod, edge)}/24\n!\n"
    rm_out = f"RM_EDGE_TO_AGG_{pod}_{edge}"
    cfg += (
        f"route-map {rm_out} permit 10\n"
        f" match ip address prefix-list {pl_name}\n"
        f" set community {community_edge(pod, edge)} additive\n!\n"
    )

    # BGP
    cfg += "!\n!\n"
    cfg += router_bgp_header(asn, rid)
    for nei_ip, nei_as in nei_cfgs:
        cfg += router_bgp_neighbor(nei_ip, nei_as, route_map_out=rm_out)
    cfg += f"  aggregate-address {server_network(pod, edge)} 255.255.255.0 as-set summary-only\n"
    cfg += router_bgp_footer()

    # Tail
    cfg += "!\n!\n"
    cfg += ios_common_tail()
    return cfg


def make_agg_config(hostname: str, k: int, edge_links: List[Tuple[str, int]], core_links: List[Tuple[str, Tuple[int, int]]], pod: int, agg: int) -> str:
    """Generate aggregation switch/router config."""
    rid = ip_agg_loopback(pod, agg)
    asn = asn_agg(pod)

    cfg = ios_header(hostname)

    # Interfaces
    cfg += "!\n!\n"
    cfg += f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"

    nei_cfgs: List[Tuple[str, int]] = []
    for (agg_if, edge_idx) in edge_links:
        edge_ip, agg_ip = p2p_edge_agg_ips(pod, edge_idx, agg)
        cfg += iface_ge_ip(agg_if, agg_ip, "Downlink P2P to edge")
        nei_cfgs.append((edge_ip, asn_edge(pod, edge_idx, k)))

    for (agg_if, core_idx) in core_links:
        agg_ip, core_ip = p2p_agg_core_ips(pod, agg, core_idx)
        cfg += iface_ge_ip(agg_if, agg_ip, "Uplink P2P to core")
        nei_cfgs.append((core_ip, asn_core()))

    # Route-maps & communities
    cfg += "!\n!\n"
    pl_name = f"PL_POD_{pod}"
    cfg += f"ip prefix-list {pl_name} seq 5 permit 1.{pod}.0.0/16 le 24\n!\n"
    rm_out = f"RM_AGG_TO_CORE_{pod}_{agg}"
    cfg += (
        f"route-map {rm_out} permit 10\n"
        f" match ip address prefix-list {pl_name}\n"
        f" set community {community_agg(pod, agg)} additive\n!\n"
    )

    # BGP
    cfg += "!\n!\n"
    cfg += router_bgp_header(asn, rid)
    for nei_ip, nei_as in nei_cfgs:
        rm = rm_out if nei_as == asn_core() else None
        cfg += router_bgp_neighbor(nei_ip, nei_as, route_map_out=rm)
    cfg += f"  aggregate-address 1.{pod}.0.0 255.255.0.0 as-set summary-only\n"
    cfg += router_bgp_footer()

    # Tail
    cfg += "!\n!\n"
    cfg += ios_common_tail()
    return cfg


def make_core_config(hostname: str, core_links: List[Tuple[str, Tuple[int, int]]]) -> str:
    """Generate core router config."""
    group, core_idx = parse_core_name(hostname)
    rid = ip_core_loopback(group, core_idx)
    asn = asn_core()

    cfg = ios_header(hostname)

    # Interfaces
    cfg += "!\n!\n"
    cfg += f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"

    nei_cfgs: List[Tuple[str, int]] = []
    for (core_if, (pod, agg_idx)) in core_links:
        agg_ip, core_ip = p2p_agg_core_ips(pod, agg_idx, core_idx)
        cfg += iface_ge_ip(core_if, core_ip, "Downlink P2P to aggregation")
        nei_cfgs.append((agg_ip, asn_agg(pod=pod)))

    # Route-maps & communities
    cfg += "!\n!\n"
    pl_name = "PL_ALL_PODS"
    cfg += f"ip prefix-list {pl_name} seq 5 permit 1.0.0.0/8 le 24\n!\n"
    rm_out = f"RM_CORE_OUT_{group}_{core_idx}"
    cfg += (
        f"route-map {rm_out} permit 10\n"
        f" match ip address prefix-list {pl_name}\n"
        f" set community {community_core(group, core_idx)} additive\n!\n"
    )

    # BGP
    cfg += "!\n!\n"
    cfg += router_bgp_header(asn, rid)
    for nei_ip, nei_as in nei_cfgs:
        cfg += router_bgp_neighbor(nei_ip, nei_as, route_map_out=rm_out)
    cfg += "  aggregate-address 1.0.0.0 255.0.0.0 as-set summary-only\n"
    cfg += router_bgp_footer()

    # Tail
    cfg += "!\n!\n"
    cfg += ios_common_tail()
    return cfg


def make_server_config(hostname: str, pod: int, edge: int, host: int) -> str:
    host_name = f"server-p{pod}-e{edge}-h{host}"
    ip_prefix = f"1.{pod}.{edge}.{host + 2}/24"
    gateway = f"1.{pod}.{edge}.1"
    host_config = {
        "hostname": host_name,
        "hostInterfaces": {
            "eth0": {
                "name": "eth0",
                "prefix": ip_prefix,
                "gateway": gateway,
            }
        },
    }
    return host_config

# ------------------------- Main assembly ----------------------------------

def generate_configs(k: int) -> None:
    link_file = f"data/fattree/fattreek{str(k).zfill(3)}/example_layer1_topology.json"
    links = load_or_build_links(k, link_file)
    outdir_configs = f"data/fattree/fattreek{str(k).zfill(3)}/configs"
    outdir_hosts = f"data/fattree/fattreek{str(k).zfill(3)}/hosts"
    os.makedirs(outdir_hosts, exist_ok=True)
    os.makedirs(outdir_configs, exist_ok=True)

    # Build adjacency and interface maps per device
    # We need to know, for each device, which ports connect to servers, edges, aggs, cores
    devices: Dict[str, Dict] = {}

    def ensure_dev(name: str):
        devices.setdefault(name, {
            "server_ports": [],  # for edges
            "edge_to_aggs": [],  # list of (edge_iface_name, agg_idx)
            "agg_to_edges": [],  # list of (agg_iface_name, edge_idx)
            "agg_to_cores": [],  # list of (agg_iface_name, core_idx)
            "core_to_aggs": [],  # list of (core_iface_name, (pod, agg_idx))
        })

    for link in links:
        n1 = link["node1"]["hostname"]
        n2 = link["node2"]["hostname"]
        i1 = link["node1"]["interfaceName"]
        i2 = link["node2"]["interfaceName"]
        ensure_dev(n1); ensure_dev(n2)
        # Categorize
        if n1.startswith("edge-") and n2.startswith("server-"):
            devices[n1]["server_ports"].append(i1)
        elif n1.startswith("edge-") and n2.startswith("agg-"):
            pod, edge_idx = parse_edge_name(n1)
            pod2, agg_idx = parse_agg_name(n2)
            assert pod == pod2
            devices[n1]["edge_to_aggs"].append((i1, agg_idx))
            devices[n2]["agg_to_edges"].append((i2, edge_idx))
        elif n1.startswith("agg-") and n2.startswith("core-"):
            pod, agg_idx = parse_agg_name(n1)
            group, core_idx = parse_core_name(n2)
            devices[n1]["agg_to_cores"].append((i1, core_idx))
            devices[n2]["core_to_aggs"].append((i2, (pod, agg_idx)))
        else:
            # If direction reversed, handle symmetric cases
            if n2.startswith("edge-") and n1.startswith("server-"):
                devices[n2]["server_ports"].append(i2)
            elif n2.startswith("edge-") and n1.startswith("agg-"):
                pod, edge_idx = parse_edge_name(n2)
                pod2, agg_idx = parse_agg_name(n1)
                assert pod == pod2
                devices[n2]["edge_to_aggs"].append((i2, agg_idx))
                devices[n1]["agg_to_edges"].append((i1, edge_idx))
            elif n2.startswith("agg-") and n1.startswith("core-"):
                pod, agg_idx = parse_agg_name(n2)
                group, core_idx = parse_core_name(n1)
                devices[n2]["agg_to_cores"].append((i2, core_idx))
                devices[n1]["core_to_aggs"].append((i1, (pod, agg_idx)))
            else:
                # ignore other types (e.g., server entries)
                pass

    # Generate per-device configs
    for dev, info in devices.items():
        if dev.startswith("edge-"):
            pod, edge_idx = parse_edge_name(dev)
            cfg = make_edge_config(
                hostname=dev,
                k=k,
                server_ports=info["server_ports"],
                agg_links=info["edge_to_aggs"],
                pod=pod,
                edge=edge_idx,
            )
        elif dev.startswith("agg-"):
            pod, agg_idx = parse_agg_name(dev)
            cfg = make_agg_config(
                hostname=dev,
                k=k,
                edge_links=info["agg_to_edges"],
                core_links=info["agg_to_cores"],
                pod=pod,
                agg=agg_idx,
            )
        elif dev.startswith("core-"):
            cfg = make_core_config(
                hostname=dev,
                core_links=info["core_to_aggs"],
            )
        else:
            # skip servers (no Cisco configs generated for servers)
            continue
        out_path = os.path.join(outdir_configs, f"{dev}.cfg")
        with open(out_path, "w") as f:
            f.write(cfg)
    print(f"[OK] wrote all router/switch configs to {outdir_configs}, total {len(devices)- (k * (k//2) * (k//2))} devices.")
    
    # generate host configs
    for pod in range(k):
        for edge_idx in range(k // 2):
            for host_idx in range(k // 2):
                host_config = make_server_config(
                    hostname=f"server-p{pod}-e{edge_idx}-h{host_idx}",
                    pod=pod,
                    edge=edge_idx,
                    host=host_idx,
                ) 
                host_name = f"server-p{pod}-e{edge_idx}-h{host_idx}"
                with open(f"{outdir_hosts}/{host_name}.json", "w") as f:
                    json.dump(host_config, f, indent=4)
    print(f"[OK] wrote server host configs to {outdir_hosts}, total {k * (k//2) * (k//2)} servers.")


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("k", type=int, help="fat-tree parameter (must be even)")
    args = parser.parse_args()

    k = args.k
    if k % 2 != 0 or k < 2:
        print("k must be even and >= 2")
        sys.exit(1)

    generate_configs(k=k)
