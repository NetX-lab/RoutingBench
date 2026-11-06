---
name: verify-link
description: Verify whether a direct physical link between two devices is operational (both interfaces up). Use to check if a specific link is usable for routing.
---

# Verify Link

## Objective
Check if a direct link between two devices exists and both ends are administratively up.

## Workflow

### Step 1: Check Topology
Call `get_topology_adjacency(device1)` to confirm the link exists and get interface names.

### Step 2: Check Both Interfaces
Call `get_interface_config` on both devices to check for shutdown status.

## Returns
```json
{"device1": "edge-p0-e0", "device2": "agg-p0-a0", "exists": true,
 "intf1": "GigabitEthernet1/0/3", "intf2": "GigabitEthernet1/0/1",
 "intf1_shutdown": false, "intf2_shutdown": false, "both_up": true}
```

## Guidelines
- `exists: false` means no direct link in topology
- `both_up: false` means at least one interface is shutdown — traffic cannot flow
- Interface shutdown is the mechanism used by the "interface_shutdown" change type
