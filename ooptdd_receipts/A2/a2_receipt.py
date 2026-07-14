"""Hermetic A2 receipt for the DB-shaped eigentrust provenance boundary."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_LKT = Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from server.contexts.tree.repository import internet_observations, normalize_node_row  # noqa: E402
from server.read_models import compute_tree_metrics  # noqa: E402


def _ev(cid, name, **attrs):
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatos.A2",
        "event": name,
        **attrs,
    }


def _raw_nodes(verdict_source):
    """Match TreeKgRepository rows: verdict_source is present even when its value is None."""
    return [
        dict(
            tag="root", verdict="canonical_stage", verdict_source=verdict_source,
            metric_value=1.0, metric_scope="s", parent=None, parents=[], parent_edges=[], questions=[]
        ),
        dict(
            tag="p1", verdict="progressive", verdict_source=verdict_source,
            metric_value=0.5, metric_scope="s", pred_baseline=1.0, pred_noise_band=0.02,
            pred_closes="q1", parent="root", parents=["root"],
            parent_edges=[dict(tag="root")], questions=[]
        ),
        dict(
            tag="top", verdict="CANONICAL", verdict_source=verdict_source,
            metric_value=0.4, metric_scope="s", parent="p1", parents=["p1"],
            parent_edges=[dict(tag="p1")], questions=[]
        ),
    ]


_OBS_ROWS = [
    dict(node="p1", payload=json.dumps({
        "url": "blog://x", "source_type": "blog", "corroboration_score": 0.5
    })),
    dict(node="p1", payload=json.dumps({
        "url": "peer://a", "source_type": "peer_reviewed", "corroboration_score": 0.9
    })),
]


def _metrics(verdict_source, *, include_observations=True):
    all_observations, node_source = internet_observations(_OBS_ROWS)
    nodes = [normalize_node_row(row) for row in _raw_nodes(verdict_source)]
    for row in nodes:
        if row["tag"] in node_source:
            row["source"] = node_source[row["tag"]]
    return compute_tree_metrics({
        "name": "a2_receipt",
        "nodes": nodes,
        "frontier": [],
        # Match the integration baseline: keep node→source binding, remove only the trust-map inputs.
        "observations": all_observations if include_observations else [],
    })


def verify(backend, cid):
    """Emit the positive provenance match and the explicit negative path-collapse oracle."""
    with_receipt = _metrics("engine")
    coverage = with_receipt["bayes"]["trust_coverage"]
    matched = int(coverage.get("path_sources_matched") or 0)
    if matched >= 1:
        backend.ship([_ev(
            cid, "trust_path_source_matched", count=matched,
            mode=coverage.get("mode"), map_supplied=coverage.get("map_supplied")
        )])

    baseline = _metrics("engine", include_observations=False)
    credence = with_receipt["bayes"]["canonical_credence"]
    baseline_credence = baseline["bayes"]["canonical_credence"]
    if credence is not None and baseline_credence is not None:
        delta = abs(float(credence) - float(baseline_credence))
        if delta > 0.05:
            backend.ship([_ev(
                cid, "canonical_credence_moved_by_eigentrust", count=1,
                canonical_credence=credence, baseline_credence=baseline_credence, delta=delta
            )])

    without_receipt = _metrics(None)
    missing_coverage = without_receipt["bayes"]["trust_coverage"]
    inconclusive = (without_receipt.get("provenance") or {}).get("inconclusive_progress") or []
    if int(missing_coverage.get("path_sources_matched") or 0) == 0 and inconclusive:
        backend.ship([_ev(
            cid, "canonical_path_collapsed_inconclusive",
            path_sources_matched=0, inconclusive_count=len(inconclusive),
            inconclusive=sorted(inconclusive)
        )])
    return {
        "matched_with_receipt": matched,
        "credence": credence,
        "baseline_credence": baseline_credence,
        "collapsed_without_receipt": sorted(inconclusive),
    }
