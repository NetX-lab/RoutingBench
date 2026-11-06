"""Method 3: Agent Skills — LLM reads SKILL.md then calls tools.

Flow:
1. LLM selects a skill → runtime sends SKILL.md content
2. LLM calls tools per SKILL.md workflow → runtime executes scripts/
3. LLM reasons over results → selects next skill or answers
"""
import os, re, json, time, math
from agents.llm_client import call_llm, extract_json
from agents.shared_prompts import load_system_prompt, load_agent_md, format_query, format_change

MAX_STEPS = 100
SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")

# Import all tool scripts
from agents.agent_skills.scripts import search_config as _sc
from agents.agent_skills.scripts import read_config_block as _rcb
from agents.agent_skills.scripts import get_bgp_neighbors as _gbn
from agents.agent_skills.scripts import get_interface_config as _gic
from agents.agent_skills.scripts import get_topology_adjacency as _gta
from agents.agent_skills.scripts import get_layer_devices as _gld
from agents.agent_skills.scripts import get_topology_paths as _gtp
from agents.agent_skills.scripts import find_references as _fr
from agents.agent_skills.scripts import extract_match_set_clauses as _emsc

TOOL_REGISTRY = {
    "search_config": _sc.run,
    "read_config_block": _rcb.run,
    "get_bgp_neighbors": _gbn.run,
    "get_interface_config": _gic.run,
    "get_topology_adjacency": _gta.run,
    "get_layer_devices": _gld.run,
    "get_topology_paths": _gtp.run,
    "find_references": _fr.run,
    "extract_match_set_clauses": _emsc.run,
}


def _load_skill_md(skill_name):
    """Load a skill's SKILL.md content."""
    path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return f"[Skill '{skill_name}' not found]"


def _execute_tool(tool_name, target_dir, **kwargs):
    """Execute a tool script and return result."""
    fn = TOOL_REGISTRY.get(tool_name)
    if not fn:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return fn(target_dir, **kwargs)
    except Exception as e:
        return {"error": f"Tool {tool_name} failed: {e}"}


def _parse_actions(text):
    """Parse LLM output for actions: use_skill, tool calls, or answer."""
    parsed = extract_json(text)
    
    # Dict actions: use_skill or answer
    if isinstance(parsed, dict):
        if parsed.get("action") in ("use_skill", "answer"):
            return parsed
        if "before_path" in parsed and "after_path" in parsed:
            return {"action": "answer", **parsed}
    
    # List: tool calls [{"tool": ...}] or skill calls [{"skill": ...}]
    if isinstance(parsed, list) and parsed:
        if "tool" in parsed[0]:
            return {"action": "tool_calls", "calls": parsed}
        if "skill" in parsed[0]:
            return {"action": "tool_calls", "calls": parsed}
    
    # Try harder: find JSON arrays in text
    all_calls = []
    for match in re.finditer(r'\[\s*\{', text):
        start = match.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '[': depth += 1
            elif text[i] == ']': depth -= 1
            if depth == 0:
                try:
                    arr = json.loads(text[start:i+1])
                    if isinstance(arr, list):
                        all_calls.extend(arr)
                except:
                    pass
                break
    if all_calls:
        return {"action": "tool_calls", "calls": all_calls}
    
    # Try line-by-line: LLM may output multiple JSON objects on separate lines
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                obj = json.loads(line)
                if obj.get("action") in ("use_skill", "answer"):
                    return obj
                if "before_path" in obj and "after_path" in obj:
                    return {"action": "answer", **obj}
            except:
                pass
    
    # Check for answer in text
    if "before_path" in text:
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            try:
                obj = json.loads(text[brace_start:brace_end+1])
                if "before_path" in obj:
                    return {"action": "answer", **obj}
            except:
                pass
    
    return None


