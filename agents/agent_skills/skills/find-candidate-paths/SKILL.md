---
name: find-candidate-paths
description: Enumerate plausible routing paths from source to destination edge routers. Use as the first step to identify which paths exist before analyzing which one is selected.
---

# Find Candidate Paths

## Objective
Enumerate all topologically valid paths between two edge routers. In a fat-tree, inter-pod paths have 5 hops (edge→agg→core→agg→edge).

## Workflow

### Step 1: BFS Path Enumeration
```json
[{"tool": "get_topology_paths", "args": {"src": "<SRC_EDGE>", "dst": "<DST_EDGE>"}}]
```
Returns all simple paths between the two edge routers.

### Step 2: Filter by Fat-Tree Structure
Keep paths with correct hop counts: 5 for inter-pod, 3 for intra-pod.

### Step 3: Feasibility Check (Optional)
For each path, check BGP sessions exist at each hop via `get_bgp_neighbors`.

## Returns
```json
{"src": "edge-p0-e0", "dst": "edge-p1-e0", "candidate_paths": [
  {"path": ["edge-p0-e0", "agg-p0-a0", "core-g0-c0", "agg-p1-a0", "edge-p1-e0"], "hops": 5, "feasible": true},
  {"path": ["edge-p0-e0", "agg-p0-a1", "core-g1-c0", "agg-p1-a1", "edge-p1-e0"], "hops": 5, "feasible": true}
]}
```

## Guidelines
- Inter-pod paths always go: edge → agg → core → agg → edge (5 hops)
- The agg index determines the core group: agg-a{X} connects to core-g{X}-c{Y}
- Number of candidate paths = (k/2)² for inter-pod
