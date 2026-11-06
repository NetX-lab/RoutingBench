"""Tool: get_topology_paths — topology-aware candidate path enumeration.

Fat-tree path structure:
  fattree/compound:  src_edge → agg → core → agg → dst_edge   (5 hops)
  crossdc (same DC): dcX-edge → dcX-agg → dcX-core → dcX-agg → dcX-edge
  crossdc (cross DC): dcX-edge → dcX-agg → dcX-core → dcX-gw → dcY-gw → dcY-core → dcY-agg → dcY-edge
"""
from agents.agent_skills.scripts import load_topo

_adj_cache = {}


def _build_adj(topo_id, topo):
    """Build adjacency dict from topology, skipping server nodes. Cached."""
    if topo_id in _adj_cache:
        return _adj_cache[topo_id]
    adj = {}
    for edge in topo.get("edges", []):
        n1, n2 = edge["node1"]["hostname"], edge["node2"]["hostname"]
        if "server" in n1 or "server" in n2:
            continue
        adj.setdefault(n1, set()).add(n2)
        adj.setdefault(n2, set()).add(n1)
    _adj_cache[topo_id] = adj
    return adj


def _fattree_paths(adj, src, dst, max_paths=10):
    """Enumerate edge→agg→core→agg→edge paths (fattree / compound)."""
    # src pod and dst pod from names like edge-p{pod}-e{idx}
    paths = []
    src_aggs = [n for n in adj.get(src, set()) if "agg" in n]
    dst_aggs = [n for n in adj.get(dst, set()) if "agg" in n]
    for sa in sorted(src_aggs):
        cores = [n for n in adj.get(sa, set()) if "core" in n]
        for core in sorted(cores):
            for da in sorted(dst_aggs):
                if core in adj.get(da, set()) and da in adj.get(dst, set()):
                    paths.append([src, sa, core, da, dst])
                    if len(paths) >= max_paths:
                        return paths
    return paths


def _crossdc_same_dc_paths(adj, src, dst, max_paths=10):
    """Enumerate intra-DC paths: dcX-edge→dcX-agg→dcX-core→dcX-agg→dcX-edge."""
    paths = []
    src_aggs = [n for n in adj.get(src, set()) if "agg" in n]
    dst_aggs = [n for n in adj.get(dst, set()) if "agg" in n]
    for sa in sorted(src_aggs):
        cores = [n for n in adj.get(sa, set()) if "core" in n]
        for core in sorted(cores):
            for da in sorted(dst_aggs):
                if core in adj.get(da, set()) and da in adj.get(dst, set()):
                    paths.append([src, sa, core, da, dst])
                    if len(paths) >= max_paths:
                        return paths
    return paths


def _crossdc_cross_dc_paths(adj, src, dst, max_paths=10):
    """Enumerate cross-DC paths: edge→agg→core→gw→gw→core→agg→edge."""
    paths = []
    src_aggs = [n for n in adj.get(src, set()) if "agg" in n]
    dst_aggs = [n for n in adj.get(dst, set()) if "agg" in n]
    for sa in sorted(src_aggs):
        src_cores = [n for n in adj.get(sa, set()) if "core" in n]
        for sc in sorted(src_cores):
            src_gws = [n for n in adj.get(sc, set()) if "gw" in n]
            for sg in sorted(src_gws):
                dst_gws = [n for n in adj.get(sg, set()) if "gw" in n]
                for dg in sorted(dst_gws):
                    dst_cores = [n for n in adj.get(dg, set()) if "core" in n]
                    for dc in sorted(dst_cores):
                        for da in sorted(dst_aggs):
                            if dc in adj.get(da, set()) and da in adj.get(dst, set()):
                                paths.append([src, sa, sc, sg, dg, dc, da, dst])
                                if len(paths) >= max_paths:
                                    return paths
    return paths


def _real_dc_paths(adj, src, dst, max_paths=200):
    """Enumerate TOR→Leaf→Spine→Leaf→TOR paths for real DC topology.
    
    Real device naming:
    - TOR: contains 't0' (e.g., lvl08-0101-0937-08lt0)
    - Leaf: contains 't1' (e.g., lvl08-0101-0937-12t1)
    - Spine: contains 't2' (e.g., lvl08-0101-0100-10t2)
    """
    paths = []
    # src TOR → Leaf (t1 neighbors)
    src_leafs = sorted(n for n in adj.get(src, set()) if "t1" in n)
    # dst TOR → Leaf (t1 neighbors)
    dst_leafs = sorted(n for n in adj.get(dst, set()) if "t1" in n)
    
    for sl in src_leafs:
        # Leaf → Spine (t2 neighbors)
        spines = sorted(n for n in adj.get(sl, set()) if "t2" in n)
        for spine in spines:
            # Spine → dst Leaf
            for dl in dst_leafs:
                if dl in adj.get(spine, set()):
                    paths.append([src, sl, spine, dl, dst])
                    if len(paths) >= max_paths:
                        return paths
    return paths


