#!/usr/bin/env python3
"""(4) Compound: per [LLM, k, agent_skills] — avg metrics.

Accuracy: status!='ok' records counted as wrong (denominator=all, numerator=ok&correct).
Overflow flag: marked when overflow rate exceeds 25%.

Usage: python3 extract_compound.py
"""
import json, os

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
OVF_THRESH = 0.25
TLE_THRESH = 3600
FT_ROUTERS = {4:20, 8:80, 12:180, 16:320, 20:500, 30:1125, 50:3125, 80:8000, 120:18000, 160:32000, 200:50000}

def load_recs(exp_dir, k, method='agent_skills'):
    """Load all records; return (all_recs, ok_recs)."""
    dd = os.path.join(exp_dir, f'k{k}', 'details')
    if not os.path.isdir(dd):
        return [], []
    recs = []
    for fn in sorted(os.listdir(dd)):
        if fn.startswith(f'{method}_') and fn.endswith('.json'):
            with open(os.path.join(dd, fn)) as f:
                recs.extend(json.load(f))
    return recs, [r for r in recs if r.get('status') == 'ok']

def check_flags(ok, total):
    if not ok or total == 0:
        return True, False
    n_tok0 = sum(1 for r in ok if r.get('token_consumption', 0) == 0)
    n_ovf = sum(1 for r in ok if r.get('context_overflow', False))
    n_tle = sum(1 for r in ok if r.get('runtime_s', 0) >= TLE_THRESH)
    is_ovf = (n_ovf / total > OVF_THRESH) or (n_tok0 / len(ok) > OVF_THRESH)
    is_tle = n_tle / len(ok) > OVF_THRESH
    return is_ovf, is_tle

if __name__ == '__main__':
    for model in ['gpt-5.4', 'gpt-4o']:
        exp_dir = None
        for d in sorted(os.listdir(BASE)):
            if d.startswith(f'compound_{model}_') and not d.startswith('resume'):
                exp_dir = os.path.join(BASE, d)
        if not exp_dir:
            continue

        print(f"\n{'='*70}")
        print(f"Compound {model} (agent_skills)")
        print(f"{'='*70}")
        print(f"{'k':>5} {'Routers':>8} {'Acc':>7} {'Tok':>7} {'tLLM':>7} {'tTot':>8} {'RLLM':>5} {'RTool':>6} {'Flag':>5}")
        print("-"*65)

        for k in K_VALUES:
            recs, ok = load_recs(exp_dir, k)
            if not recs:
                continue
            is_ovf, is_tle = check_flags(ok, len(recs))

            # Accuracy: non-ok records count as wrong
            correct = sum(1 for r in ok if r.get('correct'))
            n_total = len(recs)
            n_ok = len(ok)

            # Avg metrics computed over ok records only
            ok_tok = [r for r in ok if r.get('token_consumption', 0) > 0]
            avg_tok = sum(r['token_consumption'] for r in ok_tok)/len(ok_tok)/1000 if ok_tok else 0
            avg_llm = sum(r.get('llm_time_s',0) for r in ok)/n_ok if n_ok else 0
            avg_tot = sum(r.get('runtime_s',0) for r in ok)/n_ok if n_ok else 0
            avg_rllm = sum(r.get('rounds',0) for r in ok)/n_ok if n_ok else 0
            avg_rtool = sum(r.get('tool_calls',0) for r in ok)/n_ok if n_ok else 0

            flag = 'OVF' if is_ovf else ('TLE' if is_tle else '')
            routers = FT_ROUTERS.get(k, 0)

            print(f"{k:>5} {routers:>8,} {100*correct/n_total:>6.1f}% "
                  f"{avg_tok:>5.0f}K "
                  f"{avg_llm:>6.0f}s "
                  f"{avg_tot:>7.0f}s "
                  f"{avg_rllm:>4.1f} "
                  f"{avg_rtool:>5.1f} {flag:>5}")
