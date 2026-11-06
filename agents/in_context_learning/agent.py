"""Method 1: Full-Context — all configs in a single prompt."""
import os, json
from agents.llm_client import call_llm, extract_json
from agents.shared_prompts import load_system_prompt, load_agent_md, format_query, format_change


def build_topology_text(before_dir):
    """Build topology description from layer1 JSON."""
    topo_file = os.path.join(before_dir, "example_layer1_topology.json")
    if not os.path.exists(topo_file):
        return "[Topology file not found]"
    with open(topo_file) as f:
        topo = json.load(f)
    lines = ["Network Topology (Layer 1 Links):"]
    for edge in topo.get("edges", []):
        n1 = edge["node1"]; n2 = edge["node2"]
        # Skip server links for brevity
        if "server" in n1["hostname"] or "server" in n2["hostname"]:
            continue
        lines.append(f"  {n1['hostname']}({n1['interfaceName']}) <-> {n2['hostname']}({n2['interfaceName']})")
    return "\n".join(lines)


def build_all_configs_text(before_dir):
    """Concatenate all .cfg files."""
    cfg_dir = os.path.join(before_dir, "configs")
    parts = []
    for fn in sorted(os.listdir(cfg_dir)):
        if not fn.endswith(".cfg"):
            continue
        hostname = fn[:-4]
        if "server" in hostname:
            continue
        with open(os.path.join(cfg_dir, fn)) as f:
            content = f.read()
        parts.append(f"===== Configuration: {hostname} =====\n{content}\n===== End Configuration: {hostname} =====")
    return "\n\n".join(parts)


def run(instance, before_dir, model_name="gpt-4.1", topology="fattree"):
    """Run full-context analysis.
    
    Returns dict with: answer, metrics, log.
    """
    # Build prompt
    topo_text = build_topology_text(before_dir)
    all_configs = build_all_configs_text(before_dir)
    query = format_query(instance["src_edge"], instance["dst_edge"], instance["dst_prefix"],
                         src_dc=instance.get("src_dc"), dst_dc=instance.get("dst_dc"))
    
    ct = instance.get("change_type") or instance.get("scenario")
    change_file = os.path.join(os.path.dirname(before_dir),
                                ct,
                                f"pair{instance['pair_id']}_change{instance['change_id']}",
                                "change.json")
    with open(change_file) as f:
        change_diffs = json.load(f)
    change_text = format_change(change_diffs)

    system_prompt = load_system_prompt(topology) + "\n\n" + load_agent_md("in_context_learning")

    user_prompt = f"""=== TOPOLOGY ===
{topo_text}

=== ALL DEVICE CONFIGURATIONS ===
{all_configs}

=== QUERY ===
{query}

=== CONFIGURATION CHANGE ===
{change_text}

Analyze the routing path before and after this change. Produce your JSON answer."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = call_llm(messages, model_name=model_name)
    answer = extract_json(result.text)

    # Count inspected routers (all of them)
    cfg_dir = os.path.join(before_dir, "configs")
    n_routers = len([f for f in os.listdir(cfg_dir) if f.endswith(".cfg") and "server" not in f])

    return {
        "answer": answer,
        "raw_text": result.text,
        "metrics": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
            "llm_time_s": round(result.elapsed_s, 2),
            "tool_time_s": 0,
            "runtime_s": round(result.elapsed_s, 2),
            "rounds": 1,
            "skill_calls": 0,
            "inspected_routers": n_routers,
        },
        "log": {
            "method": "in_context_learning",
            "model": model_name,
            "prompt_length": len(user_prompt),
            "num_configs_in_prompt": n_routers,
        },
    }
