#!/usr/bin/env python3
"""(3) Cross-DC per [LLM, k, agent]: avg metrics + OVF/TLE flags.

Used for: Tables 3 (main paper) and Appendix tables.
Only GPT-5.4 and GPT-4o (cross-DC was tested with these).

Usage: python3 xdc-llm-agent.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from _common import compute_metrics

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
METHODS = ['in_context_learning', 'iterative_reasoning', 'agent_skills']

# Cross-DC routers: 2 * 5*k^2/4 + 2*k gateways
def xdc_routers(k):
    return 2 * (5 * k * k // 4) + 2 * k

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

def find_exp_dir(model_key):
    for d in sorted(os.listdir(BASE)):
        if d.lower().startswith(f'crossdc_{model_key}_'.lower()) and not d.startswith('resume'):
            return os.path.join(BASE, d)
    return None

MODELS = [('gpt-5.4', 'GPT-5.4'), ('gpt-4o', 'GPT-4o')]

if __name__ == '__main__':
    all_results = {}
    for model_key, model_name in MODELS:
        exp_dir = find_exp_dir(model_key)
        if not exp_dir:
            continue
        print(f"\n{'='*100}")
        print(f"Cross-DC {model_name}")
        print(f"{'='*100}")
        print(f"{'k':>4} {'Routers':>8}", end='')
        for method in METHODS:
            short = {'in_context_learning':'FC','iterative_reasoning':'MR','agent_skills':'AS'}[method]
            print(f"  | {short}: {'Acc':>6} {'Tok':>6} {'tLLM':>7} {'tTot':>8} {'RLLM':>5} {'RTool':>5}", end='')
        print()
        results = {}
        for k in K_VALUES:
            row = {}
            print(f"{k:>4} {xdc_routers(k):>8,}", end='')
            for method in METHODS:
                recs = load_records(exp_dir, k, method, model_key)
                if not recs:
                    print(f"  | {'':>45}", end='')
                    continue
                m = compute_metrics(recs)
                row[method] = m
                if m['flag']:
                    print(f"  |   {m['flag']:>5}{'':>40}", end='')
                else:
                    print(f"  |   {m['acc']:>5.1f}% {m['tok']/1000:>5.0f}K {m['llm_t']:>6.0f}s {m['tot_t']:>7.0f}s {m['rllm']:>4.1f} {m['rtool']:>4.1f}", end='')
            print()
            if row:
                results[k] = row
        all_results[model_key] = results

    # Save
    out_path = os.path.join(os.path.dirname(__file__), 'xdc_llm_agent_results.json')
    serializable = {mk: {str(k): v for k, v in d.items()} for mk, d in all_results.items()}
    with open(out_path, 'w') as f:
        json.dump(serializable, f, indent=2)
    print(f"\nSaved to {out_path}")
