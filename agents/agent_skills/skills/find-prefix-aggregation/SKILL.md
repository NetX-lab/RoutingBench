---
name: find-prefix-aggregation
description: Check whether a device aggregates a prefix via aggregate-address. Use when analyzing if prefix summarization affects route advertisement or path selection.
---

# Find Prefix Aggregation

## Objective
Check if the device has an `aggregate-address` entry that covers the target prefix. Aggregation with `summary-only` suppresses more-specific prefixes from being advertised.

## Workflow

### Step 1: Search Config
Call `search_config(device, "aggregate-address")` to find all aggregate entries.

### Step 2: Analyze
Check if any aggregate covers the target prefix. Note whether `summary-only` is set (suppresses component prefixes) and whether `as-set` is set (includes AS-path info).

## Returns
```json
{"device": "agg-p0-a0", "prefix": "1.0.0.0/16", "aggregates": [{"line": "aggregate-address 1.0.0.0 255.255.0.0 as-set summary-only", "summary_only": true}]}
```

## Guidelines
- `summary-only` suppresses more-specific prefixes from being advertised to BGP peers
- This means /24 routes are NOT visible at upper layers if the agg has summary-only for /16
- `as-set` preserves AS-path information from contributing routes
