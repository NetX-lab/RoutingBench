#!/usr/bin/env python3
"""Shared utilities for all extraction scripts.

Definitions:
- A record is OVF if status=='ok' AND context_overflow=True (runtime-detected pre-call),
  OR if the error message indicates context overflow (substrings: 'maximum context',
  'context length', 'too large', '413'). The bare context_overflow=True flag is
  unreliable on error records (often set with unrelated errors like missing files).
- A record is TLE if status=='ok' AND runtime_s>=3600 AND not OVF.
- Silent failures: status=='ok' but token_consumption==0 (e.g., empty API response).
  Counted as wrong in acc but excluded from token/time/rounds averages; do NOT trigger scope-OVF.
- Other errors (missing files, transient API errors not about context): excluded from
  the valid set; still count toward the accuracy denominator.
- A scope is OVF if >25% records are OVF.
- A scope is TLE if not OVF and >25% records are TLE.

Policy when scope is NOT flagged:
- OVF individual records: count as wrong in accuracy; excluded from token/time/rounds averages.
- TLE individual records: count as NORMAL case (included in accuracy and all averages).
- Silent failures and other errors: count as wrong in accuracy; excluded from averages.
"""
import json, os
from collections import defaultdict

OVF_THRESH = 0.25
TLE_THRESH = 3600  # seconds

_OVF_KEYWORDS = (
    'maximum context', 'context length', 'too large', '413',
    'input tokens exceed',  # OpenAI: "Input tokens exceed the configured limit..."
    "longer than the model's context",  # vLLM/Llama: "input is longer than the model's context length"
)

def _err_indicates_ovf(r):
    err = (r.get('error') or '') + ' ' + (r.get('error_message') or '')
    err_lc = err.lower()
    return any(kw in err_lc for kw in _OVF_KEYWORDS)

def is_record_ovf(r):
    # Explicit context_overflow status (set by the runner when it detects OVF)
    if r.get('status') == 'context_overflow':
        return True
    # Trust the boolean flag only when status reports a normal completion
    if r.get('status') == 'ok' and r.get('context_overflow', False):
        return True
    # Otherwise, rely on error-message keyword matching (covers status='error')
    if _err_indicates_ovf(r):
        return True
    return False

def is_record_tle(r):
    if is_record_ovf(r):
        return False
    return r.get('status') == 'ok' and r.get('runtime_s', 0) >= TLE_THRESH

def scope_flag(recs):
    """Return 'OVF', 'TLE', or '' for this scope."""
    if not recs:
        return 'EMPTY'
    n = len(recs)
    n_ovf = sum(1 for r in recs if is_record_ovf(r))
    if n_ovf / n > OVF_THRESH:
        return 'OVF'
    n_tle = sum(1 for r in recs if is_record_tle(r))
    if n_tle / n > OVF_THRESH:
        return 'TLE'
    return ''

def compute_metrics(recs):
    """Compute metrics for a scope.
    Returns: dict with flag/n_total/n_valid/acc/tok/llm_t/tot_t/rllm/rtool, or None if empty.

    Policy (when scope NOT flagged OVF/TLE):
    - OVF individual records: counted as wrong in acc; excluded from token/time/rounds averages.
    - TLE individual records: counted as normal — included in acc (correct/incorrect)
      AND in token/time/rounds averages.
    """
    if not recs:
        return None
    n_total = len(recs)
    flag = scope_flag(recs)

    # Accuracy: correct = ok & correct & !OVF (TLE records counted normally based on .correct)
    n_correct = sum(1 for r in recs
                    if r.get('status') == 'ok'
                    and r.get('correct')
                    and not is_record_ovf(r))
    acc = 100 * n_correct / n_total

    # Other metrics: over ok & !OVF & has-tokens records (TLE included as normal,
    # silent failures with token=0 excluded)
    valid = [r for r in recs
             if r.get('status') == 'ok'
             and not is_record_ovf(r)
             and r.get('token_consumption', 0) > 0]
    n_valid = len(valid)
    if n_valid > 0:
        avg_tok = sum(r['token_consumption'] for r in valid) / n_valid
        avg_llm = sum(r.get('llm_time_s', 0) for r in valid) / n_valid
        avg_tot = sum(r.get('runtime_s', 0) for r in valid) / n_valid
        avg_rllm = sum(r.get('rounds', 0) for r in valid) / n_valid
        avg_rtool = sum(r.get('tool_calls', 0) for r in valid) / n_valid
    else:
        avg_tok = avg_llm = avg_tot = avg_rllm = avg_rtool = 0

    return {
        'flag': flag,  # '' / 'OVF' / 'TLE'
        'n_total': n_total,
        'n_valid': n_valid,
        'acc': acc,
        'tok': avg_tok,
        'llm_t': avg_llm,
        'tot_t': avg_tot,
        'rllm': avg_rllm,
        'rtool': avg_rtool,
    }
