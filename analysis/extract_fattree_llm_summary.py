#!/usr/bin/env python3
"""(2) Fattree: per LLM — find max k (agent_skills), compute averages over valid scales.

MaxK = largest k where neither overflow nor time_limit is triggered.
Averages computed only over k <= MaxK.

Usage: python3 extract_fattree_llm_summary.py
"""
import json, os

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
OVF_THRESH = 0.25
TLE_THRESH = 3600

MODEL_ORDER = [
    ('gpt-5.4', 'GPT-5.4'),
    ('Qwen', 'Qwen-3.5-397B'),
    ('o3', 'o3'),
    ('DeepSeek-V4-Pro', 'DeepSeek-V4-Pro'),
    ('gpt-4o', 'GPT-4o'),
    ('Llama', 'Llama-3.3-70B'),
]

def load_all_ok(exp_dir, k, method='agent_skills'):
    dd = os.path.join(exp_dir, f'k{k}', 'details')
    if not os.path.isdir(dd):
        return [], 0
    recs = []
    for fn in sorted(os.listdir(dd)):
        if fn.startswith(f'{method}_') and fn.endswith('.json'):
            with open(os.path.join(dd, fn)) as f:
                recs.extend(json.load(f))
    n_total = len(recs)
    ok = [r for r in recs if r.get('status') == 'ok']
    return ok, n_total

def is_overflow(ok_recs, total):
    if total == 0:
        return True
    n_ok = len(ok_recs)
    if n_ok == 0:
        return True
    n_tok0 = sum(1 for r in ok_recs if r.get('token_consumption', 0) == 0)
    n_ovf = sum(1 for r in ok_recs if r.get('context_overflow', False))
    # Check against total for overflow flag, against ok for tok0
    return (n_ovf / total > OVF_THRESH) or (n_tok0 / n_ok > OVF_THRESH)

def is_time_limit(ok_recs):
    if not ok_recs:
        return False
    n_tle = sum(1 for r in ok_recs if r.get('runtime_s', 0) >= TLE_THRESH)
    return n_tle / len(ok_recs) > OVF_THRESH

ROUTERS = {4:20, 8:80, 12:180, 16:320, 20:500, 30:1125, 50:3125, 80:8000, 120:18000, 160:32000, 200:50000}

if __name__ == '__main__':
    print(f"{'Rank':>4} {'Model':<18} {'MaxK':>12} {'Acc':>7} {'Tok':>7} {'tLLM':>8} {'tTot':>9} {'RLLM':>6} {'RTool':>6}")
    print("-"*80)
    
    results = []
    for model_key, model_name in MODEL_ORDER:
        exp_dir = None
        for d in sorted(os.listdir(BASE)):
            if d.startswith(f'fattree_{model_key}_') and not d.startswith('resume'):
                exp_dir = os.path.join(BASE, d)
        if not exp_dir:
            continue
        
        # Find max k
        max_k = 0
        valid_ks = []
        for k in K_VALUES:
            ok, total = load_all_ok(exp_dir, k)
            if not ok and total == 0:
                continue
            if is_overflow(ok, total) or is_time_limit(ok):
                continue
            valid_ks.append(k)
            max_k = k
        
        if not valid_ks:
            results.append((model_name, 0, 0, 0, 0, 0, 0, 0, 0))
            continue
        
        # Compute averages over valid ks
        all_ok = []
        all_total = 0
        for k in valid_ks:
            ok, total = load_all_ok(exp_dir, k)
            all_ok.extend(ok)
            all_total += total

        n = len(all_ok)
        correct = sum(1 for r in all_ok if r.get('correct'))
        ok_with_tok = [r for r in all_ok if r.get('token_consumption', 0) > 0]
        avg_tok = sum(r['token_consumption'] for r in ok_with_tok) / len(ok_with_tok) if ok_with_tok else 0
        avg_llm = sum(r.get('llm_time_s', 0) for r in all_ok) / n if n else 0
        avg_tot = sum(r.get('runtime_s', 0) for r in all_ok) / n if n else 0
        avg_rllm = sum(r.get('rounds', 0) for r in all_ok) / n if n else 0
        avg_rtool = sum(r.get('tool_calls', 0) for r in all_ok) / n if n else 0
        # Accuracy: non-ok records counted as wrong
        acc = 100 * correct / all_total if all_total else 0
        
        results.append((model_name, max_k, acc, avg_tok, avg_llm, avg_tot, avg_rllm, avg_rtool, ROUTERS.get(max_k, 0)))
    
    results.sort(key=lambda x: -x[2])  # sort by accuracy
    for rank, (name, mk, acc, tok, llm, tot, rllm, rtool, routers) in enumerate(results, 1):
        print(f"{rank:>4} {name:<18} {mk:>3} ({routers:>5}) {acc:>6.1f}% {tok/1000:>5.0f}K {llm:>7.0f}s {tot:>8.0f}s {rllm:>5.1f} {rtool:>5.1f}")
    
    print(f"\nValid k ranges:")
    for model_key, model_name in MODEL_ORDER:
        exp_dir = None
        for d in sorted(os.listdir(BASE)):
            if d.lower().startswith(f'fattree_{model_key}_'.lower()) and not d.startswith('resume'):
                exp_dir = os.path.join(BASE, d)
        if not exp_dir:
            continue
        vks = []
        for k in K_VALUES:
            ok, total = load_all_ok(exp_dir, k)
            if not ok and total == 0:
                continue
            ovf = is_overflow(ok, total)
            tle = is_time_limit(ok)
            status = 'OVF' if ovf else ('TLE' if tle else 'ok')
            vks.append(f"k={k}:{status}")
        print(f"  {model_name:<18} {', '.join(vks)}")
