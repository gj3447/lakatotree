"""programme_appraisal dual-layer on tree_metrics (prom dual-layer vocab)."""
from __future__ import annotations

from lakatos.quant.metrics import tree_metrics


def test_programme_appraisal_unappraised_when_fewer_than_two_series_steps():
    nodes = [
        dict(tag="a", verdict="proof", parents=[], parent_edges=[]),
        dict(tag="b", verdict="CANONICAL", parent="a", parents=["a"], parent_edges=[],
             verdict_source="admin"),
    ]
    m = tree_metrics(nodes, [])
    pa = m["programme_appraisal"]
    assert pa["promotion_authority"] is False
    assert pa["status"] == "UNAPPRAISED"
    assert pa["steps"] < 2


def test_programme_appraisal_progressive_on_clean_progressive_path():
    # path needs CANONICAL head; series uses ≥2 progressive steps (CANONICAL is off-axis for series)
    nodes = [
        dict(tag="r", verdict="progressive", parents=[], parent_edges=[],
             verdict_source="scripted", current_receipt_sha="a" * 64,
             problem_balance_delta=0),
        dict(tag="m", verdict="progressive", parent="r", parents=["r"], parent_edges=[],
             verdict_source="scripted", current_receipt_sha="b" * 64,
             problem_balance_delta=0),
        dict(tag="h", verdict="CANONICAL", parent="m", parents=["m"], parent_edges=[],
             verdict_source="admin"),
    ]
    m = tree_metrics(nodes, [])
    pa = m["programme_appraisal"]
    assert pa["status"] == "PROGRESSIVE"
    assert pa["steps"] >= 2
    assert pa["authority"] == "diagnostic_only"
