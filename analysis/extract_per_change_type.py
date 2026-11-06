#!/usr/bin/env python3
"""(5) Per change type: per [LLM, k, agent, change_type] — avg metrics + overflow/TLE detection.

Covers all 10 change types: 6 single (fattree) + 4 compound.

Usage: python3 extract_per_change_type.py
"""
import json, os
from collections import defaultdict

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
OVF_THRESH = 0.25
TLE_THRESH = 3600

SINGLE_TYPES = ['local_preference', 'med', 'static_route', 'interface_shutdown', 'bgp_network', 'prefix_aggregation']
COMPOUND_TYPES = ['compound_lp_bgpnet', 'compound_lp_shutdown', 'compound_lp_static_shutdown', 'compound_lp_static_bgpnet_shutdown']

SHORT_NAMES = {
    'local_preference': 'LP',
    'med': 'MED',
    'static_route': 'Static',
    'interface_shutdown': 'Shut',
    'bgp_network': 'BGPNet',
    'prefix_aggregation': 'PfxAgg',
    'compound_lp_bgpnet': 'LP+Net',
    'compound_lp_shutdown': 'LP+Shut',
    'compound_lp_static_shutdown': 'LP+St+Shut',
    'compound_lp_static_bgpnet_shutdown': 'LP+St+Net+Shut',
}

def load_per_ct(exp_dir, k, method='agent_skills'):
    """Load records grouped by change_type."""
    dd = os.path.join(exp_dir, f'k{k}', 'details')
    if not os.path.isdir(dd):
        return {}
    by_ct = defaultdict(list)
    for fn in sorted(os.listdir(dd)):
        if fn.startswith(f'{method}_') and fn.endswith('.json'):
            with open(os.path.join(dd, fn)) as f:
                recs = json.load(f)
            for r in recs:
                by_ct[r.get('change_type', 'unknown')].append(r)
    return dict(by_ct)

def check_flags(recs):
    ok = [r for r in recs if r.get('status') == 'ok']
    total = len(recs)
    if not ok or total == 0:
        return True, False, ok  # overflow
    n_tok0 = sum(1 for r in ok if r.get('token_consumption', 0) == 0)
    n_ovf = sum(1 for r in recs if r.get('context_overflow', False))
    n_tle = sum(1 for r in ok if r.get('runtime_s', 0) >= TLE_THRESH)
    is_ovf = (n_ovf / total > OVF_THRESH) or (n_tok0 / len(ok) > OVF_THRESH)
    is_tle = n_tle / len(ok) > OVF_THRESH
    return is_ovf, is_tle, ok

def compute_row(ok):
    n = len(ok)
    if n == 0:
        return None
    correct = sum(1 for r in ok if r.get('correct'))
    ok_tok = [r for r in ok if r.get('token_consumption', 0) > 0]
    return {
        'n': n,
        'acc': round(100 * correct / n, 1),
        'tok': round(sum(r['token_consumption'] for r in ok_tok) / len(ok_tok)) if ok_tok else 0,
        'llm_t': round(sum(r.get('llm_time_s', 0) for r in ok) / n, 1),
        'tot_t': round(sum(r.get('runtime_s', 0) for r in ok) / n, 1),
        'rllm': round(sum(r.get('rounds', 0) for r in ok) / n, 1),
        'rtool': round(sum(r.get('tool_calls', 0) for r in ok) / n, 1),
    }

if __name__ == '__main__':
    # Fattree single changes
    for exp_name in sorted(os.listdir(BASE)):
        if not exp_name.startswith('fattree_') or exp_name.startswith('resume'):
            continue
        exp_dir = os.path.join(BASE, exp_name)
        model = exp_name.split('_')[1]
        
        print(f"\n{'='*90}")
        print(f"Fattree {model} — per change type (agent_skills)")
        print(f"{'='*90}")
        
        # Header
        ct_names = [SHORT_NAMES[ct] for ct in SINGLE_TYPES]
        print(f"{'k':>5} |", end="")
        for name in ct_names:
            print(f" {name:>8}", end="")
        print()
        print(f"{'-'*5}-+-{'-'*54}")
        
        for k in K_VALUES:
            by_ct = load_per_ct(exp_dir, k)
            if not by_ct:
                continue
            print(f"{k:>5} |", end="")
            for ct in SINGLE_TYPES:
                recs = by_ct.get(ct, [])
                if not recs:
                    print(f" {'--':>8}", end="")
                    continue
                is_ovf, is_tle, ok = check_flags(recs)
                if is_ovf:
                    print(f" {'OVF':>8}", end="")
                elif is_tle:
                    print(f" {'TLE':>8}", end="")
                elif ok:
                    correct = sum(1 for r in ok if r.get('correct'))
                    acc = 100 * correct / len(recs)
                    print(f" {acc:>7.0f}%", end="")
                else:
                    print(f" {'--':>8}", end="")
            print()
    
    # Compound changes
    for exp_name in sorted(os.listdir(BASE)):
        if not exp_name.startswith('compound_') or exp_name.startswith('resume'):
            continue
        exp_dir = os.path.join(BASE, exp_name)
        model = exp_name.split('_')[1]
        
        print(f"\n{'='*90}")
        print(f"Compound {model} — per change type (agent_skills)")
        print(f"{'='*90}")
        
        ct_names = [SHORT_NAMES[ct] for ct in COMPOUND_TYPES]
        print(f"{'k':>5} |", end="")
        for name in ct_names:
            print(f" {name:>15}", end="")
        print()
        print(f"{'-'*5}-+-{'-'*64}")
        
        for k in K_VALUES:
            by_ct = load_per_ct(exp_dir, k)
            if not by_ct:
                continue
            print(f"{k:>5} |", end="")
            for ct in COMPOUND_TYPES:
                recs = by_ct.get(ct, [])
                if not recs:
                    print(f" {'--':>15}", end="")
                    continue
                is_ovf, is_tle, ok = check_flags(recs)
                if is_ovf:
                    print(f" {'OVF':>15}", end="")
                elif is_tle:
                    print(f" {'TLE':>15}", end="")
                elif ok:
                    correct = sum(1 for r in ok if r.get('correct'))
                    acc = 100 * correct / len(recs)
                    print(f" {acc:>14.0f}%", end="")
                else:
                    print(f" {'--':>15}", end="")
            print()
