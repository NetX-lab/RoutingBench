#!/usr/bin/env python3
"""
Compound (multi-change) Configuration Scenarios for fat-tree topologies.

4 compound scenarios (all on same dst prefix, inter-pod):
  S1: LP + BGP_Network           (2 devices)
  S2: LP + Intf_Shutdown          (2 devices)
  S3: LP + Static + Intf_Shutdown (2-3 devices)
  S4: LP + Static + BGP_Network + Intf_Shutdown (3-4 devices)

Before: same as IntraDCNet (base - max-paths + LP=200 pin).
Default path: edge → agg0 → core-g0-c0 → dst_agg0 → dst_edge.

Usage: python -m network.CompoundNet <k> [--num-pairs 20] [--num-changes 5]
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
    src_edge: Tuple[int,int]; dst_edge: Tuple[int,int]; agg_idx: int; core_idx: int
    def to_node_list(self):
        sp,se=self.src_edge; dp,de=self.dst_edge
        return [f"edge-p{sp}-e{se}",f"agg-p{sp}-a{self.agg_idx}",
                f"core-g{self.agg_idx}-c{self.core_idx}",f"agg-p{dp}-a{self.agg_idx}",f"edge-p{dp}-e{de}"]
    def to_node_list_with_servers(self):
        sp,se=self.src_edge; dp,de=self.dst_edge
        return [f"server-p{sp}-e{se}-h0"]+self.to_node_list()+[f"server-p{dp}-e{de}-h0"]
    def to_dict(self):
        return {"agg_idx":self.agg_idx,"core_idx":self.core_idx,
                "node_list":self.to_node_list(),"node_list_with_servers":self.to_node_list_with_servers()}

def select_pairs(k,num=20,pairs: Optional[List[Tuple[Tuple[int, int], Tuple[int, int]]]] = None):
    if pairs is not None:
        return pairs
    half=k//2; edges=[(p,e) for p in range(k) for e in range(half)]
    inter=[(a,b) for i,a in enumerate(edges) for b in edges[i+1:] if a[0]!=b[0]]
    random.shuffle(inter); return inter[:num]

def build_link_map(links):
    lm={}
    for link in links:
        n1,n2=link["node1"]["hostname"],link["node2"]["hostname"]
        i1,i2=link["node1"]["interfaceName"],link["node2"]["interfaceName"]
        lm[(n1,n2)]=(i1,i2); lm[(n2,n1)]=(i2,i1)
    return lm

def create_before_dir(k):
    from network.IntraDCNet import create_before_dir as _cb; _cb(k)

SCENARIOS=["compound_lp_bgpnet","compound_lp_shutdown",
           "compound_lp_static_shutdown","compound_lp_static_bgpnet_shutdown"]

def _gen_compound(se,de,k,lm):
    sp,s=se; dp,d=de; half=k//2; dn=f"1.{dp}.{d}.0"
    all_sc={s:[] for s in SCENARIOS}
    for ta in range(1,half):
        for tc in range(half):
            _,aip=p2p_edge_agg_ips(sp,s,ta); rm=f"RM_LP_AGG{ta}"
            lp_diff={"device":f"edge-p{sp}-e{s}",
                "add_lines":[f"route-map {rm} permit 10",f" set local-preference 300",
                    f"route-map {rm} permit 20",f"!",f"router bgp {asn_edge(sp,s,k)}",
                    f" address-family ipv4",f"  neighbor {aip} route-map {rm} in"],
                "description":f"LP=300 on edge from agg{ta}"}
            _,cip=p2p_agg_core_ips(sp,ta,tc)
            bgpnet_diff={"device":f"agg-p{sp}-a{ta}",
                "add_lines":[f"ip route {dn} 255.255.255.0 {cip}",f"!",
                    f"router bgp {asn_agg(sp)}",f" address-family ipv4",f"  network {dn} mask 255.255.255.0"],
                "description":f"BGP net /24+static on agg{ta}→core{tc}"}
            static_diff={"device":f"agg-p{sp}-a{ta}",
                "add_lines":[f"ip route {dn} 255.255.255.0 {cip}"],
                "description":f"Static /24 on agg{ta}→core{tc}"}
            agg0=f"agg-p{sp}-a0"; core0=f"core-g0-c0"
            ia=lm.get((agg0,core0),(None,))[0]
            if not ia: continue
            shut_diff={"device":agg0,"add_lines":[f"interface {ia}",f" shutdown"],
                "description":f"Shutdown {ia} on agg0"}
            af=(ta,tc)
            all_sc["compound_lp_bgpnet"].append({"after":af,"diffs":[lp_diff,bgpnet_diff]})
            if tc==0: all_sc["compound_lp_shutdown"].append({"after":af,"diffs":[lp_diff,shut_diff]})
            all_sc["compound_lp_static_shutdown"].append({"after":af,"diffs":[lp_diff,static_diff,shut_diff]})
            all_sc["compound_lp_static_bgpnet_shutdown"].append({"after":af,"diffs":[lp_diff,static_diff,bgpnet_diff,shut_diff]})
    return all_sc

def generate_compound_configs(k,num_pairs=20,num_changes=5,pairs=None):
    ft_base=f"data/fattree/fattreek{str(k).zfill(3)}"
    base=f"data/compound/compoundk{str(k).zfill(3)}"
    if not os.path.exists(os.path.join(ft_base,"configs")):
        print(f"[INFO] Generating base configs for k={k}..."); generate_configs(k)
    create_before_dir(k)
    # Copy before/ from fattree to compound
    before_src=os.path.join(ft_base,"before"); before_dst=os.path.join(base,"before")
    if os.path.exists(before_dst): shutil.rmtree(before_dst)
    os.makedirs(base,exist_ok=True)
    shutil.copytree(before_src,before_dst)
    links=build_links(k); lm=build_link_map(links)
    user_pairs=pairs is not None
    pairs=select_pairs(k,num_pairs,pairs)
    source="user-specified" if user_pairs else "inter-pod"
    print(f"[OK] {len(pairs)} {source} pairs for k={k}")
    for sc in SCENARIOS:
        p=os.path.join(base,sc)
        if os.path.exists(p): shutil.rmtree(p)
    all_inst=[]
    for pid,(se,de) in enumerate(pairs):
        sp,s=se; dp,d=de; bp=PathSpec(se,de,0,0)
        scenarios=_gen_compound(se,de,k,lm)
        for sc in SCENARIOS:
            avail=scenarios[sc]
            if not avail: continue
            selected=[avail[i%len(avail)] for i in range(num_changes)]
            for cid,chg in enumerate(selected):
                a,c=chg["after"]; ap=PathSpec(se,de,a,c)
                cd=os.path.join(base,sc,f"pair{pid}_change{cid}")
                os.makedirs(cd,exist_ok=True)
                with open(os.path.join(cd,"change.json"),"w") as f: json.dump(chg["diffs"],f,indent=2)
                all_inst.append({"pair_id":pid,"scenario":sc,"change_id":cid,
                    "src_edge":list(se),"dst_edge":list(de),"dst_prefix":f"1.{dp}.{d}.0/24",
                    "before_path":bp.to_dict(),"after_path":ap.to_dict(),
                    "num_changes":len(chg["diffs"]),
                    "changed_devices":[dd["device"] for dd in chg["diffs"]],
                    "change_descriptions":[dd["description"] for dd in chg["diffs"]]})
        print(f"  Pair {pid}: edge-p{sp}-e{s} → edge-p{dp}-e{d}")
    with open(os.path.join(base,"compound_ground_truth.json"),"w") as f: json.dump(all_inst,f,indent=2)
    for sc in SCENARIOS:
        si=[x for x in all_inst if x["scenario"]==sc]
        with open(os.path.join(base,f"compound_gt_{sc}.json"),"w") as f: json.dump(si,f,indent=2)
        print(f"  {sc}: {len(si)}")
    print(f"[OK] Total: {len(all_inst)} compound instances")
    return all_inst


if __name__=="__main__":
    parser=ArgumentParser(); parser.add_argument("k",type=int)
    parser.add_argument("--num-pairs",type=int,default=20); parser.add_argument("--num-changes",type=int,default=5)
    parser.add_argument("--pairs-file",help="JSON file with user-specified query pairs.")
    args=parser.parse_args()
    k=args.k
    if k%2!=0 or k<4: print("k must be even and >= 4"); sys.exit(1)
    pairs=load_query_pairs(args.pairs_file,k,"compound") if args.pairs_file else None
    generate_compound_configs(k,args.num_pairs,args.num_changes,pairs=pairs)
