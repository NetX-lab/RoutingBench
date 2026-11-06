"""Method 2: Multi-Round — iteratively request device configs."""
import os, json, time
from agents.llm_client import call_llm, extract_json, LLMResult
from agents.shared_prompts import load_system_prompt, load_agent_md, format_query, format_change
from agents.iterative_reasoning.scripts.tools import get_topology, get_device_config

MAX_ROUNDS = 10


def run(instance, before_dir, model_name="gpt-5.4", topology="fattree"):
    """Run multi-round analysis."""
    topo_text = get_topology(before_dir)
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

    agent_md = load_agent_md("iterative_reasoning")
    system_prompt = load_system_prompt(topology) + "\n\n" + agent_md

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"""=== TOPOLOGY ===
{topo_text}

=== QUERY ===
{query}

=== CONFIGURATION CHANGE ===
{change_text}

Start by requesting the configurations you need."""},
    ]

    total_input = 0; total_output = 0; total_llm_time = 0; total_tool_time = 0
    inspected = set()
    tool_calls_count = 0
    rounds = 0
    answer = None
    log_rounds = []

    for rnd in range(MAX_ROUNDS):
        rounds += 1
        result = call_llm(messages, model_name=model_name)
        total_input += result.input_tokens
        total_output += result.output_tokens
        total_llm_time += result.elapsed_s

        parsed = extract_json(result.text)
        log_entry = {"round": rounds, "raw_response": result.text[:2000],
                      "input_tokens": result.input_tokens, "output_tokens": result.output_tokens}

        if parsed and parsed.get("action") == "answer":
            answer = {k: parsed[k] for k in ["before_path", "after_path", "decisive_evidence"] if k in parsed}
            log_entry["action"] = "answer"
            log_rounds.append(log_entry)
            break
        elif parsed and parsed.get("action") == "request_configs":
            devices = parsed.get("devices", [])
            log_entry["action"] = "request_configs"
            log_entry["requested_devices"] = devices
            log_rounds.append(log_entry)

            # Fetch configs
            _tool_t0 = time.time()
            config_parts = []
            for dev in devices:
                inspected.add(dev)
                tool_calls_count += 1
                # Return both before and after (if change applies to this device)
                before_cfg = get_device_config(before_dir, dev)
                after_cfg = get_device_config(before_dir, dev, change_diffs, phase="after")
                config_parts.append(f"===== Configuration: {dev} (before change) =====\n{before_cfg}\n===== End =====")
                if before_cfg != after_cfg:
                    config_parts.append(f"===== Configuration: {dev} (after change) =====\n{after_cfg}\n===== End =====")
            total_tool_time += time.time() - _tool_t0
            messages.append({"role": "assistant", "content": result.text})
            messages.append({"role": "user", "content": "\n\n".join(config_parts) + "\n\nContinue analyzing. Request more configs or produce your final answer."})
        else:
            # Couldn't parse — ask LLM to retry with valid JSON
            log_entry["action"] = "unparsed"
            log_rounds.append(log_entry)
            if "before_path" in result.text:
                answer = extract_json(result.text)
                if answer:
                    break
            # Retry: ask for valid single JSON
            messages.append({"role": "assistant", "content": result.text})
            messages.append({"role": "user", "content": 
                "Your response was not valid JSON. Please output a SINGLE JSON object:\n"
                '{"action": "request_configs", "devices": ["device1", ...]}\n'
                "OR\n"
                '{"action": "answer", "before_path": [...], "after_path": [...], "decisive_evidence": "..."}'})
            continue

    # Force answer on last round if needed
    if answer is None and rounds >= MAX_ROUNDS:
        messages.append({"role": "assistant", "content": result.text})
        messages.append({"role": "user", "content": "Round limit reached. Produce your final JSON answer NOW."})
        result = call_llm(messages, model_name=model_name)
        total_input += result.input_tokens
        total_output += result.output_tokens
        total_llm_time += result.elapsed_s
        answer = extract_json(result.text)
        rounds += 1

    return {
        "answer": answer,
        "raw_text": result.text if answer is None else json.dumps(answer),
        "metrics": {
            "input_tokens": total_input,
            "output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "llm_time_s": round(total_llm_time, 2),
            "tool_time_s": round(total_tool_time, 2),
            "runtime_s": round(total_llm_time + total_tool_time, 2),
            "rounds": rounds,
            "skill_calls": 0,
            "tool_calls": tool_calls_count,
            "inspected_routers": len(inspected),
        },
        "log": {
            "method": "iterative_reasoning",
            "model": model_name,
            "rounds_detail": log_rounds,
            "inspected_devices": sorted(inspected),
        },
    }
