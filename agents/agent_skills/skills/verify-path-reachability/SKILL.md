---
name: verify-path-reachability
description: Verify whether all links along a candidate path are physically operational. Use after identifying a candidate path to confirm it's actually usable.
---

# Verify Path Reachability

## Objective
Check every hop in a candidate path to verify all intermediate links are up. Reports the first broken link if any.

## Workflow

### Step 1: Iterate Hops
For each consecutive pair of routers in the path, call `verify_link(device1, device2)`.

### Step 2: Report
If all links are up, report reachable. If any link is down, report the broken segment.

## Returns
Reachable: `{"path": [...], "reachable": true}`
Broken: `{"path": [...], "reachable": false, "broken_at": ["agg-p0-a0", "core-g0-c0"], "details": {...}}`

## Guidelines
- A path is only usable if ALL links along it are up
- Even one shutdown interface breaks the entire path
- Always verify the after-change path to confirm it's reachable
