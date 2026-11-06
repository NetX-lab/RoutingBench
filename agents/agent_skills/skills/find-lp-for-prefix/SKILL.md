---
name: find-lp-for-prefix
description: Determine the BGP local preference affecting routes to a specific prefix on a device. Use when you need to understand which neighbor a router prefers for a destination prefix based on LP configuration.
---

# Find Local Preference for Prefix

## Objective
Determine the BGP local preference value that affects routes to a given prefix on a specific device. LP is the most influential BGP attribute after administrative distance.

## Why This Is a Skill (Not a Simple Lookup)
LP is rarely configured as a flat per-prefix value. It is typically applied via a route-map attached to a BGP neighbor, where the route-map's match clause references a prefix-list or community-list. This skill traces the full indirect chain.

## Workflow

### Step 1: Get BGP Neighbors
```json
[{"tool": "get_bgp_neighbors", "args": {"device": "<DEVICE>"}}]
```
This returns all BGP peers and their applied route-maps (inbound and outbound).

### Step 2: Examine Route-Maps
For each neighbor with an inbound route-map (`route_map_in`):
```json
[{"tool": "extract_match_set_clauses", "args": {"device": "<DEVICE>", "route_map": "<ROUTE_MAP_NAME>"}}]
```

### Step 3: Check Match Conditions
For each route-map clause:
- If `match ip address prefix-list <name>`:
  ```json
  [{"tool": "read_config_block", "args": {"device": "<DEVICE>", "block_type": "prefix-list", "name": "<PL_NAME>"}}]
  ```
- If no match clause (implicit match-all): applies to all routes from that neighbor.

### Step 4: Extract LP Value
If a matching clause contains `set local-preference <value>`, report that value.

### Step 5: Report Default
If no route-map sets LP for this prefix, the default LP is 100.

**To query the after-change state**, add `"phase": "after"` to any tool call:
```json
[{"tool": "get_bgp_neighbors", "args": {"device": "<DEVICE>", "phase": "after"}}]
```

## Returns
```json
{
  "device": "edge-p0-e0",
  "prefix": "1.1.0.0/24",
  "lp_value": 200,
  "mechanism": "route-map RM_PIN seq 10 -> set local-preference 200",
  "neighbor": "2.0.0.1"
}
```
Or if default: `{"lp_value": 100, "mechanism": "default"}`

## Guidelines
- Always check ALL inbound route-maps, not just the first one
- LP=100 is the default when no route-map overrides it
- Higher LP wins in BGP path selection
- LP is compared BEFORE AS-path, MED, and router-ID