def _classify_device(name):
    """Classify real DC device by layer."""
    nl = name.lower()
    if 't0' in nl or 'lt0' in nl: return 'TOR'
    if 't1' in nl: return 'Leaf'
    if 't2' in nl: return 'Spine'
    if 'rh' in nl: return 'RH'
    if nl.endswith('ra'): return 'RA'
    if nl.startswith('icr'): return 'ICR'
    if nl.startswith('ibr'): return 'IBR'
    if nl.startswith('owr'): return 'OWR'
    if nl.startswith('rwa'): return 'RWA'
    if nl.startswith('swan'): return 'SWAN'
    return 'unknown'


def _real_xdc_dag(adj, src, dst):
    """Build cross-DC paths by splitting into src-DC + WAN + dst-DC segments.
    
    Returns a DAG-like structure with enumerated sample paths.
    """
    src_type = _classify_device(src)
    dst_type = _classify_device(dst)
    
    # Identify src/dst DC Spine devices and WAN entry/exit devices
    src_prefix = src.split("-")[0] if "-" in src else ""
    
    # Step 1: Find src-side inner-DC path (TOR→Leaf→Spine)
    src_leafs = sorted(n for n in adj.get(src, set()) if _classify_device(n) == 'Leaf')
    
    # Step 2: From Spine, find upward chain to WAN entry
    # For each spine, trace upward: Spine→RH→(RA→ICR or RWA)
    src_spines = set()
    for sl in src_leafs:
        for nb in adj.get(sl, set()):
            if _classify_device(nb) == 'Spine':
                src_spines.add(nb)
    
    # Find WAN entry points (ICR or RWA reachable from src)
    wan_entries = set()
    src_upper = {}  # maps spine -> list of upper layer paths to WAN entry
    
    for spine in sorted(src_spines):
        rhs = [n for n in adj.get(spine, set()) if _classify_device(n) == 'RH']
        for rh in rhs:
            # RH → RA → ICR (AMS architecture)
            ras = [n for n in adj.get(rh, set()) if _classify_device(n) == 'RA']
            for ra in ras:
                icrs = [n for n in adj.get(ra, set()) if _classify_device(n) == 'ICR']
                for icr in icrs:
                    wan_entries.add(icr)
            # RH → RWA (LVL architecture)
            rwas = [n for n in adj.get(rh, set()) if _classify_device(n) == 'RWA']
            for rwa in rwas:
                wan_entries.add(rwa)
    
    # Step 3: Find dst-side WAN exit points and inner-DC paths
    dst_leafs = sorted(n for n in adj.get(dst, set()) if _classify_device(n) == 'Leaf')
    dst_spines = set()
    for dl in dst_leafs:
        for nb in adj.get(dl, set()):
            if _classify_device(nb) == 'Spine':
                dst_spines.add(nb)
    
    wan_exits = set()
    for spine in sorted(dst_spines):
        rhs = [n for n in adj.get(spine, set()) if _classify_device(n) == 'RH']
        for rh in rhs:
            ras = [n for n in adj.get(rh, set()) if _classify_device(n) == 'RA']
            for ra in ras:
                icrs = [n for n in adj.get(ra, set()) if _classify_device(n) == 'ICR']
                for icr in icrs:
                    wan_exits.add(icr)
            rwas = [n for n in adj.get(rh, set()) if _classify_device(n) == 'RWA']
            for rwa in rwas:
                wan_exits.add(rwa)
    
    # Step 4: BFS WAN paths between entries and exits
    wan_devices_set = set(d for d in adj if _classify_device(d) in ('IBR','OWR','SWAN','ICR','RWA'))
    
    wan_paths = []
    for entry in sorted(wan_entries)[:4]:  # limit to 4 entries
        for exit_dev in sorted(wan_exits)[:4]:
            # BFS from entry to exit through WAN
            from collections import deque
            q = deque([(entry, [entry])])
            visited_bfs = {entry}
            found = []
            while q and len(found) < 3:
                cur, path = q.popleft()
                if cur == exit_dev and len(path) > 1:
                    found.append(path)
                    continue
                if len(path) > 12:
                    continue
                for nb in adj.get(cur, set()):
                    if nb in visited_bfs:
                        continue
                    ct = _classify_device(nb)
                    if ct in ('IBR','OWR','SWAN') or nb == exit_dev:
                        visited_bfs.add(nb)
                        q.append((nb, path + [nb]))
            wan_paths.extend(found)
    
    # Step 5: Build full paths by combining src-side + WAN + dst-side
    # src inner: TOR → Leaf → Spine
    src_inner_paths = []
    for sl in src_leafs:
        spines = sorted(n for n in adj.get(sl, set()) if _classify_device(n) == 'Spine')
        for spine in spines:
            src_inner_paths.append([src, sl, spine])
    
    # dst inner: Spine → Leaf → TOR
    dst_inner_paths = []
    for dl in dst_leafs:
        spines = sorted(n for n in adj.get(dl, set()) if _classify_device(n) == 'Spine')
        for spine in spines:
            dst_inner_paths.append([spine, dl, dst])
    
    # Combine: enumerate full paths
    full_paths = []
    for sp in src_inner_paths[:16]:
        src_spine = sp[-1]
        # Find RH → (RA→ICR or RWA) from this spine
        rhs = [n for n in adj.get(src_spine, set()) if _classify_device(n) == 'RH']
        for rh in rhs[:4]:
            upper_devs = []
            # Check RA→ICR path
            ras = [n for n in adj.get(rh, set()) if _classify_device(n) == 'RA']
            for ra in ras[:2]:
                icrs = [n for n in adj.get(ra, set()) if _classify_device(n) == 'ICR']
                for icr in icrs[:2]:
                    upper_devs.append([rh, ra, icr])
            # Check RWA path
            rwas = [n for n in adj.get(rh, set()) if _classify_device(n) == 'RWA']
            for rwa in rwas[:2]:
                upper_devs.append([rh, rwa])
            
            for up in upper_devs[:4]:
                wan_entry = up[-1]
                # Find matching WAN paths
                for wp in wan_paths:
                    if wp[0] == wan_entry:
                        wan_exit = wp[-1]
                        # Find dst segments reachable from WAN exit
                        for dp in dst_inner_paths[:16]:
                            dst_spine = dp[0]
                            # Check if WAN exit connects to dst spine through RH(/RA)
                            exit_type = _classify_device(wan_exit)
                            # RWA→RH→Spine or ICR→RA→RH→Spine
                            if exit_type == 'RWA':
                                for rh2 in adj.get(wan_exit, set()):
                                    if _classify_device(rh2) == 'RH' and dst_spine in adj.get(rh2, set()):
                                        full = sp + up + wp[1:] + [rh2] + dp
                                        full_paths.append(full)
                            elif exit_type == 'ICR':
                                for ra2 in adj.get(wan_exit, set()):
                                    if _classify_device(ra2) == 'RA':
                                        for rh2 in adj.get(ra2, set()):
                                            if _classify_device(rh2) == 'RH' and dst_spine in adj.get(rh2, set()):
                                                full = sp + up + wp[1:] + [ra2, rh2] + dp
                                                full_paths.append(full)
                        if len(full_paths) >= 500:
                            break
                if len(full_paths) >= 500:
                    break
            if len(full_paths) >= 500:
                break
        if len(full_paths) >= 500:
            break
    
    return {
        "src": src,
        "dst": dst,
        "mode": "cross_dc_dag",
        "paths": full_paths[:500],
        "total_found": len(full_paths),
        "src_leafs": len(src_leafs),
        "dst_leafs": len(dst_leafs),
        "wan_entries": len(wan_entries),
        "wan_exits": len(wan_exits),
        "wan_paths_found": len(wan_paths),
    }


