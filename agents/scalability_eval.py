#!/usr/bin/env python3
"""Scalability evaluation: run all methods across k values with configurable
instance count (--ch-num), gap-filling resume, and recalculated summaries.

Usage:
    python -m agents.scalability_eval --topology fattree --model gpt-5.4 --ch-num 20 --workers 48
    python -m agents.scalability_eval --topology fattree --model gpt-5.4 --ch-num 20 --workers 48 --resume

Output: logs/new_scale/<topology>_<model>_<timestamp>/
"""
import argparse
import builtins
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

EXP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, EXP_DIR)
os.chdir(EXP_DIR)

K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
METHODS = ["in_context_learning", "iterative_reasoning", "agent_skills"]

# Non-special errors: total attempts = 3 (initial + 2 retries)
MAX_RETRIES = 2

# 429 / 403 / 409 / connection errors: up to 100 retries, print every 10
SPECIAL_ERROR_MAX_RETRIES = 100
SPECIAL_ERROR_LOG_INTERVAL = 10
SPECIAL_ERROR_BACKOFF_STEP_SECONDS = 30

CONTEXT_OVERFLOW_THRESHOLD = 0.25
PARALLEL_WORKERS = 8

_builtin_print = builtins.print


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _state_file(output_dir, topology, model):
    safe_model = model.replace("/", "_")
    return os.path.join(output_dir, f"resume_state_{topology}_{safe_model}.json")


def _find_latest_log_dir(output_dir, topology, model):
    prefix = f"{topology}_{model}_"
    if not os.path.isdir(output_dir):
        return None
    candidates = [
        os.path.join(output_dir, name)
        for name in os.listdir(output_dir)
        if os.path.isdir(os.path.join(output_dir, name)) and name.startswith(prefix)
    ]
    return max(candidates, key=os.path.getmtime) if candidates else None


def _init_logger(log_file, is_resume):
    marker = "RESUME" if is_resume else "START"
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n\n[{_now_str()}] ===== {marker} PID={os.getpid()} =====\n")

    def _log_print(*args, **kwargs):
        _builtin_print(*args, **kwargs)
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        msg = sep.join(str(x) for x in args) + end
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(msg)
        except Exception:
            pass

    return _log_print


def _save_json(path, payload):
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _save_checkpoint(checkpoint_file, payload):
    _save_json(checkpoint_file, {"ts": _now_str(), **payload})


# ─── Instance selection ───


def select_instances(all_instances, ch_num):
    """Select uniform instances: first ch_num instances per change_type.
    
    Each change_type has 20 pairs × 5 changes = 100 instances.
    We select by sorting (pair_id, change_id) and taking first ch_num.
    """
    by_type = defaultdict(list)
    for inst in all_instances:
        ct = inst.get("change_type") or inst.get("scenario", "unknown")
        by_type[ct].append(inst)

    selected = []
    for ct in sorted(by_type.keys()):
        insts = sorted(by_type[ct], key=lambda x: (x["pair_id"], x["change_id"]))
        selected.extend(insts[:ch_num])
    return selected


def get_done_keys(detail_dir, method):
    """Get set of (change_type, pair_id, change_id) already completed."""
    done = set()
    import glob
    for f in glob.glob(os.path.join(detail_dir, f"{method}_*.json")):
        try:
            with open(f) as fh:
                for r in json.load(fh):
                    done.add((r["change_type"], r["pair_id"], r["change_id"]))
        except Exception:
            pass
    return done


# ─── Core evaluation ───


def load_instances(topology, k):
    if topology == "fattree":
        base = f"data/fattree/fattreek{str(k).zfill(3)}"
    elif topology == "crossdc":
        base = f"data/crossdc/crossdck{str(k).zfill(3)}"
    elif topology == "compound":
        base = f"data/compound/compoundk{str(k).zfill(3)}"
    else:
        base = f"data/fattree/fattreek{str(k).zfill(3)}"

    gt_file = os.path.join(base, "ground_truth.json")
    if topology == "compound":
        gt_file = os.path.join(base, "compound_ground_truth.json")

    if not os.path.exists(gt_file):
        return [], ""
    with open(gt_file) as f:
        instances = json.load(f)
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


def _is_special_retry_error(err_msg):
    err_lower = err_msg.lower()
    return (
        "429" in err_msg
        or "403" in err_msg
        or "409" in err_msg
        or "rate limit" in err_lower
        or "connection error" in err_lower
        or "copytree" in err_lower
        or "shutil" in err_lower
    )


