#!/usr/bin/env python3
"""(5) Per change-type per [LLM, k, agent]: avg metrics + OVF/TLE flags.

Covers all 10 change types: 6 single (fattree) + 4 compound.

Usage: python3 ch-llm-agent.py
"""
import json, os, sys
from collections import defaultdict
sys.path.insert(0, os.path.dirname(__file__))
from _common import compute_metrics

BASE = os.path.join(os.path.dirname(__file__), '..', 'logs', 'new_scale')
K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
ROUTERS = {4:20, 8:80, 12:180, 16:320, 20:500, 30:1125, 50:3125, 80:8000, 120:18000, 160:32000, 200:50000}

SINGLE_TYPES = ['local_preference', 'med', 'static_route', 'interface_shutdown', 'bgp_network', 'prefix_aggregation']
COMPOUND_TYPES = ['compound_lp_bgpnet', 'compound_lp_shutdown', 'compound_lp_static_shutdown', 'compound_lp_static_bgpnet_shutdown']
ALL_TYPES = SINGLE_TYPES + COMPOUND_TYPES

SHORT_NAMES = {
    'local_preference': 'LP', 'med': 'MED', 'static_route': 'Static',
    'interface_shutdown': 'Shut', 'bgp_network': 'BGPNet', 'prefix_aggregation': 'PfxAgg',
    'compound_lp_bgpnet': 'LP+Net', 'compound_lp_shutdown': 'LP+Shut',
    'compound_lp_static_shutdown': 'LP+St+Shut', 'compound_lp_static_bgpnet_shutdown': 'LP+St+Net+Shut',
}

def load_records_by_ct(exp_dir, k, method, model_key):
    """Returns {change_type: [records]}"""
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

def find_exp_dir(prefix, model_key):
    for d in sorted(os.listdir(BASE)):
        if d.lower().startswith(f'{prefix}_{model_key}_'.lower()) and not d.startswith('resume'):
            return os.path.join(BASE, d)
    return None

MODELS = [('gpt-5.4', 'GPT-5.4'), ('gpt-4o', 'GPT-4o'),
          ('o3', 'o3'), ('DeepSeek-V4-Pro', 'DeepSeek-V4-Pro'),
          ('Qwen', 'Qwen-3.5-397B'), ('Llama', 'Llama-3.3-70B')]

if __name__ == '__main__':
    all_results = {}
    for model_key, model_name in MODELS:
        ft_dir = find_exp_dir('fattree', model_key)
        cp_dir = find_exp_dir('compound', model_key)

        # Print fattree single-change accuracy
        if ft_dir:
            print(f"\n{'='*120}")
            print(f"Fattree {model_name} — agent_skills accuracy by single-change type")
            print(f"{'='*120}")
            print(f"{'k':>4}", end='')
            for ct in SINGLE_TYPES:
                print(f"  {SHORT_NAMES[ct]:>10}", end='')
            print()
            for k in K_VALUES:
                by_ct = load_records_by_ct(ft_dir, k, 'agent_skills', model_key)
                if not by_ct: continue
                print(f"{k:>4}", end='')
                for ct in SINGLE_TYPES:
                    recs = by_ct.get(ct, [])
                    if not recs:
                        print(f"  {'--':>10}", end='')
                        continue
                    m = compute_metrics(recs)
                    if m['flag']:
                        print(f"  {m['flag']:>10}", end='')
                    else:
                        print(f"  {m['acc']:>9.1f}%", end='')
                print()

        # Print compound accuracy
        if cp_dir:
            print(f"\nCompound {model_name} — agent_skills accuracy by compound-change type")
            print(f"{'='*120}")
            print(f"{'k':>4}", end='')
            for ct in COMPOUND_TYPES:
                print(f"  {SHORT_NAMES[ct]:>15}", end='')
            print()
            for k in K_VALUES:
                by_ct = load_records_by_ct(cp_dir, k, 'agent_skills', model_key)
                if not by_ct: continue
                print(f"{k:>4}", end='')
                for ct in COMPOUND_TYPES:
                    recs = by_ct.get(ct, [])
                    if not recs:
                        print(f"  {'--':>15}", end='')
                        continue
                    m = compute_metrics(recs)
                    if m['flag']:
                        print(f"  {m['flag']:>15}", end='')
                    else:
                        print(f"  {m['acc']:>14.1f}%", end='')
                print()

        # Save full metrics
        results = {}
        for prefix, ct_list in [('fattree', SINGLE_TYPES), ('compound', COMPOUND_TYPES)]:
            ed = ft_dir if prefix == 'fattree' else cp_dir
            if not ed: continue
            for k in K_VALUES:
                by_ct = load_records_by_ct(ed, k, 'agent_skills', model_key)
                for ct in ct_list:
                    recs = by_ct.get(ct, [])
                    if not recs: continue
                    m = compute_metrics(recs)
                    results.setdefault(ct, {})[str(k)] = m
        all_results[model_key] = results

    out_path = os.path.join(os.path.dirname(__file__), 'ch_llm_agent_results.json')
    with open(out_path, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {out_path}")
