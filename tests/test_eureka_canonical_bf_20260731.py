"""Engine upgrade 2026-07-31: CANONICAL keeps progressive BF on Eureka axis.

Promoting progressive@L2 to CANONICAL must not zero path eureka (BF default 1.0).
"""
from __future__ import annotations

from lakatos.eureka import classify, eureka_over_tree, eureka_verdict
from lakatos.quant.bayes import BF_BASE, bayes_factor
from lakatos.quant.metrics import tree_metrics


def test_eureka_verdict_maps_canonical_to_progressive():
    assert eureka_verdict("CANONICAL") == "progressive"
    assert eureka_verdict("progressive_unverified") == "progressive"
    assert eureka_verdict("former_canonical") == "progressive"
    assert eureka_verdict("rejected") == "rejected"


def test_former_canonical_keeps_progressive_bf_after_demotion():
    """Later promote demotes prior head to former_canonical — eureka BF must not collapse."""
    node = dict(
        novel_registered=True,
        novel_confirmed=True,
        verdict="former_canonical",
        delta=-12.0,
        noise_band=0.0,
        source_trust=1.0,
        closed=1,
        opened=0,
    )
    ev = classify(node, require_promotion=False)
    assert ev.true is True, ev.reasons
    assert ev.bf == bayes_factor("progressive", delta=-12.0, noise_band=0.0)


def test_missing_pred_baseline_is_inconclusive_not_bf_marginal():
    """Path early nodes without pred_baseline must not fake delta=0 → bf_marginal."""
    from lakatos.eureka import _node_to_eureka_input
    row = dict(
        novel_registered=True, novel_confirmed=True, verdict="former_canonical",
        metric_value=62.0, pred_baseline=None, pred_noise_band=None,
        closed_question_count=0, questions=[], source_trust=1.0,
    )
    inp = _node_to_eureka_input(row)
    assert inp["measurement_absent"] is True
    ev = classify(inp, require_promotion=False)
    assert ev.felt is True
    assert ev.inconclusive is True
    assert ev.hallucinated is False
    assert not any(str(r).startswith("bf_marginal") for r in ev.reasons)


def test_canonical_with_novel_closure_can_be_true_eureka():
    """CANONICAL head with measurement delta + novel + closed question → true."""
    # classify() reads noise_band/delta keys (eureka input shape), not pred_*.
    node = dict(
        novel_registered=True,
        novel_confirmed=True,
        verdict="CANONICAL",
        delta=-12.0,
        noise_band=0.0,
        source_trust=1.0,
        closed=1,
        opened=0,
    )
    ev = classify(node, require_promotion=False)
    assert ev.felt is True
    assert ev.true is True, ev.reasons
    assert ev.bf == bayes_factor("progressive", delta=-12.0, noise_band=0.0)
    assert ev.bf >= BF_BASE["progressive"] * 0.5


def test_path_metrics_true_eureka_with_canonical_l2_head():
    """tree_metrics eureka.true_rate > 0 when path ends in measured CANONICAL."""
    nodes = [
        dict(tag="root", verdict="former_canonical", parent=None, parents=[],
             parent_edges=[], metric_value=None, novel_registered=False),
        dict(tag="head", verdict="CANONICAL", parent="root", parents=["root"],
             parent_edges=[], metric_value=0.0, pred_baseline=12.0,
             pred_noise_band=0.0, pred_direction="lower",
             novel_registered=True, novel_confirmed=True,
             verdict_source="scripted", current_receipt_sha="a" * 64,
             measurement_grade="server_regenerated", replay_status="verified",
             source_trust=1.0, closed_question_count=1, questions=[],
             pred_closes="q-x"),
    ]
    frontier = [dict(name="q-x", status="CLOSED", closed_by=["head"], body="")]
    m = tree_metrics(nodes, frontier)
    assert m["canonical"] == "head"
    assert m["eureka"]["true"] >= 1
    assert m["eureka"]["true_rate"] > 0


def test_progress_prefers_head_metric_name_over_legacy_count():
    """Head metric_name (unreceipted_closes) wins over longer legacy tests series."""
    nodes = [
        dict(tag="a", verdict="former_canonical", parent=None, parents=[],
             parent_edges=[], metric_value=62.0, metric_scope="count",
             metric_name="tests", pred_direction="higher", verdict_source="admin"),
        dict(tag="b", verdict="former_canonical", parent="a", parents=["a"],
             parent_edges=[], metric_value=100.0, metric_scope="count",
             metric_name="tests", pred_direction="higher", verdict_source="admin"),
        dict(tag="c", verdict="progressive", parent="b", parents=["b"],
             parent_edges=[], metric_value=12.0, metric_name="unreceipted_closes",
             pred_direction="lower", pred_baseline=12.0,
             verdict_source="scripted", current_receipt_sha="b" * 64,
             measurement_grade="server_regenerated", replay_status="verified"),
        dict(tag="d", verdict="CANONICAL", parent="c", parents=["c"],
             parent_edges=[], metric_value=0.0, metric_name="unreceipted_closes",
             pred_direction="lower", pred_baseline=12.0,
             verdict_source="scripted", current_receipt_sha="c" * 64,
             measurement_grade="server_regenerated", replay_status="verified",
             novel_registered=True, novel_confirmed=True,
             closed_question_count=1, questions=[]),
    ]
    m = tree_metrics(nodes, [])
    prog = m["progress"]
    assert prog is not None
    assert prog["scope"] == "unreceipted_closes"
    assert prog["direction"] == "lower"
    assert prog["improvement_pct"] == 100.0  # 12 → 0 lower = full improvement
