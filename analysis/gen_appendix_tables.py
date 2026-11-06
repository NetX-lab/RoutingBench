#!/usr/bin/env python3
"""Generate LaTeX appendix tables from extraction script outputs.

Generates 12 tables:
- 6 tables: per-LLM 3-method comparison on fattree (1 per LLM)
- 2 tables: cross-DC 3-method comparison (gpt-5.4, gpt-4o)
- 2 tables: compound 3-method comparison (gpt-5.4, gpt-4o)
- 2 tables: per change-type accuracy (gpt-5.4, gpt-4o on fattree+compound)
"""
import json, os
sys = __import__('sys')
sys.path.insert(0, os.path.dirname(__file__))

RESULT_DIR = os.path.dirname(__file__)
ROUTERS = {4:20, 8:80, 12:180, 16:320, 20:500, 30:1125, 50:3125, 80:8000, 120:18000, 160:32000, 200:50000}
def xdc_routers(k):
    return 2 * (5 * k * k // 4) + 2 * k

K_VALUES = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
METHODS = ['in_context_learning', 'iterative_reasoning', 'agent_skills']
METHOD_NAMES = {'in_context_learning': '\\methodnaive{}', 'iterative_reasoning': '\\methodmulti{}', 'agent_skills': '\\methodagent{}'}

def fmt_cell(m):
    """Format metric cell for table."""
    if m is None:
        return '--'
    flag = m.get('flag', '')
    if flag == 'OVF':
        return 'OVF'
    if flag == 'TLE':
        return 'TLE'
    return f"{m['acc']:.0f}\\% & {m['tok']/1000:.0f}K & {m['llm_t']:.0f}s & {m['tot_t']:.0f}s & {m['rllm']:.1f} & {m['rtool']:.1f}"

def empty_cell():
    return '-- & -- & -- & -- & -- & --'

def gen_three_method_table(results, label_suffix, caption, label, routers_fn=lambda k: ROUTERS.get(k,0)):
    """Generate 3-method comparison table for one LLM/topology.

    Three-line table style: \\toprule / \\midrule (under sub-headers) / \\bottomrule only.
    For each method column, show data only up to (and including) the first scale that
    triggers OVF/TLE. Below that, leave cells blank (no '--').
    """
    # Determine for each method, the cutoff k (first k where the column terminates: OVF, TLE,
    # or a scope-level operational failure with n_valid=0). After that, leave blank.
    # Cells AT the cutoff itself: 'OVF'/'TLE' get a labelled multicolumn; pure operational
    # failure gets blank (no labels, since it's not a real benchmark outcome).
    cutoff = {}  # method -> idx of first failing row in K_LIST (inclusive)
    cutoff_kind = {}  # 'OVF' | 'TLE' | 'EXP'  (EXP = experimental error, render blank)
    K_LIST = [k for k in K_VALUES if (str(k) in results or k in results)]
    for m in METHODS:
        cutoff[m] = None
        cutoff_kind[m] = None
        for i, k in enumerate(K_LIST):
            kd = results.get(str(k), results.get(k, {}))
            cell = kd.get(m)
            if cell is None:
                continue
            flag = cell.get('flag', '')
            if flag == 'OVF':
                cutoff[m] = i; cutoff_kind[m] = 'OVF'; break
            if flag == 'TLE':
                cutoff[m] = i; cutoff_kind[m] = 'TLE'; break
            if cell.get('n_valid', 0) == 0:
                cutoff[m] = i; cutoff_kind[m] = 'EXP'; break

    out = []
    out.append(r"\begin{table}[H]")
    out.append(r"\centering")
    out.append(r"\caption{" + caption + "}")
    out.append(r"\label{" + label + "}")
    out.append(r"\scriptsize")
    out.append(r"\setlength{\tabcolsep}{2.5pt}")
    out.append(r"\resizebox{\textwidth}{!}{%")
    # Add visual gap (~10pt) between the three method groups
    out.append(r"\begin{tabular}{@{}ll" + "rrrrrr" + r"!{\hspace{10pt}}" + "rrrrrr" + r"!{\hspace{10pt}}" + "rrrrrr" + r"@{}}")
    out.append(r"\toprule")
    # Method-name header row (bold, no numbering), no \cmidrule below
    method_hdrs = []
    for m in METHODS:
        method_hdrs.append(r" & \multicolumn{6}{c}{\textbf{" + METHOD_NAMES[m] + r"}}")
    out.append(r"$k$ & Routers" + "".join(method_hdrs) + r" \\")
    # Sub-header row (Acc/Tok/...) directly without rule between
    sub = []
    for _ in METHODS:
        sub.append(r" & Acc & Tok & $t_\mathrm{LLM}$ & $t_\mathrm{Run}$ & $R_\mathrm{LLM}$ & $R_\mathrm{Tool}$")
    out.append(r"~ & ~" + "".join(sub) + r" \\")
    out.append(r"\midrule")

    for i, k in enumerate(K_LIST):
        kdata = results.get(str(k), results.get(k, {}))
        row = [f"{k}", f"{routers_fn(k):,}"]
        for m in METHODS:
            cut = cutoff[m]
            kind = cutoff_kind[m]
            # Cells past cutoff: blank
            if cut is not None and i > cut:
                row.append(' & '.join(['']*6))
                continue
            # Cell AT cutoff: render label or blank depending on kind
            if cut is not None and i == cut:
                if kind == 'OVF':
                    row.append(r"\multicolumn{6}{c}{Context Window Overflow}")
                elif kind == 'TLE':
                    row.append(r"\multicolumn{6}{c}{Time Limit Exceeded}")
                else:  # EXP
                    row.append(' & '.join(['']*6))
                continue
            # Before cutoff or no cutoff: render normal data
            cell = kdata.get(m)
            if cell is None:
                row.append(empty_cell())
                continue
            row.append(f"{cell['acc']:.0f}\\% & {cell['tok']/1000:.0f}K & {cell['llm_t']:.0f}s & {cell['tot_t']:.0f}s & {cell['rllm']:.1f} & {cell['rtool']:.1f}")
        out.append(" & ".join(row) + r" \\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}}")
    out.append(r"\end{table}")
    return "\n".join(out)

def gen_change_type_table(results, model_name, label):
    """Generate per-change-type table for one LLM."""
    SINGLE = ['local_preference','med','static_route','interface_shutdown','bgp_network','prefix_aggregation']
    COMP = ['compound_lp_bgpnet','compound_lp_shutdown','compound_lp_static_shutdown','compound_lp_static_bgpnet_shutdown']
    SHORT = {
        'local_preference':'LP','med':'MED','static_route':'Static',
        'interface_shutdown':'Shut','bgp_network':'BGP Net','prefix_aggregation':'Pfx Agg',
        'compound_lp_bgpnet':'LP+Net','compound_lp_shutdown':'LP+Shut',
        'compound_lp_static_shutdown':'LP+St+Shut','compound_lp_static_bgpnet_shutdown':'LP+St+Net+Shut',
    }
    all_types = SINGLE + COMP

    out = []
    out.append(r"\begin{table}[H]")
    out.append(r"\centering")
    out.append(r"\caption{\methodagent{} (" + model_name + r") accuracy by change type on fattree (single) and compound topologies.}")
    out.append(r"\label{" + label + "}")
    out.append(r"\scriptsize")
    out.append(r"\resizebox{\textwidth}{!}{%")
    out.append(r"\begin{tabular}{@{}ll" + "r"*len(all_types) + r"@{}}")
    out.append(r"\toprule")
    out.append(r"$k$ & Routers")
    for ct in all_types:
        out.append(f" & {SHORT[ct]}")
    out.append(r" \\")
    out.append(r"\midrule")
    for k in K_VALUES:
        ks = str(k)
        row = [f"{k}", f"{ROUTERS.get(k,0):,}"]
        any_data = False
        for ct in all_types:
            if ct in results and ks in results[ct]:
                m = results[ct][ks]
                flag = m.get('flag', '')
                if flag == 'OVF':
                    row.append('OVF')
                elif flag == 'TLE':
                    row.append('TLE')
                else:
                    row.append(f"{m['acc']:.0f}\\%")
                any_data = True
            else:
                row.append('--')
        if any_data:
            out.append(" & ".join(row) + r" \\")
    out.append(r"\bottomrule")
    out.append(r"\end{tabular}}")
    out.append(r"\end{table}")
    return "\n".join(out)

if __name__ == '__main__':
    out_path = os.path.join(RESULT_DIR, 'appendix_tables.tex')
    with open(out_path, 'w') as f:
        # 1. Per-LLM 3-method tables on fattree
        with open(os.path.join(RESULT_DIR, 'ft_llm_agent_results.json')) as fr:
            ft = json.load(fr)
        for mk, mn in [('gpt-5.4','GPT-5.4'),('gpt-4o','GPT-4o'),('o3','o3'),
                       ('DeepSeek-V4-Pro','DeepSeek-V4-Pro'),('Qwen','Qwen-3.5-397B'),('Llama','Llama-3.3-70B')]:
            if mk not in ft: continue
            cap_name = 'OpenAI o3' if mn == 'o3' else mn
            cap = f"Three-agent comparison on single-DC fat-tree with {cap_name} across all scales."
            lab = f"tab:app-ft-{mk.lower().replace('.','-')}"
            f.write(gen_three_method_table(ft[mk], mk, cap, lab) + "\n\n")

        # 2. Cross-DC 3-method tables
        with open(os.path.join(RESULT_DIR, 'xdc_llm_agent_results.json')) as fr:
            xd = json.load(fr)
        for mk, mn in [('gpt-5.4','GPT-5.4'),('gpt-4o','GPT-4o')]:
            if mk not in xd: continue
            cap = f"Three-agent comparison on cross-DC with {mn} across all scales."
            lab = f"tab:app-xdc-{mk.lower().replace('.','-')}"
            f.write(gen_three_method_table(xd[mk], mk, cap, lab, routers_fn=xdc_routers) + "\n\n")

        # 3. Compound 3-method tables
        with open(os.path.join(RESULT_DIR, 'cp_llm_agent_results.json')) as fr:
            cp = json.load(fr)
        for mk, mn in [('gpt-5.4','GPT-5.4'),('gpt-4o','GPT-4o')]:
            if mk not in cp: continue
            cap = f"Three-agent comparison on compound changes with {mn} across all scales."
            lab = f"tab:app-cp-{mk.lower().replace('.','-')}"
            f.write(gen_three_method_table(cp[mk], mk, cap, lab) + "\n\n")

        # 4. Per change-type tables: omitted from the appendix (kept in JSON only)

    print(f"Saved appendix tables to {out_path}")
