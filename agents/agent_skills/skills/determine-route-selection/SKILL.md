---
name: determine-route-selection
description: Determine which routing entry wins on a device for a prefix and why. This is a composite skill that calls multiple extraction skills and applies BGP selection rules.
---

# Determine Route Selection

## Objective
Determine the winning route on a device for a given prefix by checking all route types and applying selection priority.

## Workflow

### Step 1: Check Static Routes
```json
[{"tool": "search_config", "args": {"device": "<DEVICE>", "regex": "ip route <PREFIX_NET>"}}]
```
Static routes have AD=1, highest priority. If found, this wins.

### Step 2: Check BGP Network Statement
```json
[{"tool": "search_config", "args": {"device": "<DEVICE>", "regex": "network <PREFIX_NET>"}}]
```

### Step 3: Check Local Preference
```json
[{"tool": "get_bgp_neighbors", "args": {"device": "<DEVICE>"}},
 {"tool": "extract_match_set_clauses", "args": {"device": "<DEVICE>", "route_map": "<RM_NAME>"}}]
```
Check inbound route-maps for `set local-preference`. Highest LP wins.

### Step 4: Check MED
Look for `set metric` in route-map clauses. Lower MED preferred (only compared within same AS).

### Step 5: Check Interface/Neighbor Status
```json
[{"tool": "get_topology_adjacency", "args": {"device": "<DEVICE>"}},
 {"tool": "get_interface_config", "args": {"device": "<DEVICE>", "intf": "<INTF>"}}]
```
Verify the selected next-hop's interface is up.

### Step 6: Apply Selection Priority
1. Static (AD=1) > Connected > BGP
2. Within BGP: Highest LP > Shortest AS-path > Lowest MED > Lowest Router-ID

**To query the after-change state**, add `"phase": "after"` to tool calls.

## Returns
```json
{"device": "edge-p0-e0", "prefix": "1.1.0.0/24",
 "winner": "bgp_default",
 "static": {"static_route": "not configured"},
 "lp": {"lp_entries": [{"neighbor": "2.0.0.1", "lp_value": 200}]},
 "med": {"med": "not configured"}}
```

## Guidelines
- This skill composes other skills — it's the go-to for understanding hop-by-hop decisions
- The winner field summarizes: "static_route", "bgp_network", or "bgp_default"
- Always check static routes first — they silently override BGP
