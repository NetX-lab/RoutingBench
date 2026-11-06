---
name: find-static-route
description: Check whether a static route for a specific prefix exists on a device. Use when analyzing if static routes (AD=1) override BGP paths.
---

# Find Static Route

## Objective
Check if a static route for the given prefix exists. Static routes have AD=1, which overrides BGP (AD=20).

## Workflow

### Step 1: Search Config
Call `search_config(device, "ip route <prefix_network>")` to find static route entries.

### Step 2: Parse Entry
If found, extract: network, mask, next-hop IP, and administrative distance.

### Step 3: Verify Next-Hop Interface
Call `get_interface_config(device, <outgoing_interface>)` to verify the interface toward the next-hop is up.

## Returns
```json
{"device": "edge-p0-e0", "prefix": "1.1.0.0/24", "static_routes": [{"network": "1.1.0.0", "mask": "255.255.255.0", "next_hop": "2.0.1.1"}]}
```
Or: `{"static_route": "not configured"}`

## Guidelines
- Static route AD=1 beats BGP AD=20 (if prefix matches)
- Check if next-hop is reachable before concluding the static route is active
- A static to Null0 means traffic is blackholed (used for BGP network statements)
