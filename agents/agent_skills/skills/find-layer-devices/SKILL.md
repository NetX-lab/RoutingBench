---
name: find-layer-devices
description: List all devices in a given topology layer (edge, agg, core) optionally scoped to a pod. Use to enumerate routers at a specific tier.
---

# Find Layer Devices

## Objective
Return all device names in a specified topology layer, optionally filtered by pod scope.

## Workflow

### Step 1: Query Layer
Call `get_layer_devices(layer, scope)` where layer is "edge", "agg", or "core", and scope is an optional pod number.

## Returns
```json
{"layer": "agg", "scope": 0, "devices": ["agg-p0-a0", "agg-p0-a1"]}
```

## Guidelines
- Layers: "edge" (ToR switches), "agg" (aggregation), "core" (spine)
- Scope by pod number to get devices in a specific pod
- Use without scope to get all devices in a layer across all pods
