#!/usr/bin/env python3
"""Unified evaluation framework for 3 agent methods.

Reads config from config.yaml (or CLI overrides).
Saves detailed logs + metrics to logs/ directory.

Usage:
    python -m agents.framework
    python -m agents.framework --method agent_skills --k 8 --limit 6
"""
import os, sys, json, time, argparse, traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

METRICS_FIELDS = ["accuracy", "token_consumption", "runtime_s",
                  "rounds", "skill_calls", "inspected_routers"]


def load_config():
    """Load the top-level config.yaml's `evaluation` section, allow CLI overrides."""
    from agents.config_loader import load_config as _load_top, repo_root
    top = _load_top()
    cfg = (top.get("evaluation") or {}) if isinstance(top, dict) else {}

    parser = argparse.ArgumentParser()
    parser.add_argument("--topology", default=cfg.get("topology", "fattree"),
                        choices=["fattree", "crossdc", "compound"])
    parser.add_argument("--method", default=cfg.get("method", "all"))
    parser.add_argument("--k", type=int, default=cfg.get("k", 4))
    parser.add_argument("--model", default=cfg.get("model", "default"))
    parser.add_argument("--limit", type=int, default=cfg.get("limit"))
    parser.add_argument("--change-type", default=cfg.get("change_type"))
    parser.add_argument("--output-dir", default=cfg.get("output_dir", "logs"))
    args = parser.parse_args()
    # Run from the repository root so relative dataset paths resolve consistently.
    os.chdir(repo_root())
    return args


# Map topology name → data directory prefix
_TOPO_DIR = {
    "fattree": "data/fattree/fattreek",
    "crossdc": "data/crossdc/crossdck",
    "compound": "data/compound/compoundk",
}

def load_instances(topology, k):
    prefix = _TOPO_DIR.get(topology, _TOPO_DIR["fattree"])
    base = f"{prefix}{str(k).zfill(3)}"
    # Compound uses compound_ground_truth.json; others use ground_truth.json
    if topology == "compound":
        gt_file = os.path.join(base, "compound_ground_truth.json")
    else:
        gt_file = os.path.join(base, "ground_truth.json")
    if not os.path.exists(gt_file):
        print(f"[ERROR] Ground truth not found: {gt_file}")
        return [], ""
    with open(gt_file) as f:
        instances = json.load(f)
    # Compound uses 'scenario' key; normalize to 'change_type' for framework
    if topology == "compound":
        for inst in instances:
            if "scenario" in inst and "change_type" not in inst:
                inst["change_type"] = inst["scenario"]
    before_dir = os.path.join(base, "before")
    return instances, before_dir


def evaluate_answer(answer, instance):
    if not answer:
        return {"before_correct": False, "after_correct": False, "both_correct": False}
    gt_before = instance["before_path"]["node_list"]
    gt_after = instance["after_path"]["node_list"]
    pred_before = answer.get("before_path", [])
    pred_after = answer.get("after_path", [])
    def norm(path):
        return [n for n in path if "server" not in n]
    b_ok = norm(pred_before) == norm(gt_before)
    a_ok = norm(pred_after) == norm(gt_after)
    return {"before_correct": b_ok, "after_correct": a_ok, "both_correct": b_ok and a_ok}


def run_method(method_name, instance, before_dir, model_name, topology="fattree"):
    if method_name == "in_context_learning":
        from agents.in_context_learning.agent import run
    elif method_name == "iterative_reasoning":
        from agents.iterative_reasoning.agent import run
    elif method_name == "agent_skills":
        from agents.agent_skills.agent import run
    else:
        raise ValueError(f"Unknown method: {method_name}")
    return run(instance, before_dir, model_name=model_name, topology=topology)


