## DON'T Rules from Experiences

### DON'T assume the core index matches the agg index
When traffic enters a core group (e.g., `core-g3-c?`), the router-ID tiebreak selects the core with the **lowest RID** within that group. For example, if the RID for `core-g{G}-c{C}` is `10.255.{G}.{C}`, then `core-g3-c0` (RID 10.255.3.0) always beats `core-g3-c1` (10.255.3.1), `core-g3-c2`, `core-g3-c3`, etc. **The default winner within ANY core group is always c0** in this situation, not the core whose index matches the agg index. Use `search_config` with `regex=bgp router-id` to verify if unsure.

### DON'T let your JSON answer contradict your reasoning
Before emitting your final JSON answer, re-read your own `decisive_evidence` text and double-check that the device names in `before_path` and `after_path` arrays exactly match the conclusion you reached. A common error is reasoning correctly (e.g., "core-g3-c0 wins by lowest RID") but then accidentally writing a different core index in the JSON (e.g., `core-g3-c3`). Always verify consistency between your reasoning and the JSON output.

### DON'T trust candidate-path BFS results for interface shutdown changes
The `find-candidate-paths` skill uses topology-level BFS that does **not** reflect interface shutdown state — it always shows all physically wired links, whether up or down. When the configuration change involves `shutdown` on an interface, you **must** use `check-interface-reachability` to determine which link is down, then **manually exclude** any path that traverses the downed link. Do not conclude "path is unchanged" just because BFS still lists it.

### DON'T ignore the static route next-hop when it determines the forwarding device
When a change adds a static route like `ip route <prefix> <mask> <next-hop-IP>`, the next-hop IP **directly determines** which neighbor device receives the traffic — the router-ID tiebreak is irrelevant because the static route (AD=1) overrides BGP (AD=20). You must resolve the next-hop IP to an actual device to find which specific router the traffic goes to. Do NOT fall back to "lowest RID in the group" when a static route is present.

### DON'T use wrong argument names when calling tools
Each tool has a specific function signature. Common mistakes:
- `get_interface_config` expects `intf` (not `interface_name` or `interface`)
- `get_topology_paths` expects `src` and `dst`
- `search_config` expects `device` and `regex`

If a tool returns an error about missing arguments, check the argument name and retry. 

### DON'T confuse agg index, core group, and dst_agg index
The fat-tree connectivity rule is strict: `agg-pX-a{A}` connects ONLY to `core-g{A}-c*`, and `core-g{A}-c*` connects ONLY to `agg-pY-a{A}` on the destination side. Therefore **src_agg index == core group == dst_agg index**, always.