"""Shared configuration loader.

Reads the top-level ``config.yaml`` once and exposes typed accessors. All
runtime entry points should obtain configuration from here so that paths,
the LLM model registry, and evaluation defaults stay in sync across scripts.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config.yaml"

_lock = threading.Lock()
_cache = None


def repo_root() -> Path:
    return _REPO_ROOT


def config_path() -> Path:
    return _CONFIG_PATH


def load_config() -> dict:
    """Return the parsed top-level config.yaml (cached)."""
    global _cache
    with _lock:
        if _cache is None:
            if _CONFIG_PATH.exists():
                with open(_CONFIG_PATH) as f:
                    _cache = yaml.safe_load(f) or {}
            else:
                _cache = {}
    return _cache


def get(*keys, default=None):
    """Walk a dotted path through the config dict; missing keys -> default."""
    cur = load_config()
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def get_path(*keys, default=None) -> Path:
    """Resolve a config path to an absolute pathlib.Path under repo_root()."""
    val = get(*keys, default=default)
    if val is None:
        return _REPO_ROOT
    p = Path(val).expanduser()
    if not p.is_absolute():
        p = (_REPO_ROOT / p).resolve()
    return p
