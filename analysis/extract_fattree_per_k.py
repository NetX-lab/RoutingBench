#!/usr/bin/env python3
"""(1) Fattree: per [LLM, k, agent] — avg metrics + overflow detection.

Overflow: token=0 > 25% OR context_overflow > 25% among ok records.
Time limit: runtime >= 3600s > 25% among ok records.

Usage: python3 extract_fattree_per_k.py
"""
import json, os, glob

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
METHODS = ['in_context_learning', 'iterative_reasoning', 'agent_skills']
OVF_THRESH = 0.25
TLE_THRESH = 3600

def load_details(exp_dir, k, method):
    dd = os.path.join(exp_dir, f'k{k}', 'details')
    if not os.path.isdir(dd):
        return []
    recs = []
    for fn in sorted(os.listdir(dd)):
        if fn.startswith(f'{method}_') and fn.endswith('.json'):
            with open(os.path.join(dd, fn)) as f:
                recs.extend(json.load(f))
    return recs

def compute_metrics(recs):
    ok = [r for r in recs if r.get('status') == 'ok']
    if not ok:
        return None
    n_ok = len(ok)
    n_total = len(recs)
    n_ovf = sum(1 for r in recs if r.get('context_overflow', False))
    n_tok0 = sum(1 for r in ok if r.get('token_consumption', 0) == 0)
    n_tle = sum(1 for r in ok if r.get('runtime_s', 0) >= TLE_THRESH)
    
    is_overflow = (n_ovf / n_total > OVF_THRESH if n_total else False) or \
                  (n_tok0 / n_ok > OVF_THRESH if n_ok else False)
    is_tle = (n_tle / n_ok > OVF_THRESH) if n_ok else False
    
    correct = sum(1 for r in ok if r.get('correct'))
    ok_with_tok = [r for r in ok if r.get('token_consumption', 0) > 0]
    
    return {
        'n_total': n_total,
        'n_ok': n_ok,
        'accuracy': round(100 * correct / n_total, 1),
        'avg_tokens': round(sum(r['token_consumption'] for r in ok_with_tok) / len(ok_with_tok)) if ok_with_tok else 0,
        'avg_llm_time': round(sum(r.get('llm_time_s', 0) for r in ok) / n_ok, 1),
        'avg_total_time': round(sum(r.get('runtime_s', 0) for r in ok) / n_ok, 1),
        'avg_llm_rounds': round(sum(r.get('rounds', 0) for r in ok) / n_ok, 1),
        'avg_tool_rounds': round(sum(r.get('tool_calls', 0) for r in ok) / n_ok, 1),
        'overflow': is_overflow,
        'time_limit': is_tle,
        'ovf_rate': round(n_ovf / n_total, 3) if n_total else 0,
        'tok0_rate': round(n_tok0 / n_ok, 3) if n_ok else 0,
        'tle_rate': round(n_tle / n_ok, 3) if n_ok else 0,
    }

if __name__ == '__main__':
    for exp_name in sorted(os.listdir(BASE)):
        if not exp_name.startswith('fattree_') or exp_name.startswith('resume'):
            continue
        exp_dir = os.path.join(BASE, exp_name)
        if not os.path.isdir(exp_dir):
            continue
        
        model = exp_name.split('_')[1]
        print(f"\n{'='*80}")
        print(f"LLM: {model}")
        print(f"{'='*80}")
        
        for method in METHODS:
            has_data = False
            for k in K_VALUES:
                recs = load_details(exp_dir, k, method)
                if not recs:
                    continue
                m = compute_metrics(recs)
                if m is None:
                    continue
                if not has_data:
                    print(f"\n  {method}:")
                    print(f"  {'k':>5} {'Acc':>7} {'Tok':>7} {'tLLM':>7} {'tTot':>8} {'RLLM':>5} {'RTool':>6} {'OVF':>4} {'TLE':>4}")
                    print(f"  {'-'*58}")
                    has_data = True
                
                ovf_mark = 'OVF' if m['overflow'] else ''
                tle_mark = 'TLE' if m['time_limit'] else ''
                flag = ovf_mark or tle_mark or ''
                print(f"  {k:>5} {m['accuracy']:>6.1f}% {m['avg_tokens']/1000:>5.0f}K {m['avg_llm_time']:>6.0f}s {m['avg_total_time']:>7.0f}s {m['avg_llm_rounds']:>4.1f} {m['avg_tool_rounds']:>5.1f} {flag:>4}")