def _is_model_not_found(err_lower):
    return any(
        x in err_lower
        for x in [
            "model not found",
            "deploymentid not found",
            "deployment not found",
            "no such deployment",
        ]
    )


def run_single_instance(
    method, instance, before_dir, model_name, topology, k, log_dir, checkpoint_file, completed_summary_records
):
    ct = instance.get("change_type") or instance.get("scenario", "unknown")
    pid = instance["pair_id"]
    cid = instance["change_id"]

    retries_used = 0
    while True:
        try:
            t0 = time.time()

            if method == "in_context_learning":
                from agents.in_context_learning.agent import run
            elif method == "iterative_reasoning":
                from agents.iterative_reasoning.agent import run
            elif method == "agent_skills":
                from agents.agent_skills.agent import run

            result = run(instance, before_dir, model_name=model_name, topology=topology)
            wall_time = time.time() - t0

            eval_result = evaluate_answer(result.get("answer"), instance)
            metrics = result.get("metrics", {})

            return {
                "status": "ok",
                "method": method,
                "change_type": ct,
                "pair_id": pid,
                "change_id": cid,
                "correct": eval_result["both_correct"],
                "token_consumption": metrics.get("total_tokens", 0),
                "llm_time_s": metrics.get("llm_time_s", 0),
                "tool_time_s": metrics.get("tool_time_s", 0),
                "runtime_s": metrics.get("runtime_s", 0),
                "wall_time_s": round(wall_time, 2),
                "rounds": metrics.get("rounds", 1),
                "skill_calls": metrics.get("skill_calls", 0),
                "tool_calls": metrics.get("tool_calls", 0),
                "inspected_routers": metrics.get("inspected_routers", 0),
                "context_overflow": False,
                "attempt": retries_used + 1,
            }

        except Exception as e:
            err_msg = str(e)
            err_lower = err_msg.lower()

            # Context window overflow
            if any(
                x in err_lower
                for x in [
                    "context_length_exceeded",
                    "context window",
                    "maximum context length",
                    "too many tokens",
                    "request too large",
                ]
            ):
                return {
                    "status": "context_overflow",
                    "method": method,
                    "change_type": ct,
                    "pair_id": pid,
                    "change_id": cid,
                    "correct": False,
                    "token_consumption": 0,
                    "runtime_s": 0,
                    "rounds": 0,
                    "skill_calls": 0,
                    "tool_calls": 0,
                    "inspected_routers": 0,
                    "context_overflow": True,
                    "error": err_msg[:200],
                    "attempt": retries_used + 1,
                }

            context = {
                "topology": topology,
                "model": model_name,
                "log_dir": log_dir,
                "k": k,
                "method": method,
                "change_type": ct,
                "pair_id": pid,
                "change_id": cid,
                "retries_used": retries_used,
                "completed_summary_records": completed_summary_records,
            }

            # Model/deployment not found: wait 1 hour and retry.
            if _is_model_not_found(err_lower):
                retries_used += 1
                print(f"\n!!! [{_now_str()}] MODEL NOT FOUND: {model_name} \u2014 sleeping 1h")
                _save_checkpoint(checkpoint_file, {"status": "model_not_found_waiting", **context})
                time.sleep(3600)
                continue

            is_special = _is_special_retry_error(err_msg)

            if "429" in err_msg or "rate limit" in err_lower:
                err_short = "429 Rate Limit"
            elif "403" in err_msg:
                err_short = "403 Forbidden"
            elif "409" in err_msg:
                err_short = "409 Conflict"
            elif "connection error" in err_lower:
                err_short = "Connection error"
            elif "upstream request timeout" in err_lower:
                err_short = "upstream timeout"
            elif "copytree" in err_lower or "shutil" in err_lower:
                err_short = "copytree conflict"
            else:
                err_short = err_msg[:100]

            max_retries = SPECIAL_ERROR_MAX_RETRIES if is_special else MAX_RETRIES

            if retries_used >= max_retries:
                if is_special:
                    print(f"\n!!! [{_now_str()}] {err_short} hit {max_retries} retries — cooling 15min")
                    _save_checkpoint(checkpoint_file, {"status": "rate_limit_cooldown", **context})
                    time.sleep(900)
                    retries_used = 0
                    continue

                print(f"    [FAIL] {method} {ct} p{pid}c{cid}: {err_short} (skip)")
                return {
                    "status": "error",
                    "method": method,
                    "change_type": ct,
                    "pair_id": pid,
                    "change_id": cid,
                    "correct": False,
                    "token_consumption": 0,
                    "runtime_s": 0,
                    "rounds": 0,
                    "skill_calls": 0,
                    "tool_calls": 0,
                    "inspected_routers": 0,
                    "context_overflow": False,
                    "error": err_msg[:200],
                    "attempt": retries_used + 1,
                }

            retries_used += 1

            if is_special:
                backoff_s = max(
                    5,
                    (retries_used // SPECIAL_ERROR_LOG_INTERVAL) * SPECIAL_ERROR_BACKOFF_STEP_SECONDS,
                )
                if retries_used % SPECIAL_ERROR_LOG_INTERVAL == 0:
                    print(f"    [RETRY {retries_used}] {method} {ct} p{pid}c{cid}: {err_short}; backoff={backoff_s}s")
            else:
                backoff_s = 5

            _save_checkpoint(
                checkpoint_file,
                {
                    "status": "retrying",
                    **context,
                    "retries_used": retries_used,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            time.sleep(backoff_s)


def _compute_summary(results, method, k, topology, model_name):
    ok_results = [r for r in results if r["status"] == "ok"]
    n_ok = len(ok_results)
    n_total = len(results)
    n_overflow = sum(1 for r in results if r.get("context_overflow"))
    n_correct = sum(1 for r in ok_results if r["correct"])
    accuracy = round(n_correct / max(1, n_ok) * 100, 1)

    should_stop = False
    stop_reason = None
    by_type = defaultdict(list)
    for r in results:
        ct = r.get("change_type", "?")
        by_type[ct].append(r)
    for ct, ct_results in by_type.items():
        n = len(ct_results)
        ovf = sum(1 for r in ct_results if r.get("context_overflow"))
        if n > 0 and ovf / n > CONTEXT_OVERFLOW_THRESHOLD:
            should_stop = True
            stop_reason = "overflow"

    return {
        "method": method,
        "k": k,
        "topology": topology,
        "model": model_name,
        "n_total": n_total,
        "n_ok": n_ok,
        "n_overflow": n_overflow,
        "n_errors": n_total - n_ok - n_overflow,
        "accuracy": accuracy,
        "accuracy_raw": f"{n_correct}/{n_ok}",
        "overflow_rate": round(n_overflow / max(1, n_total) * 100, 1),
        "avg_token_consumption": round(sum(r["token_consumption"] for r in ok_results) / max(1, n_ok)),
        "avg_llm_time_s": round(sum(r.get("llm_time_s", 0) for r in ok_results) / max(1, n_ok), 1),
        "avg_tool_time_s": round(sum(r.get("tool_time_s", 0) for r in ok_results) / max(1, n_ok), 1),
        "avg_runtime_s": round(sum(r.get("runtime_s", 0) for r in ok_results) / max(1, n_ok), 1),
        "avg_wall_time_s": round(sum(r.get("wall_time_s", 0) for r in ok_results) / max(1, n_ok), 1),
        "avg_rounds": round(sum(r["rounds"] for r in ok_results) / max(1, n_ok), 1),
        "avg_skill_calls": round(sum(r.get("skill_calls", 0) for r in ok_results) / max(1, n_ok), 1),
        "avg_tool_calls": round(sum(r.get("tool_calls", 0) for r in ok_results) / max(1, n_ok), 1),
        "avg_inspected_routers": round(sum(r.get("inspected_routers", 0) for r in ok_results) / max(1, n_ok), 1),
        "should_stop_scaling": should_stop,
        "stop_reason": stop_reason,
    }


def run_method_at_scale(
    method,
    instances,
    before_dir,
    model_name,
    topology,
    k,
    log_dir,
    checkpoint_file,
    completed_summary_records,
    workers=PARALLEL_WORKERS,
):
    """Run instances, gap-fill from existing detail files, return summary + results."""
    detail_dir = os.path.join(log_dir, "details")
    os.makedirs(detail_dir, exist_ok=True)

    # Load existing results for this method
    done_keys = get_done_keys(detail_dir, method)

    # Filter to only missing instances
    to_run = [
        inst
        for inst in instances
        if (
            inst.get("change_type") or inst.get("scenario", "unknown"),
            inst["pair_id"],
            inst["change_id"],
        )
        not in done_keys
    ]

    # Load previously completed results
    import glob as _glob
    existing_results = []
    for f in _glob.glob(os.path.join(detail_dir, f"{method}_*.json")):
        try:
            with open(f) as fh:
                existing_results.extend(json.load(fh))
        except Exception:
            pass

    if not to_run:
        print(f"    All {len(instances)} instances already done, recalculating summary...")
        # Filter existing to only selected instances
        target_keys = set(
            (
                inst.get("change_type") or inst.get("scenario", "unknown"),
                inst["pair_id"],
                inst["change_id"],
            )
            for inst in instances
        )
        filtered = [
            r
            for r in existing_results
            if (r["change_type"], r["pair_id"], r["change_id"]) in target_keys
        ]
        summary = _compute_summary(filtered, method, k, topology, model_name)
        return summary, filtered

    print(f"    {len(to_run)} new + {len(done_keys)} existing = {len(to_run)+len(done_keys)} total")

    by_type = defaultdict(list)
    for inst in to_run:
        ct = inst.get("change_type") or inst.get("scenario", "unknown")
        by_type[ct].append(inst)

    for ct, ct_instances in sorted(by_type.items()):
        print(f"    [{ct}] {len(ct_instances)} new...", flush=True)

    new_results = []
    ct_results_map = defaultdict(list)
    effective_workers = min(workers, len(to_run))

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = {
            executor.submit(
                run_single_instance,
                method,
                inst,
                before_dir,
                model_name,
                topology,
                k,
                log_dir,
                checkpoint_file,
                completed_summary_records,
            ): inst
            for inst in to_run
        }
        for f in as_completed(futures):
            inst = futures[f]
            ct = inst.get("change_type") or inst.get("scenario", "unknown")
            r = f.result()
            ct_results_map[ct].append(r)
            new_results.append(r)

            if len(ct_results_map[ct]) == len(by_type[ct]):
                ct_results = ct_results_map[ct]
                n = len(ct_results)
                correct = sum(1 for item in ct_results if item.get("correct"))
                sym = "Y" if correct == n else f"{correct}/{n}"
                print(f"      -> [{ct}] done: {sym}")

                detail_file = os.path.join(detail_dir, f"{method}_{ct}.json")
                existing_ct = []
                if os.path.exists(detail_file):
                    try:
                        with open(detail_file) as fh:
                            existing_ct = json.load(fh)
                    except Exception:
                        pass
                existing_ct.extend(ct_results)
                with open(detail_file, "w") as fh:
                    json.dump(existing_ct, fh, indent=2)

    # Compute summary from ALL results (existing + new) filtered to target instances
    all_results = existing_results + new_results
    target_keys = set(
        (
            inst.get("change_type") or inst.get("scenario", "unknown"),
            inst["pair_id"],
            inst["change_id"],
        )
        for inst in instances
    )
    filtered = [
        r
        for r in all_results
        if (r["change_type"], r["pair_id"], r["change_id"]) in target_keys
    ]
    # Deduplicate: keep latest result per (ct, pid, cid)
    seen = {}
    for r in filtered:
        key = (r["change_type"], r["pair_id"], r["change_id"])
        seen[key] = r
    filtered = list(seen.values())

    summary = _compute_summary(filtered, method, k, topology, model_name)
    return summary, filtered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topology", default="fattree")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--k-values", nargs="+", type=int, default=None)
    parser.add_argument("--methods", nargs="+", default=None)
    parser.add_argument("--workers", type=int, default=PARALLEL_WORKERS)
    parser.add_argument("--output-dir", default="logs/new_scale")
    parser.add_argument("--resume", action="store_true", help="Resume / gap-fill from previous run")
    parser.add_argument(
        "--ch-num",
        type=int,
        default=20,
        help="Number of instances per change_type (e.g., 3->18 total, 20->120 total, 100->600 total)",
    )
    args = parser.parse_args()

    workers = args.workers
    k_values = args.k_values or K_VALUES
    methods = args.methods or METHODS
    ch_num = args.ch_num

    os.makedirs(args.output_dir, exist_ok=True)
    state_file = _state_file(args.output_dir, args.topology, args.model)

    is_resume = False
    log_dir = None
    if args.resume:
        state = _load_json(state_file)
        if state and state.get("log_dir") and os.path.isdir(state["log_dir"]):
            log_dir = state["log_dir"]
            is_resume = True
        else:
            latest = _find_latest_log_dir(args.output_dir, args.topology, args.model)
            if latest:
                log_dir = latest
                is_resume = True

    if not log_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(args.output_dir, f"{args.topology}_{args.model}_{timestamp}")
        os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, "scalability_eval.log")
    global print
    print = _init_logger(log_file, is_resume=is_resume)

    checkpoint_file = os.path.join(log_dir, "resume_checkpoint.json")

    _save_json(
        state_file,
        {"ts": _now_str(), "topology": args.topology, "model": args.model, "log_dir": log_dir},
    )

    if not os.path.exists(os.path.join(log_dir, "config.json")):
        _save_json(
            os.path.join(log_dir, "config.json"),
            {
                "topology": args.topology,
                "model": args.model,
                "k_values": k_values,
                "methods": methods,
                "workers": workers,
                "ch_num": ch_num,
                "created_ts": _now_str(),
            },
        )

    print("Scalability Evaluation v2")
    print(f"  Topology: {args.topology}")
    print(f"  Model: {args.model}")
    print(f"  K values: {k_values}")
    print(f"  Methods: {methods}")
    print(f"  Workers: {workers}")
    print(f"  ch_num: {ch_num} per change_type")
    print(f"  Log dir: {log_dir}")
    print(f"  Resume: {is_resume}")

    all_summaries = []
    method_stop = {m: False for m in methods}

    for k in k_values:
        n_routers = 5 * k * k // 4
        instances, before_dir = load_instances(args.topology, k)
        if not instances:
            print(f"\n[SKIP] k={k}: no data found")
            continue

        # Select instances based on ch_num
        selected = select_instances(instances, ch_num)

        print(f"\n{'='*70}")
        print(f"  k={k} ({n_routers} routers), {len(selected)} instances (ch_num={ch_num})")
        print(f"{'='*70}")

        k_log_dir = os.path.join(log_dir, f"k{k}")
        os.makedirs(k_log_dir, exist_ok=True)

        for method in methods:
            if method_stop[method]:
                print(f"\n  [{method}] SKIPPED (overflow threshold)")
                all_summaries.append(
                    {"method": method, "k": k, "topology": args.topology, "status": "skipped_overflow", "n_total": 0}
                )
                continue

            # Filter selected instances for this method
            method_instances = selected

            _save_checkpoint(
                checkpoint_file,
                {
                    "status": "running",
                    "log_dir": log_dir,
                    "topology": args.topology,
                    "model": args.model,
                    "k": k,
                    "method": method,
                    "ch_num": ch_num,
                },
            )

            print(f"\n  [{method}]")
            summary, _results = run_method_at_scale(
                method,
                method_instances,
                before_dir,
                args.model,
                args.topology,
                k,
                k_log_dir,
                checkpoint_file,
                completed_summary_records=len(all_summaries),
                workers=workers,
            )

            all_summaries.append(summary)

            print(f"    -> Accuracy: {summary['accuracy_raw']} ({summary['accuracy']}%)")
            print(f"    -> Tokens: {summary['avg_token_consumption']}, Runtime: {summary['avg_runtime_s']}s")
            print(
                f"    -> Rounds: {summary['avg_rounds']}, Skills: {summary['avg_skill_calls']}, "
                f"Tools: {summary['avg_tool_calls']}, Inspected: {summary['avg_inspected_routers']}"
            )
            if summary["n_overflow"] > 0:
                print(f"    -> Overflow: {summary['n_overflow']}/{summary['n_total']} ({summary['overflow_rate']}%)")

            if summary.get("should_stop_scaling"):
                print(f"    -> STOPPING: overflow >{CONTEXT_OVERFLOW_THRESHOLD*100}%")
                method_stop[method] = True

            _save_json(os.path.join(k_log_dir, f"{method}_summary.json"), summary)

        if all(method_stop.values()):
            print("\n[STOP] All methods overflow")
            break

    _save_json(os.path.join(log_dir, "all_summaries.json"), all_summaries)

    # Report
    report_lines = [
        f"Scalability Report - {args.topology} / {args.model} (ch_num={ch_num})",
        f"Generated: {_now_str()}",
        "",
        f"{'k':>5} {'Method':<16} {'Acc':>8} {'Tokens':>10} {'LLM_t':>8} {'Tool_t':>8} {'Time':>8} {'Rounds':>7} {'OVF%':>6}",
        "-" * 90,
    ]
    for s in all_summaries:
        if s.get("status") == "skipped_overflow":
            continue
        report_lines.append(
            f"{s['k']:>5} {s['method']:<16} {s['accuracy']:>7.1f}% {s['avg_token_consumption']:>10} "
            f"{s.get('avg_llm_time_s',0):>7.1f}s {s.get('avg_tool_time_s',0):>7.1f}s "
            f"{s['avg_runtime_s']:>7.1f}s {s['avg_rounds']:>7.1f} {s['overflow_rate']:>5.1f}%"
        )

    report = "\n".join(report_lines)
    print(f"\n{'='*90}")
    print(report)
    print(f"{'='*90}")

    with open(os.path.join(log_dir, "scalability_report.txt"), "w") as f:
        f.write(report)

    print(f"\nResults saved to: {log_dir}/")

    try:
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)
    except Exception:
        pass


if __name__ == "__main__":
    main()
