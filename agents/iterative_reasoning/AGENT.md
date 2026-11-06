# Multi-Round Agent

You receive the topology and query but **no device configurations** initially.

## Interaction Loop

You operate in a **multi-round conversation loop** with the system:

1. **Request configs** — select which devices to inspect:
   ```json
   {"action": "request_configs", "devices": ["device1", "device2"]}
   ```
   The system returns the full .cfg file for each requested device (both before and after change states if the device is affected).

2. **Analyze** — read the returned configs, extract routing evidence (LP, static routes, MED, interface status, etc.).

3. **Repeat or answer** — if you need more evidence, go back to step 1 and request more devices. If you have enough, produce your final answer:
   ```json
   {"action": "answer", "before_path": [...], "after_path": [...], "decisive_evidence": "..."}
   ```

## Strategy

- Start with the **source edge router** and the **device where the change is applied**
- Follow the path **hop-by-hop**: after examining the source edge, request the next-hop agg, then the core, etc.
- Request only the devices you need — fewer requests = faster and cheaper
- You see complete raw .cfg files for each device, so look for `route-map`, `set local-preference`, `ip route`, `shutdown`, `bgp router-id`, etc.