def main():
    args = load_config()
    
    # Setup output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"{args.topology}_{args.method}_k{args.k}_{args.model}_{timestamp}"
    log_dir = os.path.join(args.output_dir, run_id)
    os.makedirs(log_dir, exist_ok=True)
    
    # Save config
    run_config = {"topology": args.topology, "method": args.method, "k": args.k,
                  "model": args.model, "limit": args.limit,
                  "change_type": args.change_type, "timestamp": timestamp}
    with open(os.path.join(log_dir, "config.json"), "w") as f:
        json.dump(run_config, f, indent=2)
    
    instances, before_dir = load_instances(args.topology, args.k)
    if not instances:
        return
    if args.change_type:
        instances = [i for i in instances if i["change_type"] == args.change_type]
    if args.limit:
        instances = instances[:args.limit]

    methods = [args.method] if args.method != "all" else ["in_context_learning", "iterative_reasoning", "agent_skills"]
    
    all_results = []
    summary = {}
    
    for method in methods:
        print(f"\n{'='*60}")
        print(f"  Method: {method}, topology={args.topology}, k={args.k}, model={args.model}")
        print(f"  Instances: {len(instances)}")
        print(f"  Logs: {log_dir}")
        print(f"{'='*60}")
        
        method_results = []
        correct = 0; total = 0
        total_tokens = 0; total_time = 0
        total_rounds = 0; total_skills = 0; total_inspected = 0
        
        for idx, inst in enumerate(instances):
            pid, cid, ct = inst["pair_id"], inst["change_id"], inst["change_type"]
            print(f"\n  [{idx+1}/{len(instances)}] {ct} pair{pid}/change{cid}...", end=" ", flush=True)
            
            try:
                t0 = time.time()
                result = run_method(method, inst, before_dir, args.model, topology=args.topology)
                wall_time = time.time() - t0
                
                eval_result = evaluate_answer(result.get("answer"), inst)
                metrics = result.get("metrics", {})
                
                entry = {
                    "instance": {"pair_id": pid, "change_id": cid, "change_type": ct,
                                 "src_edge": inst["src_edge"], "dst_edge": inst["dst_edge"],
                                 "dst_prefix": inst["dst_prefix"]},
                    "method": method,
                    "model": args.model,
                    "k": args.k,
                    "answer": result.get("answer"),
                    "ground_truth": {
                        "before_path": inst["before_path"]["node_list"],
                        "after_path": inst["after_path"]["node_list"],
                    },
                    "evaluation": eval_result,
                    "metrics": {
                        "accuracy": 1 if eval_result["both_correct"] else 0,
                        "token_consumption": metrics.get("total_tokens", 0),
                        "input_tokens": metrics.get("input_tokens", 0),
                        "output_tokens": metrics.get("output_tokens", 0),
                        "runtime_s": round(wall_time, 2),
                        "rounds": metrics.get("rounds", 1),
                        "skill_calls": metrics.get("skill_calls", 0),
                        "inspected_routers": metrics.get("inspected_routers", 0),
                    },
                    "log": result.get("log", {}),
                    "raw_text": result.get("raw_text", "")[:5000],
                }
                
                method_results.append(entry)
                all_results.append(entry)
                
                # Accumulate
                total += 1
                if eval_result["both_correct"]: correct += 1
                total_tokens += metrics.get("total_tokens", 0)
                total_time += wall_time
                total_rounds += metrics.get("rounds", 1)
                total_skills += metrics.get("skill_calls", 0)
                total_inspected += metrics.get("inspected_routers", 0)
                
                # Print status
                status = "✓" if eval_result["both_correct"] else "✗"
                tok = metrics.get("total_tokens", 0)
                rnd = metrics.get("rounds", 1)
                sk = metrics.get("skill_calls", 0)
                insp = metrics.get("inspected_routers", 0)
                print(f"{status} tokens={tok} time={wall_time:.1f}s rounds={rnd} skills={sk} inspected={insp}")
                
                if not eval_result["both_correct"]:
                    gt_b = inst["before_path"]["node_list"]
                    gt_a = inst["after_path"]["node_list"]
                    pred = result.get("answer") or {}
                    if not eval_result["before_correct"]:
                        print(f"    Before GT:   {gt_b}")
                        print(f"    Before Pred: {pred.get('before_path', 'N/A') if pred else 'N/A'}")
                    if not eval_result["after_correct"]:
                        print(f"    After GT:    {gt_a}")
                        print(f"    After Pred:  {pred.get('after_path', 'N/A') if pred else 'N/A'}")

                # Save individual instance log
                instance_log = os.path.join(log_dir, f"{method}_{ct}_p{pid}_c{cid}.json")
                with open(instance_log, "w") as f:
                    json.dump(entry, f, indent=2)
                
            except Exception as e:
                print(f"ERROR: {e}")
                traceback.print_exc()
                all_results.append({
                    "instance": {"pair_id": pid, "change_id": cid, "change_type": ct},
                    "method": method, "model": args.model, "k": args.k,
                    "error": str(e),
                    "metrics": {"accuracy": 0, "token_consumption": 0, "runtime_s": 0,
                                "rounds": 0, "skill_calls": 0, "inspected_routers": 0},
                })
                total += 1
        
        # Method summary
        n = max(total, 1)
        method_summary = {
            "method": method,
            "model": args.model,
            "k": args.k,
            "n_instances": total,
            "accuracy": round(correct / n * 100, 1),
            "accuracy_raw": f"{correct}/{total}",
            "avg_token_consumption": round(total_tokens / n),
            "avg_runtime_s": round(total_time / n, 1),
            "avg_rounds": round(total_rounds / n, 1),
            "avg_skill_calls": round(total_skills / n, 1),
            "avg_inspected_routers": round(total_inspected / n, 1),
            "total_runtime_s": round(total_time, 1),
        }
        summary[method] = method_summary
        
        print(f"\n  ── {method} Summary ──")
        print(f"  Accuracy:           {method_summary['accuracy_raw']} ({method_summary['accuracy']}%)")
        print(f"  Avg tokens:         {method_summary['avg_token_consumption']}")
        print(f"  Avg runtime:        {method_summary['avg_runtime_s']}s")
        print(f"  Avg rounds:         {method_summary['avg_rounds']}")
        print(f"  Avg skill calls:    {method_summary['avg_skill_calls']}")
        print(f"  Avg inspected:      {method_summary['avg_inspected_routers']}")
    
    # Save all results
    with open(os.path.join(log_dir, "all_results.json"), "w") as f:
        json.dump(all_results, f, indent=2)
    
    # Save summary
    with open(os.path.join(log_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    
    # Print final summary table
    if len(summary) > 1:
        print(f"\n{'='*80}")
        print(f"  COMPARISON ({args.topology}, k={args.k}, model={args.model})")
        print(f"{'='*80}")
        print(f"  {'Method':<16} {'Accuracy':>10} {'Tokens':>10} {'Runtime':>10} {'Rounds':>8} {'Skills':>8} {'Inspected':>10}")
        print(f"  {'-'*16} {'-'*10} {'-'*10} {'-'*10} {'-'*8} {'-'*8} {'-'*10}")
        for m, s in summary.items():
            print(f"  {m:<16} {s['accuracy_raw']:>10} {s['avg_token_consumption']:>10} {s['avg_runtime_s']:>9}s {s['avg_rounds']:>8} {s['avg_skill_calls']:>8} {s['avg_inspected_routers']:>10}")
    
    print(f"\n  Logs saved to: {log_dir}/")
    print(f"  Config:         {log_dir}/config.json")
    print(f"  Results:        {log_dir}/all_results.json")
    print(f"  Summary:        {log_dir}/summary.json")
    print(f"  Per-instance:   {log_dir}/<method>_<type>_p<id>_c<id>.json")


if __name__ == "__main__":
    main()
