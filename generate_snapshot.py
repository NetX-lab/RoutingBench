#!/usr/bin/env python3
"""One-shot snapshot generator for RoutingBench.

Generates every snapshot, change file, and ground-truth label for
``fattree``, ``crossdc``, and ``compound`` topologies at the configured
scales. The output is written to ``data/<topology>/<topology>k<NNN>/``.

Each instance's ``before_path`` / ``after_path`` ground truth is computed
**analytically** from the topology generator's path-selection model — the
data pipeline does not require any external simulator.

Usage examples
--------------
    # Generate every default scale of every topology (this is what the
    # paper's evaluation uses).
    python generate_snapshot.py

    # Pick a subset.
    python generate_snapshot.py --topologies fattree crossdc --k 4 8 12

    # Per-instance counts (default: 20 source/dest pairs, 5 changes each).
    python generate_snapshot.py --num-pairs 20 --num-changes 5
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback

# Make sibling generators importable when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEFAULT_K = [4, 8, 12, 16, 20, 30, 50, 80, 120, 160, 200]
TOPOLOGY_CHOICES = ["fattree", "crossdc", "compound"]


def _gen_fattree(k: int, num_pairs: int, num_changes: int, *, ipv6: bool = False,
                 pairs=None) -> None:
    if ipv6:
        # IPv6 widening (paper Sec.~3.2): produce only the base configs;
        # the change generators continue to use the IPv4 path by default.
        from network.AddressingV6 import generate_configs_v6
        generate_configs_v6(k)
        return

    from network.IntraDCNet import generate_advanced_configs
    from network.TopoBase import generate_configs

    base = f"data/fattree/fattreek{str(k).zfill(3)}"
    if not os.path.exists(os.path.join(base, "configs")):
        generate_configs(k)
    generate_advanced_configs(k, num_pairs, num_changes, pairs=pairs)


def _gen_crossdc(k: int, num_pairs: int, num_changes: int, *, pairs=None) -> None:
    from network.InterDCNet import generate_crossdc, generate_crossdc_changes

    base = f"data/crossdc/crossdck{str(k).zfill(3)}"
    if not os.path.exists(os.path.join(base, "example_layer1_topology.json")):
        generate_crossdc(k)
    generate_crossdc_changes(k, num_pairs, num_changes, pairs=pairs)


def _gen_compound(k: int, num_pairs: int, num_changes: int, *, pairs=None) -> None:
    from network.CompoundNet import generate_compound_configs

    generate_compound_configs(k, num_pairs, num_changes, pairs=pairs)


_GENERATORS = {
    "fattree": _gen_fattree,
    "crossdc": _gen_crossdc,
    "compound": _gen_compound,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topologies", nargs="+", choices=TOPOLOGY_CHOICES,
                        default=TOPOLOGY_CHOICES,
                        help="Which topology families to generate (default: all three).")
    parser.add_argument("--k", nargs="+", type=int, default=DEFAULT_K,
                        help=f"k values to generate (default: {DEFAULT_K}).")
    parser.add_argument("--num-pairs", type=int, default=20,
                        help="Source/destination edge pairs per change type (default: 20).")
    parser.add_argument("--num-changes", type=int, default=5,
                        help="Distinct change instances per pair (default: 5).")
    parser.add_argument("--pairs-file",
                        help="JSON file with user-specified query pairs. The file may be a list "
                             "or an object keyed by topology name.")
    parser.add_argument("--ipv6", action="store_true",
                        help="Use the IPv6 addressing scheme for fattree base "
                             "configs (each index field widened to two bytes; "
                             "required for k > 256). Outputs to "
                             "data/fattree_v6/. Only fattree is supported.")
    args = parser.parse_args()

    if args.ipv6 and args.topologies != ["fattree"]:
        print("[INFO] --ipv6 only applies to fattree; restricting to fattree.")
        args.topologies = ["fattree"]

    pairs_file = os.path.abspath(args.pairs_file) if args.pairs_file else None
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 70)
    print(f"RoutingBench snapshot generation")
    print(f"  topologies : {args.topologies}")
    print(f"  k values   : {args.k}")
    print(f"  pairs/type : {args.num_pairs}")
    print(f"  changes    : {args.num_changes}")
    if pairs_file:
        print(f"  pairs file : {pairs_file}")
    print("=" * 70)

    failures: list[tuple[str, int, str]] = []
    for topo in args.topologies:
        for k in args.k:
            if k % 2 != 0 or k < 4:
                print(f"[SKIP] {topo} k={k} (k must be even and >= 4)")
                continue
            t0 = time.time()
            print(f"\n--- {topo} k={k} ---", flush=True)
            try:
                pairs = None
                if pairs_file:
                    from network.query_pairs import load_query_pairs
                    pairs = load_query_pairs(pairs_file, k, topo)
                if topo == "fattree" and args.ipv6:
                    _gen_fattree(k, args.num_pairs, args.num_changes, ipv6=True)
                else:
                    _GENERATORS[topo](k, args.num_pairs, args.num_changes, pairs=pairs)
                print(f"[OK] {topo} k={k} done in {time.time() - t0:.1f}s", flush=True)
            except Exception as e:
                print(f"[ERROR] {topo} k={k}: {e}", flush=True)
                traceback.print_exc()
                failures.append((topo, k, str(e)))

    print("\n" + "=" * 70)
    if failures:
        print(f"FAILED: {len(failures)} configurations")
        for topo, k, err in failures:
            print(f"  {topo} k={k}: {err}")
        sys.exit(1)
    print("All requested snapshots generated successfully.")


if __name__ == "__main__":
    main()
