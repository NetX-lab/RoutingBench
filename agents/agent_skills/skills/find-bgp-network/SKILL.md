---
name: find-bgp-network
description: Check whether a device originates a prefix via a BGP network statement. Use when analyzing if a router locally originates a route into BGP.
---

# Find BGP Network Statement

## Objective
Check if the device originates a specific prefix via `network` statement in BGP config. A network statement makes the router originate the prefix into BGP (shorter AS-path), which can attract traffic via longest-prefix-match.

## Workflow

### Step 1: Search BGP Config
Call `search_config(device, "network <prefix_network>")` to find network statements.

### Step 2: Verify Backing Route
A BGP network statement requires a matching route in the RIB (often a static route to Null0). Check with `search_config(device, "ip route <prefix_network>")`.

## Returns
```json
{"device": "agg-p0-a1", "prefix": "1.1.0.0/24", "bgp_network": "  network 1.1.0.0 mask 255.255.255.0"}
```

## Guidelines
- BGP network statement only works if there's a matching route in RIB
- Static route to Null0 is commonly used as the backing route
- The originated /24 wins over aggregated /8 or /16 via longest-prefix-match at downstream routers
