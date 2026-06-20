"""dogfood: prom-honesty 프로그램이 엔진 규율을 지키는지 — verdict 손입력 0, judge 가 생성.

hermetic: 실제 subprocess receipt 대신 *합성 receipt* 를 run() 에 주입(빠름·결정론).
# KG: span_lakatotree_prom_honesty_dogfood / LakatosTree_PromHonesty_20260620
"""
from __future__ import annotations

from examples.prom_honesty_programme import NODES, run

# 닫힌 가지(A/B)의 guard + threat 테스트가 전부 PASSED 인 합성 receipt. 열린 가지 guard 는 *부재*.
_GREEN = {
    # promA
    "test_writer_add_node_byconstruction_rejects_scored": True,        # guard
    "test_add_node_rejects_every_scored_verdict_422": True,            # threat: rejects_every_scored
    "test_writer_upsert_nodes_byconstruction_rejects_scored": True,    # threat: byconstruction_rejects
    "test_set_verdict_403_on_scripted_verdict": True,                  # threat: set_verdict_403
    # promB
    "test_same_metric_same_measurement_is_not_novel": True,            # guard
    "test_independent_metric_is_progressive": True,                    # threat
}


def _by_tag(rc):
    return {r["tag"]: r for r in run(rc)}


def test_done_branches_score_progressive_from_receipt():
    """A·B 는 judge 가 receipt 에서 progressive 를 *생성* (novel 독립 확증)."""
    out = _by_tag(_GREEN)
    for tag in ("promA_node_gating", "promB_novel_independence"):
        assert out[tag]["verdict"] == "progressive", out[tag]
        assert out[tag]["novel"] is True
        assert out[tag]["open_gap"] == 0


def test_open_branches_are_honestly_pending():
    """열린 가지는 guard_test 가 receipt 에 없으므로 pending — '영수증 없는 green 은 거짓말'."""
    out = _by_tag(_GREEN)
    for tag in ("sha_provenance", "promC_oo_roundtrip", "promD_doc_honesty",
                "db_boundary", "longinus_grounding"):
        assert out[tag]["verdict"].startswith("pending"), out[tag]
        assert out[tag]["status"] == "OPEN"


def test_verdict_is_judge_generated_not_hand_entered():
    """guard 가 실패하면(novel 미확증) progressive 가 *안* 나온다 = verdict 는 judge 산출이지 손입력 아님."""
    rc = dict(_GREEN)
    rc["test_writer_add_node_byconstruction_rejects_scored"] = False   # A guard 실패
    out = _by_tag(rc)
    assert out["promA_node_gating"]["verdict"] != "progressive"
    assert out["promA_node_gating"]["novel"] is False                  # 독립 novel 미확증


def test_dogfoods_prom_b_novel_independence():
    """이 프로그램 자체가 PROM-B 를 지킨다: novel metric ≠ 예측 metric (독립 초과경험내용)."""
    for n in NODES:
        if n.prediction is not None and n.novel_target is not None:
            assert n.novel_target.metric_name != n.prediction.metric_name, (
                f"{n.tag}: novel 이 예측과 같은 metric — 재활용(PROM-B 위반)")


def test_no_literal_scored_verdict_assigned_in_source():
    """소스에 scored verdict 문자열 손입력이 없다(judge 만 생성). 루트/표시문자열은 예외."""
    import examples.prom_honesty_programme as mod
    src = open(mod.__file__, encoding="utf-8").read()
    for bad in ('verdict="progressive"', "verdict='progressive'",
                'verdict="rejected"', 'verdict="partial"'):
        assert bad not in src, f"손입력 verdict 발견: {bad}"