def run(instance, before_dir, model_name="gpt-5.4", topology="fattree"):
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
    
    # Build in-memory overlay for after-change configs (no disk I/O)
    from agents.agent_skills.scripts import set_overlay, clear_overlay
    after_overlay = {}  # device_name -> modified cfg content
    for d in change_diffs:
        cfg_path = os.path.join(before_dir, "configs", f"{d['device']}.cfg")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                lines = f.read().rstrip().split("\n")
            idx = len(lines)
            for i in range(len(lines)-1, -1, -1):
                if lines[i].strip() == "end": idx = i; break
            lines = lines[:idx] + ["!"] + d["add_lines"] + ["!"] + lines[idx:]
            after_overlay[d['device']] = "\n".join(lines) + "\n"

    agent_md = load_agent_md("agent_skills")
    system_prompt = load_system_prompt(topology) + "\n\n" + agent_md

    _rules_dir = os.path.join(os.path.dirname(__file__), "rules")
    for _rules_file in ("dont_rules_common.md", f"dont_rules_{topology}.md"):
        _rules_path = os.path.join(_rules_dir, _rules_file)
        if os.path.exists(_rules_path):
            with open(_rules_path) as f:
                system_prompt += "\n\n" + f.read()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"""=== QUERY ===
{query}

=== CONFIGURATION CHANGE ===
{change_text}

Select a skill to begin analysis. Output: {{"action": "use_skill", "skill": "skill-name"}}
Or call tools directly if you know what to do."""},
    ]

    # Determine minimum inspected devices based on topology scale.
    total_input = 0; total_output = 0; total_llm_time = 0; total_tool_time = 0
    k_val = instance.get("k") or 4

    import re as _re
    m = _re.search(r'fattreek(\d+)', before_dir)
    if m:
        k_val = int(m.group(1))
    else:
        m = _re.search(r'crossdck(\d+)', before_dir)
        if m:
            k_val = int(m.group(1))
    min_inspected = max(3, math.ceil(math.sqrt(k_val)))

    skill_calls = 0; tool_calls_count = 0
    inspected_devices = set()
    log_steps = []
    answer = None

    for step in range(MAX_STEPS):
        result = call_llm(messages, model_name=model_name)
        total_input += result.input_tokens
        total_output += result.output_tokens
        total_llm_time += result.elapsed_s

        log_entry = {"step": step+1, "raw": result.text[:3000],
                      "input_tokens": result.input_tokens, "output_tokens": result.output_tokens}

        action = _parse_actions(result.text)
        
        if not action:
            log_entry["action"] = "unparsed"
            log_steps.append(log_entry)
            messages.append({"role": "assistant", "content": result.text})
            if tool_calls_count > 0:
                messages.append({"role": "user", "content": "Please produce your final answer as JSON with before_path, after_path, and decisive_evidence."})
            else:
                messages.append({"role": "user", "content": "Your output could not be parsed. You MUST output valid JSON. Either select a skill:\n{\"action\": \"use_skill\", \"skill\": \"find-candidate-paths\"}\nOr call tools as a JSON array:\n[{\"tool\": \"tool_name\", \"args\": {...}}]\nDo NOT produce an answer without first gathering evidence via tools."})
            continue
        
        if action["action"] == "answer" and tool_calls_count > 0:
            # Enforce minimum inspected devices based on topology scale
            if len(inspected_devices) < min_inspected:
                messages.append({"role": "assistant", "content": result.text})
                messages.append({"role": "user", "content": 
                    f"You have only inspected {len(inspected_devices)} devices ({sorted(inspected_devices)}). "
                    f"For this topology scale you must examine at least {min_inspected} devices before answering. "
                    f"Check more agg/core routers to verify your path. Use find-neighbors or get_bgp_neighbors on additional devices."})
                log_entry["action"] = "insufficient_inspection"
                log_steps.append(log_entry)
                continue
            answer = {k: action[k] for k in ["before_path", "after_path", "decisive_evidence"] if k in action}
            log_entry["action"] = "answer"
            log_steps.append(log_entry)
            break
        
        if action["action"] == "answer" and tool_calls_count == 0:
            # Force skill/tool usage
            messages.append({"role": "assistant", "content": result.text})
            messages.append({"role": "user", "content": "You must gather evidence first. Select a skill: {\"action\": \"use_skill\", \"skill\": \"find-candidate-paths\"}"})
            log_entry["action"] = "forced"
            log_steps.append(log_entry)
            continue
        
        if action["action"] == "use_skill":
            skill_name = action.get("skill", "")
            skill_md = _load_skill_md(skill_name)
            skill_calls += 1
            messages.append({"role": "assistant", "content": result.text})
            messages.append({"role": "user", "content": f"## Skill: {skill_name}\n\n{skill_md}\n\nNow call the tools described in this skill's workflow. Output a JSON array of tool calls."})
            log_entry["action"] = "use_skill"
            log_entry["skill"] = skill_name
            log_steps.append(log_entry)
            continue
        
        if action["action"] == "tool_calls":
            calls = action["calls"]
            tool_results = []
            _tool_t0 = time.time()
            for call in calls:
                tool_name = call.get("tool") or call.get("skill", "")
                args = call.get("args", {})
                if not isinstance(args, dict):
                    args = {}
                phase = args.pop("phase", "before")
                
                # Set/clear overlay for after-phase reads
                if phase == "after":
                    set_overlay(after_overlay)
                else:
                    clear_overlay()
                
                for v in args.values():
                    if isinstance(v, str) and any(x in v for x in ["-p", "core", "agg", "edge", "dc"]):
                        inspected_devices.add(v)
                
                tr = _execute_tool(tool_name, before_dir, **args)
                clear_overlay()  # always clear after each tool call
                tool_calls_count += 1
                tool_results.append({"tool": tool_name, "args": {**args, "phase": phase}, "result": tr})
            
            total_tool_time += time.time() - _tool_t0
            log_entry["action"] = "tool_calls"
            log_entry["tools"] = [{"tool": t["tool"], "args": t["args"]} for t in tool_results]
            log_steps.append(log_entry)
            
            result_text = "Tool results:\n"
            for i, tr in enumerate(tool_results):
                result_text += f"\n[{i+1}] {tr['tool']}({json.dumps(tr['args'])}) ->\n"
                result_text += json.dumps(tr["result"], indent=2)[:2000] + "\n"
            
            messages.append({"role": "assistant", "content": result.text})
            messages.append({"role": "user", "content": result_text + 
                "\n\nContinue: call more tools, select another skill, or produce your final answer."})
            continue

    # Fallback: if answer is still None after loop, force one final answer extraction
    if answer is None and tool_calls_count > 0:
        messages.append({"role": "user", "content":
            "You have run out of rounds. You MUST produce your final answer NOW as a JSON object with "
            "\"before_path\" (list of router hostnames) and \"after_path\" (list of router hostnames). "
            "Do NOT call any more tools. Output ONLY the JSON answer."})
        for _retry in range(3):
            result = call_llm(messages, model_name=model_name)
            total_input += result.input_tokens
            total_output += result.output_tokens
            total_llm_time += result.elapsed_s
            action = _parse_actions(result.text)
            if action and action.get("action") == "answer":
                answer = {k: action[k] for k in ["before_path", "after_path", "decisive_evidence"] if k in action}
                break
            # Try even more aggressive extraction from raw text
            parsed = extract_json(result.text)
            if isinstance(parsed, dict) and "before_path" in parsed:
                answer = {k: parsed[k] for k in ["before_path", "after_path", "decisive_evidence"] if k in parsed}
                break
            messages.append({"role": "assistant", "content": result.text})
            messages.append({"role": "user", "content":
                "Invalid format. Output ONLY a JSON object like: "
                "{\"before_path\": [\"router1\", \"router2\", ...], \"after_path\": [\"router1\", \"router2\", ...], \"decisive_evidence\": \"...\"}"})

    clear_overlay()  # ensure cleanup

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
            "rounds": len(log_steps),
            "skill_calls": skill_calls,
            "tool_calls": tool_calls_count,
            "inspected_routers": len(inspected_devices),
        },
        "log": {
            "method": "agent_skills",
            "model": model_name,
            "steps": log_steps,
            "inspected_devices": sorted(inspected_devices),
        },
    }
