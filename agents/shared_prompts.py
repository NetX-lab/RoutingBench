"""Shared prompt components — loaded from markdown files."""
import os, json

_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Map topology name → system prompt file
_PROMPT_FILES = {
    "fattree": "system_prompt.md",
    "crossdc": "system_prompt_crossdc.md",
    "compound": "system_prompt_compound.md",
}

def load_system_prompt(topology="fattree"):
    fname = _PROMPT_FILES.get(topology, "system_prompt.md")
    with open(os.path.join(_AGENTS_DIR, fname)) as f:
        return f.read()

def load_agent_md(method_name):
    path = os.path.join(_AGENTS_DIR, method_name, "AGENT.md")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""

SYSTEM_PROMPT = load_system_prompt("fattree")

def format_query(src_edge, dst_edge, dst_prefix, src_dc=None, dst_dc=None):
    sp, se = src_edge; dp, de = dst_edge
    if src_dc is not None and dst_dc is not None:
        return (f"Source: dc{src_dc}-edge-p{sp}-e{se}, "
                f"Destination: dc{dst_dc}-edge-p{dp}-e{de}, Prefix: {dst_prefix}")
    return f"Source: edge-p{sp}-e{se}, Destination: edge-p{dp}-e{de}, Prefix: {dst_prefix}"

def format_change(change_diffs):
    parts = []
    for d in change_diffs:
        parts.append(f"On device {d['device']}:")
        for line in d["add_lines"]:
            parts.append(f"  + {line}")
        if d.get("description"):
            parts.append(f"  Purpose: {d['description']}")
    return "\n".join(parts)
