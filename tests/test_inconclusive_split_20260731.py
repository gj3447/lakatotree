"""Inconclusive green alert/reason split (engine upgrade 2026-07-31)."""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics


def test_inconclusive_reason_split_surfaces_client_asserted():
    nodes = [
        dict(tag="root", verdict="CANONICAL", parent=None, parents=[], parent_edges=[],
             verdict_source="admin"),
        # forceful scripted + receipt but client_asserted unverified → INCONCLUSIVE
        dict(tag="l0", verdict="progressive", parent="root", parents=["root"],
             parent_edges=[], verdict_source="scripted",
             current_receipt_sha="a" * 64,
             measurement_grade="client_asserted", replay_status="not_attempted",
             metric_value=1.0, pred_baseline=2.0),
        # forceful without receipt
        dict(tag="nr", verdict="progressive", parent="root", parents=["root"],
             parent_edges=[], verdict_source="scripted",
             current_receipt_sha="", metric_value=1.0, pred_baseline=2.0),
    ]
    m = tree_metrics(nodes, [])
    split = m["provenance"]["inconclusive_reason_split"]
    assert split["client_asserted_unverified"] >= 1
    assert split["forceful_without_receipt"] >= 1
    alert = next(a for a in m["alerts"] if "inconclusive" in a)
    assert "client_asserted_unverified" in alert
    assert "verdict_source 없이" not in alert  # old misleading phrase
