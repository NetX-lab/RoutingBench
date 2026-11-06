---
name: check-interface-reachability
description: Check whether a specific interface on a device is operationally reachable (up/down, IP assigned). Use when verifying physical connectivity along a path.
---

# Check Interface Reachability

## Objective
Determine if a specific interface on a device is administratively up, has an IP address, and is connected to a peer.

## Workflow

### Step 1: Get Interface Config
Call `get_interface_config(device, interface_name)` to check admin status, IP, and description.

## Returns
```json
{"device": "edge-p0-e0", "interface": "GigabitEthernet1/0/3", "ip": "2.0.0.0 255.255.255.254", "shutdown": false, "description": "To agg-p0-a0"}
```

## Guidelines
- `shutdown` = true means the interface is administratively down, no traffic flows
- An interface without IP cannot participate in L3 routing
- Check both ends of a link for full reachability verification
