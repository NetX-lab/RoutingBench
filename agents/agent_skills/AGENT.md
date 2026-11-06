# Agent Skills

You have no direct access to topology or device configurations. You analyze the network through **skills** — each skill is a documented workflow in the `skills/` directory.

## Interaction Loop

You operate in a **plan-invoke-reason loop** with a skill runtime:

1. **Plan** — decide which skill to use next based on what you know so far
2. **Invoke** — select a skill by name → the system loads its `SKILL.md` and shows you the workflow
3. **Execute** — follow the SKILL.md instructions by calling **tools** (deterministic scripts). The system executes each tool and returns results.
4. **Reason** — analyze tool results, update your understanding of the routing path
5. **Repeat or answer** — if you need more evidence, go back to step 1 and select another skill. If you have enough, produce your final answer.

This loop continues until you produce an answer. There is no fixed round limit.

## Selecting a Skill

Output:
```json
{"action": "use_skill", "skill": "skill-name"}
```

The system will show you that skill's SKILL.md with its objective, workflow steps, and tool call examples.

## Available Skills (in `skills/` directory)

### Config Extraction
| Skill | What it determines |
|-------|-------------------|
| `find-lp-for-prefix` | BGP local-preference for a prefix on a device |
| `find-med-for-prefix` | MED value for a prefix on a device |
| `find-static-route` | Static route existence for a prefix |
| `find-bgp-network` | BGP network statement on a device |
| `find-prefix-aggregation` | Aggregate-address on a device |
| `find-route-map-policy` | Full routing policy between device and neighbor |
| `check-interface-reachability` | Interface up/down status |

### Topology
| Skill | What it determines |
|-------|-------------------|
| `find-neighbors` | All neighbors with interface details |
| `find-layer-devices` | Devices in a topology layer |
| `find-candidate-paths` | Plausible routing paths between two edges |

### Verification (config)
| Skill | What it determines |
|-------|-------------------|
| `determine-route-selection` | Which route wins on a device for a prefix |
| `verify-bgp-session` | BGP session validity between two devices |

### Verification (topology)
| Skill | What it determines |
|-------|-------------------|
| `verify-link` | Physical link operational status |
| `verify-path-reachability` | All links in a path are up |

## Analysis Requirements

Before producing your answer, you must gather sufficient evidence:

1. **Discover the topology**: Use `find-candidate-paths` to see all possible routes.
2. **Gather evidence from sufficient routers**: Collect routing evidence from as many routers along and around the path as possible. Never assume a fixed agg (e.g., agg0) wins — examine the actual LP, static routes, and MED on multiple candidates. For a fat-tree with parameter k, you must inspect **at least ⌈√k⌉ distinct routers** (e.g., k=4 → ≥2, k=16 → ≥4, k=50 → ≥8). Include the source edge, multiple aggs in the source pod, and relevant core/dst-agg routers.
3. **Check the changed device**: Examine the change's effect using the appropriate skill (LP, static, MED, etc.) in both `phase: "before"` and `phase: "after"`.
4. **Verify the after-path**: For shutdown changes, verify link status. For static/bgp_network/prefix_agg changes, resolve next-hop to determine the exact core.

## Producing Your Answer

When you have enough evidence:
```json
{"action": "answer", "before_path": [...], "after_path": [...], "decisive_evidence": "..."}
```


