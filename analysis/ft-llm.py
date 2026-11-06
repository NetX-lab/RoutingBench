#!/usr/bin/env python3
"""(2) Per-LLM summary on fattree.

For each LLM:
- k* = max k where [LLM, k, agent_skills] is NOT OVF and NOT TLE.
- Averages computed over all valid k <= k* (agent_skills only).

Used for: Table 2 (main paper).

Usage: python3 ft-llm.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import compute_metrics, scope_flag, is_record_ovf, is_record_tle

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
ROUTERS = {4:20, 8:80, 12:180, 16:320, 20:500, 30:1125, 50:3125, 80:8000, 120:18000, 160:32000, 200:50000}

MODELS = [
    ('gpt-5.4', 'GPT-5.4'),
    ('gpt-4o', 'GPT-4o'),
    ('o3', 'o3'),
    ('DeepSeek-V4-Pro', 'DeepSeek-V4-Pro'),
    ('Qwen', 'Qwen-3.5-397B'),
    ('Llama', 'Llama-3.3-70B'),
]

def load_records(exp_dir, k, method, model_key):
    dd = os.path.join(exp_dir, f'k{k}', 'details')
    if not os.path.isdir(dd):
        return []
    recs = []
    for fn in sorted(os.listdir(dd)):
        if fn.startswith(f'{method}_') and fn.endswith('.json'):
            with open(os.path.join(dd, fn)) as f:
                recs.extend(json.load(f))
    return recs

if __name__ == '__main__':
    print(f"{'Rank':>4} {'Model':<18} {'k*':>10} {'Acc':>7} {'Tok':>7} {'tLLM':>7} {'tTot':>8} {'RLLM':>5} {'RTool':>6}")
    print("-"*80)

    summary = []
    valid_ks_log = {}
    for model_key, model_name in MODELS:
        # Find exp dir
        exp_dir = None
        for d in sorted(os.listdir(BASE)):
            if d.lower().startswith(f'fattree_{model_key}_'.lower()) and not d.startswith('resume'):
                exp_dir = os.path.join(BASE, d)
        if not exp_dir:
            continue

        # Find max k* (agent_skills only) and the flag at the first failing k beyond k*
        k_star = 0
        valid_ks = []
        valid_status = []
        beyond_flag = ''   # flag at first k > k* that failed; '' means k*=200 (no failure observed)
        for k in K_VALUES:
            recs = load_records(exp_dir, k, 'agent_skills', model_key)
            if not recs:
                valid_status.append(f"k{k}:no-data")
                continue
            flag = scope_flag(recs)
            valid_status.append(f"k{k}:{flag or 'ok'}")
            if flag == '':
                valid_ks.append(k)
                k_star = k
            else:
                if not beyond_flag:
                    beyond_flag = flag  # capture only the first failing flag
        valid_ks_log[model_name] = valid_status

        if not valid_ks:
            print(f"     {model_name:<18}: NO valid k")
            continue

        # Aggregate all records across valid_ks
        all_recs = []
        for k in valid_ks:
            recs = load_records(exp_dir, k, 'agent_skills', model_key)
            all_recs.extend(recs)

        # Compute metrics on aggregate (treats LLM-level scope; recompute flag at this scope)
        m = compute_metrics(all_recs)
        if m is None:
            continue

        summary.append({
            'model': model_name,
            'k_star': k_star,
            'routers': ROUTERS.get(k_star, 0),
            'limit_reason': beyond_flag,  # '' / 'OVF' / 'TLE'
            'acc': m['acc'],
            'tok': m['tok'],
            'llm_t': m['llm_t'],
            'tot_t': m['tot_t'],
            'rllm': m['rllm'],
            'rtool': m['rtool'],
        })

    # Sort by accuracy desc
    summary.sort(key=lambda x: -x['acc'])
    for rank, s in enumerate(summary, 1):
        ks_str = f"{s['k_star']} ({s['routers']:,})"
        print(f"{rank:>4} {s['model']:<18} {ks_str:>10} {s['acc']:>6.1f}% "
              f"{s['tok']/1000:>5.0f}K {s['llm_t']:>6.0f}s {s['tot_t']:>7.0f}s "
              f"{s['rllm']:>4.1f} {s['rtool']:>5.1f}")

    print("\nValid k status (by model):")
    for model_name, status_list in valid_ks_log.items():
        print(f"  {model_name:<18}: {' '.join(status_list)}")

    # Save
    out_path = os.path.join(os.path.dirname(__file__), 'ft_llm_results.json')
    with open(out_path, 'w') as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved to {out_path}")
