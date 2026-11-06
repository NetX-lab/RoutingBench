---
name: find-med-for-prefix
description: Determine the MED (Multi-Exit Discriminator) value set for routes to a specific prefix on a device. Use when analyzing whether MED affects path selection between peers with the same AS.
---

# Find MED for Prefix

## Objective
Determine the MED value affecting routes to a given prefix on a device. MED is compared only among routes from the same neighboring AS, after LP and AS-path are tied.

## Workflow

### Step 1: Get BGP Neighbors
Call `get_bgp_neighbors(device)` to find all peers and their route-maps.

### Step 2: Examine Route-Maps
For each neighbor with inbound or outbound route-map:
- Call `extract_match_set_clauses(device, route_map_name)`.
- Look for `set metric <value>` in set clauses.

### Step 3: Report
If found, report the MED value, direction (in/out), and the neighbor it applies to.
If not found, report "MED not configured" (default MED = 0).

## Returns
```json
{"device": "agg-p0-a0", "prefix": "1.1.0.0/24", "med_entries": [{"neighbor": "3.0.0.1", "route_map": "RM_MED_CORE0", "direction": "in", "med_value": 9999}]}
```

## Guidelines
- MED is only compared between routes from the SAME neighboring AS
- Lower MED is preferred
- MED is checked AFTER LP and AS-path in BGP selection
- Default MED is 0 when not set
