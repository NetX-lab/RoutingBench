#!/usr/bin/env python3
"""
Generate Cross-DC fat-tree topology, base configs, advanced changes, and verify.

Cross-DC: 2 DCs (each fat-tree k), k gateways per DC connected to all cores,
gateways fully meshed between DCs. Queries: src in DC0, dst in DC1.

Naming: dc{d}-edge-p{pod}-e{idx}, dc{d}-agg-p{pod}-a{idx},
        dc{d}-core-g{grp}-c{idx}, dc{d}-gw{g}

Addressing:
  DC0 servers: 1.<pod>.<edge>.0/24    DC1 servers: 9.<pod>.<edge>.0/24
  Edge↔Agg:    DC0: 2.<pod>.<agg>.<edge*2>/31   DC1: 6.<pod>.<agg>.<edge*2>/31
  Agg↔Core:    DC0: 3.<pod>.<core>.<agg*2>/31   DC1: 7.<pod>.<core>.<agg*2>/31
  Core↔GW:     DC0: 4.0.<gw>.<core_seq*2>/31    DC1: 8.0.<gw>.<core_seq*2>/31
  GW↔GW:       5.<gw0>.<gw1>.{0,1}/31
  Loopbacks:   Edge DC0: 10.<pod>.0.<edge>      DC1: 10.<pod>.2.<edge>
               Agg  DC0: 10.<pod>.1.<agg>       DC1: 10.<pod>.3.<agg>
               Core 10.<200+dc>.<grp>.<idx>    GW 10.<250+dc>.0.<gw>
ASN: Edge 100000+dc*10000+pod*(k//2)+edge, Agg 20000+dc*1000+pod,
     Core 30000+dc, GW 40000+dc*1000+gw

Usage: python -m network.InterDCNet <k> [--num-pairs 20] [--num-changes 5]
"""

import os, sys, json, shutil, random
from argparse import ArgumentParser
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from network.query_pairs import load_query_pairs

random.seed(42)

