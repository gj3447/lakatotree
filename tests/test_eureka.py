"""EUREKA detector — felt vs true vs hallucinated.

Pins the core finding (prom eureka-red-blue 2026-06-18): a felt aha is not a true one;
a felt aha with no external receipt is a hallucination (the ~37% false-insight finding
made executable). Red is an asymmetric downstream filter — it can veto, never originate.
"""
from __future__ import annotations

from lakatos.eureka import (
    BF_SUBSTANTIAL,
    _node_to_eureka_input,
    classify,
    eureka_over_tree,
    eureka_rate,
)

# a real lakatotree tree node (server repository/read_models shape) that is a
# measurement-grade true eureka: a confirmed novel prediction, strong effect, net closure.
_TREE_NODE = {
    "tag": "v8_frozen", "verdict": "progressive",
    "novel_registered": True, "novel_confirmed": True,
    "metric_value": 12.0, "pred_baseline": 2.0, "pred_noise_band": 0.1,
    "pred_closes": ["q1", "q2", "q3"], "questions": ["q4"], "source_trust": 1.0,
}

_TRUE = {
    "novel_registered": True, "novel_confirmed": True, "verdict": "progressive",
    "delta": 10.0, "noise_band": 0.1, "source_trust": 1.0,
    "closed": 3, "opened": 1, "stands": True, "reproducible": True,
}


def test_true_eureka_passes_every_red_gate():
    v = classify(_TRUE)
    assert v.felt and v.true and not v.hallucinated
    assert v.reasons == () and v.bf > BF_SUBSTANTIAL and v.balance > 0


def test_felt_but_unconfirmed_is_hallucinated():
    # the decisive case: a bold novel conjecture (blue flash) that was never externally
    # confirmed — feels like eureka, is a hallucination (the human 37%).
    node = {**_TRUE, "novel_confirmed": False}
    v = classify(node)
    assert v.felt and not v.true and v.hallucinated
    assert "novel_unconfirmed" in v.reasons


def test_no_novel_prediction_is_not_even_felt():
    v = classify({"novel_registered": False, "verdict": "progressive"})
    assert not v.felt and not v.true and not v.hallucinated
    assert v.reasons == ("no_novel_prediction",)


def test_marginal_evidence_blocks_true_eureka():
    # confirmed + felt, but the evidence is only marginal (weak delta) -> not true.
    node = {**_TRUE, "delta": 0.05, "noise_band": 1.0}
    v = classify(node)
    assert v.felt and not v.true and v.hallucinated
    assert any(r.startswith("bf_marginal") for r in v.reasons)
    assert v.bf <= BF_SUBSTANTIAL


def test_negative_problem_balance_blocks_true_eureka():
    # the conjecture closed fewer problems than it opened -> excuses breeding problems.
    node = {**_TRUE, "closed": 1, "opened": 3}
    v = classify(node)
    assert v.hallucinated and any(r.startswith("problem_balance") for r in v.reasons)


def test_promotion_gate_veto_blocks_true_eureka():
    # unresolved doubt (stands=False) -> red gate vetoes even a confirmed novel hit.
    node = {**_TRUE, "stands": False}
    v = classify(node)
    assert v.hallucinated and "unresolved_doubt" in v.reasons


def test_rejected_verdict_is_never_true_eureka():
    node = {**_TRUE, "verdict": "rejected"}
    v = classify(node)
    assert v.hallucinated  # rejected is not promotable + BF<1


def test_eureka_rate_measures_true_over_felt():
    nodes = [
        _TRUE,                                   # true
        {**_TRUE, "novel_confirmed": False},     # hallucinated
        {**_TRUE, "stands": False},              # hallucinated
        {"novel_registered": False},             # not felt (excluded from denominator)
    ]
    r = eureka_rate(nodes)
    assert r["felt"] == 3 and r["true"] == 1 and r["hallucinated"] == 2
    assert r["true_rate"] == round(1 / 3, 3)
    assert r["hallucination_rate"] == round(2 / 3, 3)


# ── eureka over real tree nodes (measurement-grade, standing excluded) ────────
def test_node_to_input_derives_delta_and_balance_from_real_fields():
    inp = _node_to_eureka_input(_TREE_NODE)
    assert inp["delta"] == 10.0          # metric_value - pred_baseline (judge convention)
    assert inp["noise_band"] == 0.1
    assert inp["closed"] == 3 and inp["opened"] == 1   # |pred_closes| vs |questions|
    assert "stands" not in inp and "reproducible" not in inp  # standing is not a node field


def test_tree_node_is_measurement_true_eureka():
    # confirmed novel + strong effect + net closure, NO standing field needed.
    v = classify(_node_to_eureka_input(_TREE_NODE), require_promotion=False)
    assert v.felt and v.true and not v.hallucinated
    assert v.bf > BF_SUBSTANTIAL and v.balance > 0


def test_require_promotion_false_drops_the_standing_gate():
    # the same input that is true without promotion is hallucinated WITH it (no stands).
    inp = _node_to_eureka_input(_TREE_NODE)
    assert classify(inp, require_promotion=False).true is True
    assert classify(inp, require_promotion=True).true is False  # promotion vetoes (no stands)


def test_unconfirmed_tree_node_is_hallucinated():
    node = {**_TREE_NODE, "novel_confirmed": False}
    v = classify(_node_to_eureka_input(node), require_promotion=False)
    assert v.felt and not v.true and "novel_unconfirmed" in v.reasons


def test_marginal_effect_tree_node_blocked():
    # confirmed but the result barely moved off baseline -> marginal evidence -> not true.
    node = {**_TREE_NODE, "metric_value": 2.05, "pred_noise_band": 1.0}  # delta 0.05
    v = classify(_node_to_eureka_input(node), require_promotion=False)
    assert not v.true and any(r.startswith("bf_marginal") for r in v.reasons)


def test_eureka_over_tree_aggregates_and_flags_measurement_grade():
    nodes = [
        _TREE_NODE,                                   # true
        {**_TREE_NODE, "novel_confirmed": False},     # hallucinated
        {"tag": "x", "novel_registered": False},      # not felt
    ]
    r = eureka_over_tree(nodes)
    assert r["measurement_grade"] is True
    assert r["felt"] == 2 and r["true"] == 1 and r["hallucinated"] == 1
    assert r["true_rate"] == 0.5
