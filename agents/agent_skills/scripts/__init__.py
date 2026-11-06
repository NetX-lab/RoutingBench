"""Shared utilities for all tool scripts."""
import os, re, json, threading

# Thread-local storage for config overlay (after-change state)
_tls = threading.local()


def set_overlay(overlay_dict):
    """Set per-thread config overlay. overlay_dict maps device_name -> modified cfg content."""
    _tls.overlay = overlay_dict


def clear_overlay():
    """Clear per-thread config overlay."""
    _tls.overlay = None


def load_cfg(before_dir, device):
    """Load a device's config. Supports:
    - {device}.cfg file (Arista EOS)
    - {device}/frr.conf (FRR config in directory)
    - {device}/config_db.json (SONiC config in directory)
    If overlay is set and device is in it, return overlay content.
    """
    overlay = getattr(_tls, 'overlay', None)
    if overlay and device in overlay:
        return overlay[device]
    configs_dir = os.path.join(before_dir, "configs")
    # Try .cfg file first
    cfg_path = os.path.join(configs_dir, f"{device}.cfg")
    if os.path.isfile(cfg_path):
        with open(cfg_path) as f:
            return f.read()
    # Try directory with frr.conf
    dev_dir = os.path.join(configs_dir, device)
    if os.path.isdir(dev_dir):
        frr_path = os.path.join(dev_dir, "frr.conf")
        if os.path.isfile(frr_path):
            with open(frr_path) as f:
                return f.read()
    return None


_topo_cache = {}


def load_topo(before_dir):
    """Load topology JSON (cached per before_dir)."""
    p = os.path.join(before_dir, "example_layer1_topology.json")
    if p in _topo_cache:
        return _topo_cache[p]
    if os.path.exists(p):
        with open(p) as f:
            topo = json.load(f)
        _topo_cache[p] = topo
        return topo
    return None
