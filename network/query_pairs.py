"""Helpers for loading user-specified RoutingBench query pairs."""

from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple

Endpoint = Tuple[int, int]
QueryPair = Tuple[Endpoint, Endpoint]

_EDGE_RE = re.compile(r"^(?:dc(?P<dc>\d+)-)?edge-p(?P<pod>\d+)-e(?P<edge>\d+)$")


def load_query_pairs(path: str, k: int, topology: str) -> List[QueryPair]:
    """Load and validate query pairs for a topology.

    The JSON file may be either a list of pairs or an object with topology keys,
    for example ``{"fattree": [...], "crossdc": [...]}``.  Each pair may use
    ``src_edge``/``dst_edge`` (or ``src``/``dst``) fields with either
    ``[pod, edge]`` values or endpoint names such as ``edge-p0-e0`` and
    ``dc0-edge-p0-e0``.
    """
    with open(path) as file_obj:
        raw = json.load(file_obj)

    specs = _select_specs(raw, topology)
    if not isinstance(specs, list):
        raise ValueError("pairs file must contain a list of query pairs")

    pairs = [_parse_pair(spec, k, topology) for spec in specs]
    if not pairs:
        raise ValueError("pairs file did not contain any query pairs")
    return pairs


def _select_specs(raw: Any, topology: str) -> Any:
    if isinstance(raw, dict):
        if topology in raw:
            return raw[topology]
        for key in ("pairs", "query_pairs"):
            if key in raw:
                return raw[key]
    return raw


def _parse_pair(spec: Any, k: int, topology: str) -> QueryPair:
    if isinstance(spec, dict):
        src = _first_present(spec, ("src_edge", "src", "S"))
        dst = _first_present(spec, ("dst_edge", "dst", "D"))
    elif isinstance(spec, list) and len(spec) == 2:
        src, dst = spec
    else:
        raise ValueError(f"invalid query pair entry: {spec!r}")

    if topology == "crossdc":
        src_edge = _parse_endpoint(src, k, "src_edge", expected_dc=0)
        dst_edge = _parse_endpoint(dst, k, "dst_edge", expected_dc=1)
    else:
        src_edge = _parse_endpoint(src, k, "src_edge")
        dst_edge = _parse_endpoint(dst, k, "dst_edge")
        if src_edge[0] == dst_edge[0]:
            raise ValueError(f"{topology} query pairs must be inter-pod: {spec!r}")
    return src_edge, dst_edge


def _first_present(spec: dict, keys: Tuple[str, ...]) -> Any:
    for key in keys:
        if key in spec:
            return spec[key]
    raise ValueError(f"query pair is missing one of {keys}: {spec!r}")


def _parse_endpoint(value: Any, k: int, field: str, expected_dc: Optional[int] = None) -> Endpoint:
    dc = None
    if isinstance(value, str):
        match = _EDGE_RE.match(value)
        if not match:
            raise ValueError(f"{field} must be an edge endpoint name, got {value!r}")
        if match.group("dc") is not None:
            dc = int(match.group("dc"))
        pod = int(match.group("pod"))
        edge = int(match.group("edge"))
    elif isinstance(value, list) and len(value) in (2, 3):
        if len(value) == 3:
            dc, pod, edge = value
        else:
            pod, edge = value
        pod = int(pod)
        edge = int(edge)
        dc = None if dc is None else int(dc)
    else:
        raise ValueError(f"{field} must be [pod, edge], [dc, pod, edge], or endpoint name")

    if expected_dc is not None and dc is not None and dc != expected_dc:
        raise ValueError(f"{field} must be in dc{expected_dc}, got dc{dc}")
    half = k // 2
    if not (0 <= pod < k and 0 <= edge < half):
        raise ValueError(f"{field} endpoint out of range for k={k}: pod={pod}, edge={edge}")
    return pod, edge