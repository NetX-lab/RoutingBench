---
name: find-route-map-policy
description: Determine the full routing policy applied between a device and a specific BGP neighbor. Use when you need to understand all match/set actions on a peering session.
---

# Find Route-Map Policy

## Objective
Get the complete routing policy (all match and set clauses) between a device and a specific BGP neighbor, for both inbound and outbound directions.

## Workflow

### Step 1: Get BGP Neighbors
Call `get_bgp_neighbors(device)` to find the route-map names applied to the target neighbor.

### Step 2: Read Route-Maps
For each route-map (in/out), call `extract_match_set_clauses(device, route_map_name)` to get all clauses.

### Step 3: Resolve References
For each clause, resolve prefix-lists and community-lists via `read_config_block` to understand what traffic is matched.

## Returns
```json
{"device": "edge-p0-e0", "neighbor": "2.0.0.1", "remote_as": 20000,
 "route_map_in": {"name": "RM_PIN", "clauses": [{"action": "permit", "seq": 10, "match": [], "set": ["set local-preference 200"]}]},
 "route_map_out": {"name": "RM_EDGE_OUT", "clauses": [...]}}
```

## Guidelines
- A route-map with no match clause is an implicit match-all
- `permit 20` with no match/set is a catch-all permit (pass remaining routes unchanged)
- Multiple clauses are evaluated in sequence order; first match wins
