---
name: verify-bgp-session
description: Verify that a BGP session between two devices is properly configured with mutual peering. Use to confirm BGP connectivity along a path.
---

# Verify BGP Session

## Objective
Verify that both devices have each other configured as BGP neighbors with correct remote-AS.

## Workflow

### Step 1: Check Device Side
Call `get_bgp_neighbors(device)` and check if the neighbor appears with correct remote-AS and route-maps.

### Step 2: Check Neighbor Side
Call `get_bgp_neighbors(neighbor)` and verify the reverse direction.

### Step 3: Check Interfaces
Verify connecting interfaces are up on both sides.

## Returns
```json
{"device": "edge-p0-e0", "neighbor": "agg-p0-a0", "mutual": true,
 "device_bgp": {"asn": 100000, "neighbors": [...]},
 "neighbor_bgp": {"asn": 20000, "neighbors": [...]}}
```

## Guidelines
- BGP session requires mutual configuration (both sides must have each other as neighbor)
- Mismatched remote-AS = session won't establish
- A missing route-map doesn't prevent session, just means no policy applied
