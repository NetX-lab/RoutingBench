---
name: find-neighbors
description: List all directly connected neighbors of a device with interface details and status. Use to understand a device's connectivity.
---

# Find Neighbors

## Objective
List all non-server neighbors of a device with local/remote interface names, IP addresses, and operational status.

## Workflow

### Step 1: Get Topology Adjacency
Call `get_topology_adjacency(device)` to get all neighbors from the topology JSON.

### Step 2: Enrich with Interface Info
For each neighbor, call `get_interface_config(device, local_intf)` to add IP and shutdown status.

## Returns
```json
{"device": "edge-p0-e0", "neighbors": [
  {"neighbor": "agg-p0-a0", "local_intf": "GigabitEthernet1/0/3", "remote_intf": "GigabitEthernet1/0/1", "ip": "2.0.0.0 255.255.255.254", "shutdown": false},
  {"neighbor": "agg-p0-a1", "local_intf": "GigabitEthernet1/0/4", "remote_intf": "GigabitEthernet1/0/1", "ip": "2.0.1.0 255.255.255.254", "shutdown": false}
]}
```

## Guidelines
- Server neighbors are excluded (only router-to-router links)
- A shutdown interface means that neighbor is not reachable via that link
