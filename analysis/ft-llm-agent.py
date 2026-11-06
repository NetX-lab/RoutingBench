#!/usr/bin/env python3
"""(1) Fattree per [LLM, k, agent]: avg metrics + OVF/TLE flags.

For each LLM, prints per-k results across all 3 agents (in_context_learning, iterative_reasoning, agent_skills).
Used for: Figure 7 (GPT-5.4/GPT-4o) and Appendix tables (6 LLMs x all-method comparison).

Usage: python3 ft-llm-agent.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import compute_metrics

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
METHODS = ['in_context_learning', 'iterative_reasoning', 'agent_skills']
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

def find_exp_dir(model_key, topology='fattree'):
    for d in sorted(os.listdir(BASE)):
        if d.lower().startswith(f'{topology}_{model_key}_'.lower()) and not d.startswith('resume'):
            return os.path.join(BASE, d)
    return None

def get_results(model_key):
    """Return {k: {method: metrics}}"""
    exp_dir = find_exp_dir(model_key)
    if not exp_dir:
        return {}
    out = {}
    for k in K_VALUES:
        for method in METHODS:
            recs = load_records(exp_dir, k, method, model_key)
            if not recs:
                continue
            m = compute_metrics(recs)
            if m is None:
                continue
            out.setdefault(k, {})[method] = m
    return out

def print_one_model(model_key, model_name):
    results = get_results(model_key)
    if not results:
        print(f"\n{model_name}: NO DATA")
        return
    print(f"\n{'='*120}")
    print(f"{model_name} (fattree)")
    print(f"{'='*120}")
    print(f"{'k':>4} {'Routers':>7}", end='')
    for method in METHODS:
        short = {'in_context_learning':'FC','iterative_reasoning':'MR','agent_skills':'AS'}[method]
        print(f"  | {short}: {'Acc':>6} {'Tok':>6} {'tLLM':>7} {'tTot':>8} {'RLLM':>5} {'RTool':>5} {'flag':>4}", end='')
    print()
    for k in K_VALUES:
        if k not in results:
            continue
        print(f"{k:>4} {ROUTERS.get(k,0):>7,}", end='')
        for method in METHODS:
            if method not in results[k]:
                print(f"  | {'':>49}", end='')
                continue
            m = results[k][method]
            flag = m['flag']
            if flag == 'OVF':
                print(f"  |     {'OVF':>49}", end='')
            else:
                print(f"  |   {m['acc']:>5.1f}% {m['tok']/1000:>5.0f}K {m['llm_t']:>6.0f}s {m['tot_t']:>7.0f}s {m['rllm']:>4.1f} {m['rtool']:>4.1f} {flag:>4}", end='')
        print()
    return results

if __name__ == '__main__':
    all_results = {}
    for model_key, model_name in MODELS:
        all_results[model_key] = print_one_model(model_key, model_name)
    # Save as JSON for downstream use
    out_path = os.path.join(os.path.dirname(__file__), 'ft_llm_agent_results.json')
    serializable = {mk: {str(k): v for k, v in d.items()} for mk, d in all_results.items() if d}
    with open(out_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    print(f"\nSaved to {out_path}")