# ── Addressing ──
def _edge_lo(dc,pod,e):     return f"10.{pod}.{2*dc}.{e}"
def _agg_lo(dc,pod,a):      return f"10.{pod}.{2*dc+1}.{a}"
def _core_lo(dc,grp,idx):   return f"10.{200+dc}.{grp}.{idx}"
def _gw_lo(dc,gw):           return f"10.{250+dc}.0.{gw}"
def _asn_edge(dc,pod,e,k):  return 100000+dc*10000+pod*(k//2)+e
def _asn_agg(dc,pod):        return 20000+dc*1000+pod
def _asn_core(dc):            return 30000+dc
def _asn_gw(dc,gw):          return 40000+dc*1000+gw
def _p2p_edge_agg(dc,pod,e,a):
    base = 6 if dc else 2
    b = e*2; return (f"{base}.{pod}.{a}.{b}", f"{base}.{pod}.{a}.{b+1}")
def _p2p_agg_core(dc,pod,a,c):
    base = 7 if dc else 3
    b = a*2; return (f"{base}.{pod}.{c}.{b}", f"{base}.{pod}.{c}.{b+1}")
def _p2p_core_gw(dc,gw,core_seq):
    base = 8 if dc else 4
    b = core_seq*2; return (f"{base}.0.{gw}.{b}", f"{base}.0.{gw}.{b+1}")
def _p2p_gw_gw(gw0,gw1):
    return (f"5.{gw0}.{gw1}.0", f"5.{gw0}.{gw1}.1")
def _server_net(dc,pod,e):
    return f"{1 if dc==0 else 9}.{pod}.{e}.0"

# ── IOS helpers ──
def _next_port(c,h):
    c.setdefault(h,1); p=c[h]; c[h]=p+1
    return f"GigabitEthernet{(p-1)//48+1}/0/{(p-1)%48+1}"

def _ios_header(h):
    return f"!\nversion 15.2\nservice timestamps debug datetime msec\nservice timestamps log datetime msec\n!\nhostname {h}\n!\nboot-start-marker\nboot-end-marker\n!\nno aaa new-model\nno ip icmp rate-limit unreachable\nip cef\n!\nno ip domain lookup\nip domain name lab.local\nno ipv6 cef\n!\nmultilink bundle-name authenticated\n!\nip tcp synwait-time 5\n!\n"

def _ios_tail():
    return "ip forward-protocol nd\nip bgp-community new-format\n!\nno ip http server\nno ip http secure-server\n!\ncontrol-plane\n!\nline con 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\nline aux 0\n exec-timeout 0 0\n privilege level 15\n logging synchronous\n stopbits 1\nline vty 0 4\n login\n!\nend\n"

def _iface_l3(name,ip,desc,mask="255.255.255.254"):
    return f"interface {name}\n description {desc}\n ip address {ip} {mask}\n speed 1000\n duplex full\n negotiation auto\n!\n"
def _iface_vlan(vid,ip,desc):
    return f"interface Vlan{vid}\n description {desc}\n ip address {ip} 255.255.255.0\n no shutdown\n!\n"
def _iface_access(name,vid,desc):
    return f"interface {name}\n description {desc}\n switchport mode access\n switchport access vlan {vid}\n spanning-tree portfast\n no shutdown\n!\n"
def _bgp_header(asn,rid):
    return f"router bgp {asn}\n bgp router-id {rid}\n bgp log-neighbor-changes\n !\n address-family ipv4\n  redistribute connected\n"
def _bgp_nei(ip,ras,rm_out=None):
    s = f"  neighbor {ip} remote-as {ras}\n  neighbor {ip} activate\n"
    if rm_out: s += f"  neighbor {ip} route-map {rm_out} out\n"
    return s
def _bgp_footer():
    return " exit-address-family\n!\n"

# ── Topology generation ──
def generate_crossdc(k):
    half = k//2
    outdir = f"data/crossdc/crossdck{str(k).zfill(3)}"
    cfg_dir = os.path.join(outdir,"configs"); hosts_dir = os.path.join(outdir,"hosts")
    if os.path.exists(outdir): shutil.rmtree(outdir)
    os.makedirs(cfg_dir); os.makedirs(hosts_dir)
    pc = {}; links = []
    def add_link(h1,h2):
        i1=_next_port(pc,h1); i2=_next_port(pc,h2)
        links.append({"node1":{"hostname":h1,"interfaceName":i1},"node2":{"hostname":h2,"interfaceName":i2}})
        return i1,i2
    for dc in range(2):
        pfx=f"dc{dc}-"
        for pod in range(k):
            for e in range(half):
                edge=f"{pfx}edge-p{pod}-e{e}"
                for h in range(half): add_link(edge,f"{pfx}server-p{pod}-e{e}-h{h}")
        for pod in range(k):
            for e in range(half):
                for a in range(half): add_link(f"{pfx}edge-p{pod}-e{e}",f"{pfx}agg-p{pod}-a{a}")
        for pod in range(k):
            for a in range(half):
                for c in range(half): add_link(f"{pfx}agg-p{pod}-a{a}",f"{pfx}core-g{a}-c{c}")
        for g in range(k):
            gw=f"{pfx}gw{g}"
            for grp in range(half):
                for c in range(half): add_link(f"{pfx}core-g{grp}-c{c}",gw)
    for g0 in range(k):
        for g1 in range(k): add_link(f"dc0-gw{g0}",f"dc1-gw{g1}")
    lm = {}
    for link in links:
        n1,n2=link["node1"]["hostname"],link["node2"]["hostname"]
        i1,i2=link["node1"]["interfaceName"],link["node2"]["interfaceName"]
        lm[(n1,n2)]=(i1,i2); lm[(n2,n1)]=(i2,i1)
    with open(os.path.join(outdir,"example_layer1_topology.json"),"w") as f:
        json.dump({"edges":links},f,indent=2)
    devices = {}
    for dc in range(2):
        pfx=f"dc{dc}-"; sp=1 if dc==0 else 9
        for pod in range(k):
            for e in range(half):
                h=f"{pfx}edge-p{pod}-e{e}"; asn=_asn_edge(dc,pod,e,k); rid=_edge_lo(dc,pod,e)
                vid=1000+(100*dc+pod)*half+e
                cfg=_ios_header(h)+f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"
                cfg+=_iface_vlan(vid,f"{sp}.{pod}.{e}.1",f"SVI {pfx}p{pod}e{e}")
                for hh in range(half):
                    srv=f"{pfx}server-p{pod}-e{e}-h{hh}"; cfg+=_iface_access(lm[(h,srv)][0],vid,f"To {srv}")
                nei=[]
                for a in range(half):
                    agg=f"{pfx}agg-p{pod}-a{a}"; eip,aip=_p2p_edge_agg(dc,pod,e,a)
                    cfg+=_iface_l3(lm[(h,agg)][0],eip,f"To {agg}"); nei.append((aip,_asn_agg(dc,pod)))
                sn=f"{sp}.{pod}.{e}.0"; pl=f"PL_E_{dc}_{pod}_{e}"; rm=f"RM_E_{dc}_{pod}_{e}"
                cfg+=f"ip prefix-list {pl} seq 5 permit {sn}/24\n!\nroute-map {rm} permit 10\n match ip address prefix-list {pl}\n!\n"
                cfg+=_bgp_header(asn,rid)
                for nip,nas in nei: cfg+=_bgp_nei(nip,nas,rm_out=rm)
                cfg+=f"  aggregate-address {sn} 255.255.255.0 as-set summary-only\n"
                cfg+=_bgp_footer()+_ios_tail(); devices[h]=cfg
        for pod in range(k):
            for a in range(half):
                h=f"{pfx}agg-p{pod}-a{a}"; asn=_asn_agg(dc,pod); rid=_agg_lo(dc,pod,a)
                cfg=_ios_header(h)+f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"
                nei=[]
                for e in range(half):
                    edge=f"{pfx}edge-p{pod}-e{e}"; eip,aip=_p2p_edge_agg(dc,pod,e,a)
                    cfg+=_iface_l3(lm[(h,edge)][0],aip,f"To {edge}"); nei.append((eip,_asn_edge(dc,pod,e,k)))
                for c in range(half):
                    core=f"{pfx}core-g{a}-c{c}"; aip,cip=_p2p_agg_core(dc,pod,a,c)
                    cfg+=_iface_l3(lm[(h,core)][0],aip,f"To {core}"); nei.append((cip,_asn_core(dc)))
                pl=f"PL_P_{dc}_{pod}"; rm=f"RM_A_{dc}_{pod}_{a}"
                cfg+=f"ip prefix-list {pl} seq 5 permit {sp}.{pod}.0.0/16 le 24\n!\nroute-map {rm} permit 10\n match ip address prefix-list {pl}\n!\n"
                cfg+=_bgp_header(asn,rid)
                for nip,nas in nei:
                    rmo=rm if nas==_asn_core(dc) else None; cfg+=_bgp_nei(nip,nas,rm_out=rmo)
                cfg+=f"  aggregate-address {sp}.{pod}.0.0 255.255.0.0 as-set summary-only\n"
                cfg+=_bgp_footer()+_ios_tail(); devices[h]=cfg
        for grp in range(half):
            for c in range(half):
                h=f"{pfx}core-g{grp}-c{c}"; asn=_asn_core(dc); rid=_core_lo(dc,grp,c)
                cfg=_ios_header(h)+f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"
                nei=[]
                for pod in range(k):
                    agg=f"{pfx}agg-p{pod}-a{grp}"; aip,cip=_p2p_agg_core(dc,pod,grp,c)
                    cfg+=_iface_l3(lm[(h,agg)][0],cip,f"To {agg}"); nei.append((aip,_asn_agg(dc,pod)))
                for g in range(k):
                    gw=f"{pfx}gw{g}"; cs=grp*half+c; cip,gip=_p2p_core_gw(dc,g,cs)
                    cfg+=_iface_l3(lm[(h,gw)][0],cip,f"To {gw}"); nei.append((gip,_asn_gw(dc,g)))
                cfg+=f"ip prefix-list PL_ALL seq 5 permit {sp}.0.0.0/8 le 24\n!\n"
                cfg+=_bgp_header(asn,rid)
                for nip,nas in nei: cfg+=_bgp_nei(nip,nas)
                cfg+=f"  aggregate-address {sp}.0.0.0 255.0.0.0 as-set summary-only\n"
                cfg+=_bgp_footer()+_ios_tail(); devices[h]=cfg
        for g in range(k):
            h=f"{pfx}gw{g}"; asn=_asn_gw(dc,g); rid=_gw_lo(dc,g)
            cfg=_ios_header(h)+f"interface Loopback0\n ip address {rid} 255.255.255.255\n!\n"
            nei=[]
            for grp in range(half):
                for c in range(half):
                    core=f"{pfx}core-g{grp}-c{c}"; cs=grp*half+c; cip,gip=_p2p_core_gw(dc,g,cs)
                    cfg+=_iface_l3(lm[(h,core)][0],gip,f"To {core}"); nei.append((cip,_asn_core(dc)))
            odc=1-dc
            for g2 in range(k):
                peer=f"dc{odc}-gw{g2}"
                if dc==0: mip,pip=_p2p_gw_gw(g,g2)
                else: pip,mip=_p2p_gw_gw(g2,g)
                cfg+=_iface_l3(lm[(h,peer)][0],mip,f"To {peer}"); nei.append((pip,_asn_gw(odc,g2)))
            cfg+=_bgp_header(asn,rid)
            for nip,nas in nei: cfg+=_bgp_nei(nip,nas)
            cfg+=_bgp_footer()+_ios_tail(); devices[h]=cfg
    for h,cfg in devices.items():
        with open(os.path.join(cfg_dir,f"{h}.cfg"),"w") as f: f.write(cfg)
    for dc in range(2):
        sp=1 if dc==0 else 9
        for pod in range(k):
            for e in range(half):
                for hh in range(half):
                    hn=f"dc{dc}-server-p{pod}-e{e}-h{hh}"
                    hcfg={"hostname":hn,"hostInterfaces":{"eth0":{"name":"eth0","prefix":f"{sp}.{pod}.{e}.{hh+2}/24","gateway":f"{sp}.{pod}.{e}.1"}}}
                    with open(os.path.join(hosts_dir,f"{hn}.json"),"w") as f: json.dump(hcfg,f,indent=4)
    nr=2*(k*half+k*half+half*half+k)
    print(f"[OK] Cross-DC: 2×fattree({k})+2×{k}gw = {nr} routers, {len(links)} links")
    return outdir,lm

def create_crossdc_before(k):
    base=f"data/crossdc/crossdck{str(k).zfill(3)}"; before=os.path.join(base,"before")
    if os.path.exists(before): shutil.rmtree(before)
    half=k//2; cfg_src=os.path.join(base,"configs"); cfg_dst=os.path.join(before,"configs")
    os.makedirs(cfg_dst)
    for fn in os.listdir(cfg_src):
        with open(os.path.join(cfg_src,fn)) as f: content=f.read()
        content=content.replace("  maximum-paths 8\n","")
        if "-edge-" in fn and fn.endswith(".cfg"):
            h=fn[:-4]; parts=h.split("-"); dc=int(parts[0][2:]); pod=int(parts[2][1:]); eidx=int(parts[3][1:])
            _,a0ip=_p2p_edge_agg(dc,pod,eidx,0); asn=_asn_edge(dc,pod,eidx,k)
            pin=["!","route-map RM_PIN permit 10"," set local-preference 200","route-map RM_PIN permit 20","!",
                 f"router bgp {asn}"," address-family ipv4",f"  neighbor {a0ip} route-map RM_PIN in","!"]
            lines=content.rstrip().split("\n"); idx=len(lines)
            for i in range(len(lines)-1,-1,-1):
                if lines[i].strip()=="end": idx=i; break
            lines=lines[:idx]+pin+lines[idx:]; content="\n".join(lines)+"\n"
        with open(os.path.join(cfg_dst,fn),"w") as f: f.write(content)
    for sub in ["hosts"]:
        s=os.path.join(base,sub); d=os.path.join(before,sub)
        if os.path.isdir(s): shutil.copytree(s,d)
    t=os.path.join(base,"example_layer1_topology.json")
    if os.path.exists(t): shutil.copy2(t,os.path.join(before,"example_layer1_topology.json"))
    print(f"[OK] Cross-DC before/ created with LP=200 pin")

# ── Path & changes ──
@dataclass
class CrossDCPath:
    src_dc:int; src_edge:Tuple[int,int]; dst_dc:int; dst_edge:Tuple[int,int]
    src_agg:int; src_core:int; src_gw:int; dst_gw:int
    def to_node_list(self):
        sp,se=self.src_edge; dp,de=self.dst_edge; sd=self.src_dc; dd=self.dst_dc
        return [f"dc{sd}-edge-p{sp}-e{se}",f"dc{sd}-agg-p{sp}-a{self.src_agg}",
                f"dc{sd}-core-g{self.src_agg}-c{self.src_core}",f"dc{sd}-gw{self.src_gw}",
                f"dc{dd}-gw{self.dst_gw}",f"dc{dd}-core-g0-c0",f"dc{dd}-agg-p{dp}-a0",f"dc{dd}-edge-p{dp}-e{de}"]
    def to_node_list_with_servers(self):
        sp,se=self.src_edge; dp,de=self.dst_edge
        return [f"dc{self.src_dc}-server-p{sp}-e{se}-h0"]+self.to_node_list()+[f"dc{self.dst_dc}-server-p{dp}-e{de}-h0"]
    def to_dict(self):
        return {"src_agg":self.src_agg,"src_core":self.src_core,"src_gw":self.src_gw,"dst_gw":self.dst_gw,
                "node_list":self.to_node_list(),"node_list_with_servers":self.to_node_list_with_servers()}

def _default_xdc_path(se,de): return CrossDCPath(0,se,1,de,0,0,0,0)

def _xgen_lp(se,de,k):
    sp,s=se; half=k//2; out=[]
    for a in range(1,half):
        _,aip=_p2p_edge_agg(0,sp,s,a); rm=f"RM_LP_AGG{a}"
        out.append({"after":{"src_agg":a,"src_core":0,"src_gw":0,"dst_gw":0},"diff":{"device":f"dc0-edge-p{sp}-e{s}",
            "add_lines":[f"route-map {rm} permit 10",f" set local-preference 300",f"route-map {rm} permit 20",f"!",
                f"router bgp {_asn_edge(0,sp,s,k)}",f" address-family ipv4",f"  neighbor {aip} route-map {rm} in"],
            "description":f"LP=300 on dc0-edge from agg{a}"}})
    for c in range(1,half):
        _,cip=_p2p_agg_core(0,sp,0,c); rm=f"RM_LP_CORE{c}"
        out.append({"after":{"src_agg":0,"src_core":c,"src_gw":0,"dst_gw":0},"diff":{"device":f"dc0-agg-p{sp}-a0",
            "add_lines":[f"route-map {rm} permit 10",f" set local-preference 200",f"route-map {rm} permit 20",f"!",
                f"router bgp {_asn_agg(0,sp)}",f" address-family ipv4",f"  neighbor {cip} route-map {rm} in"],
            "description":f"LP=200 on dc0-agg0 from core{c}"}})
    return out

def _xgen_med(se,de,k):
    sp,s=se; half=k//2; out=[]
    if half<2: return out
    _,c0ip=_p2p_agg_core(0,sp,0,0); rm="RM_MED_CORE0"
    out.append({"after":{"src_agg":0,"src_core":1,"src_gw":0,"dst_gw":0},"diff":{"device":f"dc0-agg-p{sp}-a0",
        "add_lines":[f"route-map {rm} permit 10",f" set metric 9999",f"route-map {rm} permit 20",f"!",
            f"router bgp {_asn_agg(0,sp)}",f" address-family ipv4",f"  neighbor {c0ip} route-map {rm} in"],
        "description":"MED=9999 on dc0-agg0 from core0"}})
    return out

def _xgen_static(se,de,k):
    sp,s=se; dp,d=de; half=k//2; dn=f"9.{dp}.{d}.0"; out=[]
    for a in range(1,half):
        _,aip=_p2p_edge_agg(0,sp,s,a)
        out.append({"after":{"src_agg":a,"src_core":0,"src_gw":0,"dst_gw":0},"diff":{"device":f"dc0-edge-p{sp}-e{s}",
            "add_lines":[f"ip route {dn} 255.255.255.0 {aip}"],"description":f"Static /24 on dc0-edge→agg{a}"}})
    for c in range(1,half):
        _,cip=_p2p_agg_core(0,sp,0,c)
        out.append({"after":{"src_agg":0,"src_core":c,"src_gw":0,"dst_gw":0},"diff":{"device":f"dc0-agg-p{sp}-a0",
            "add_lines":[f"ip route {dn} 255.255.255.0 {cip}"],"description":f"Static /24 on dc0-agg0→core{c}"}})
    return out

def _xgen_bgpnet(se,de,k):
    sp,s=se; dp,d=de; half=k//2; dn=f"9.{dp}.{d}.0"; out=[]
    for a in range(half):
        for c in range(half):
            if a==0 and c==0: continue
            _,cip=_p2p_agg_core(0,sp,a,c); agg=f"dc0-agg-p{sp}-a{a}"
            out.append({"after":{"src_agg":a,"src_core":c,"src_gw":0,"dst_gw":0},"diff":{"device":agg,
                "add_lines":[f"ip route {dn} 255.255.255.0 {cip}",f"!",f"router bgp {_asn_agg(0,sp)}",
                    f" address-family ipv4",f"  network {dn} mask 255.255.255.0"],
                "description":f"BGP net /24 on {agg}"}})
    return out

def _xgen_pfxagg(se,de,k):
    sp,s=se; dp,d=de; half=k//2; dn=f"9.{dp}.{d}.0"; out=[]
    for a in range(half):
        for c in range(half):
            if a==0 and c==0: continue
            _,cip=_p2p_agg_core(0,sp,a,c); agg=f"dc0-agg-p{sp}-a{a}"
            out.append({"after":{"src_agg":a,"src_core":c,"src_gw":0,"dst_gw":0},"diff":{"device":agg,
                "add_lines":[f"ip route {dn} 255.255.255.0 {cip}",f"!",f"router bgp {_asn_agg(0,sp)}",
                    f" address-family ipv4",f"  network {dn} mask 255.255.255.0",
                    f"  aggregate-address {dn} 255.255.255.0 as-set"],
                "description":f"Pfx agg /24 on {agg}"}})
    return out

def _xgen_shutdown(se,de,k,lm):
    sp,s=se; half=k//2; out=[]
    if half<2: return out
    edge=f"dc0-edge-p{sp}-e{s}"; agg0=f"dc0-agg-p{sp}-a0"
    ie=lm.get((edge,agg0),(None,))[0]
    if ie: out.append({"after":{"src_agg":1,"src_core":0,"src_gw":0,"dst_gw":0},"diff":{"device":edge,
        "add_lines":[f"interface {ie}",f" shutdown"],"description":f"Shutdown {ie} on {edge}"}})
    core0=f"dc0-core-g0-c0"; ia=lm.get((agg0,core0),(None,))[0]
    if ia: out.append({"after":{"src_agg":0,"src_core":1,"src_gw":0,"dst_gw":0},"diff":{"device":agg0,
        "add_lines":[f"interface {ia}",f" shutdown"],"description":f"Shutdown {ia} on {agg0}"}})
    return out

CHANGE_TYPES=["local_preference","med","static_route","bgp_network","prefix_aggregation","interface_shutdown"]
_XGENS={"local_preference":lambda s,d,k,lm:_xgen_lp(s,d,k),"med":lambda s,d,k,lm:_xgen_med(s,d,k),
    "static_route":lambda s,d,k,lm:_xgen_static(s,d,k),"bgp_network":lambda s,d,k,lm:_xgen_bgpnet(s,d,k),
    "prefix_aggregation":lambda s,d,k,lm:_xgen_pfxagg(s,d,k),
    "interface_shutdown":lambda s,d,k,lm:_xgen_shutdown(s,d,k,lm)}

def generate_crossdc_changes(k,num_pairs=20,num_changes=5,pairs=None):
    base=f"data/crossdc/crossdck{str(k).zfill(3)}"
    if not os.path.exists(os.path.join(base,"example_layer1_topology.json")): generate_crossdc(k)
    create_crossdc_before(k)
    with open(os.path.join(base,"example_layer1_topology.json")) as f: links=json.load(f)["edges"]
    lm={}
    for link in links:
        n1,n2=link["node1"]["hostname"],link["node2"]["hostname"]
        i1,i2=link["node1"]["interfaceName"],link["node2"]["interfaceName"]
        lm[(n1,n2)]=(i1,i2); lm[(n2,n1)]=(i2,i1)
    half=k//2
    if pairs is None:
        dc0e=[(p,e) for p in range(k) for e in range(half)]
        dc1e=[(p,e) for p in range(k) for e in range(half)]
        xp=[(a,b) for a in dc0e for b in dc1e]; random.shuffle(xp); pairs=xp[:num_pairs]
        source="random cross-DC"
    else:
        source="user-specified cross-DC"
    print(f"[OK] {len(pairs)} {source} pairs for k={k}")
    for ct in CHANGE_TYPES:
        p=os.path.join(base,ct)
        if os.path.exists(p): shutil.rmtree(p)
    all_inst=[]
    for pid,(se,de) in enumerate(pairs):
        sp,s=se; dp,d=de; bp=_default_xdc_path(se,de)
        for ct in CHANGE_TYPES:
            avail=_XGENS[ct](se,de,k,lm)
            selected=[avail[i%len(avail)] for i in range(num_changes)]
            for cid,chg in enumerate(selected):
                af=chg["after"]
                ap=CrossDCPath(0,se,1,de,af["src_agg"],af["src_core"],af["src_gw"],af["dst_gw"])
                cd_dir=os.path.join(base,ct,f"pair{pid}_change{cid}")
                os.makedirs(cd_dir,exist_ok=True)
                with open(os.path.join(cd_dir,"change.json"),"w") as f: json.dump([chg["diff"]],f,indent=2)
                all_inst.append({"pair_id":pid,"change_type":ct,"change_id":cid,"src_dc":0,"dst_dc":1,
                    "src_edge":list(se),"dst_edge":list(de),"dst_prefix":f"9.{dp}.{d}.0/24",
                    "before_path":bp.to_dict(),"after_path":ap.to_dict(),
                    "change_device":chg["diff"]["device"],"change_description":chg["diff"]["description"]})
        print(f"  Pair {pid}: dc0-edge-p{sp}-e{s} → dc1-edge-p{dp}-e{d}")
    with open(os.path.join(base,"ground_truth.json"),"w") as f: json.dump(all_inst,f,indent=2)
    with open(os.path.join(base,"endpoint_pairs.json"),"w") as f:
        json.dump([{"pair_id":i,"src_edge":list(s),"dst_edge":list(d)} for i,(s,d) in enumerate(pairs)],f,indent=2)
    for ct in CHANGE_TYPES:
        ci=[x for x in all_inst if x["change_type"]==ct]
        with open(os.path.join(base,f"ground_truth_{ct}.json"),"w") as f: json.dump(ci,f,indent=2)
        print(f"  {ct}: {len(ci)}")
    print(f"[OK] Total: {len(all_inst)} instances")
    return all_inst


if __name__=="__main__":
    parser=ArgumentParser(); parser.add_argument("k",type=int)
    parser.add_argument("--num-pairs",type=int,default=20); parser.add_argument("--num-changes",type=int,default=5)
    parser.add_argument("--pairs-file",help="JSON file with user-specified query pairs.")
    args=parser.parse_args()
    k=args.k
    if k%2!=0 or k<4: print("k must be even and >= 4"); sys.exit(1)
    pairs=load_query_pairs(args.pairs_file,k,"crossdc") if args.pairs_file else None
    generate_crossdc(k); generate_crossdc_changes(k,args.num_pairs,args.num_changes,pairs=pairs)