def run(before_dir, src, dst, max_paths=200):
    topo = load_topo(before_dir)
    if not topo:
        return {"error": "Topology not found"}
    adj = _build_adj(before_dir, topo)

    if src not in adj:
        return {"error": f"Source {src} not found in topology"}
    if dst not in adj:
        return {"error": f"Destination {dst} not found in topology"}

    # Detect topology type from node names
    is_crossdc_synthetic = src.startswith("dc") and dst.startswith("dc")
    is_real_dc = ("t0" in src or "lt0" in src) and ("t0" in dst or "lt0" in dst)
    
    # Check if cross-DC real (different DC prefixes)
    src_dc_prefix = src.split("-")[0] if "-" in src else src.split(".")[0]
    dst_dc_prefix = dst.split("-")[0] if "-" in dst else dst.split(".")[0]
    is_real_xdc = is_real_dc and src_dc_prefix != dst_dc_prefix

    if is_real_xdc:
        return _real_xdc_dag(adj, src, dst)
    elif is_real_dc:
        paths = _real_dc_paths(adj, src, dst, max_paths)
    elif is_crossdc_synthetic:
        src_dc = src.split("-")[0]
        dst_dc = dst.split("-")[0]
        if src_dc == dst_dc:
            paths = _crossdc_same_dc_paths(adj, src, dst, max_paths)
        else:
            paths = _crossdc_cross_dc_paths(adj, src, dst, max_paths)
    else:
        paths = _fattree_paths(adj, src, dst, max_paths)

    return {"src": src, "dst": dst, "paths": paths}
