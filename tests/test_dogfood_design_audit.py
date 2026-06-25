"""dogfood: 설계감사 프로그램이 엔진 규율을 지키는지 — verdict 손입력 0, judge 생성.

hermetic: 실 pytest 대신 합성 receipt 를 run(rc) 에 주입. guard 미착륙=정직한 pending,
착륙=judge 가 progressive 생성. 13 결함은 아직 안 고쳐졌으므로 실 receipt 는 전부 pending(가짜 green 0).
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

from examples.design_audit_20260625_programme import AUDIT_NODES, run

_H4_GUARD = "test_demote_canonical_protects_hard_core"


def _by_tag(rc):
    return {r["tag"]: r for r in run(rc)}


def test_all_findings_pending_when_no_guards_landed():
    """guard 0개(빈 receipt) → 13 결함 전부 pending(no-receipt), CLOSED 0 (가짜 green 금지)."""
    scored = [r for r in run({}) if r["status"] != "ROOT"]
    assert scored and all(r["verdict"] == "pending(no-receipt)" for r in scored)
    assert not any(r["status"] == "CLOSED" for r in scored)


def test_root_is_canonical_stage_not_scored():
    h = _by_tag({})["receipt_binding_hardcore"]
    assert h["verdict"] == "canonical_stage" and h["status"] == "ROOT"


def test_guard_landing_scores_progressive_from_receipt():
    """결함의 guard_test 가 green 으로 착륙 → judge 가 progressive 를 *생성*(개선+독립 novel)."""
    h4 = _by_tag({_H4_GUARD: True})["H4_demote_hardcore_unguarded"]
    assert h4["verdict"] == "progressive"
    assert h4["improved"] is True and h4["novel"] is True


def test_verdict_is_judge_generated_not_hand_entered():
    """guard 가 미통과(False)면 progressive 가 *안* 나온다 = judge 산출이지 손입력 아님."""
    h4 = _by_tag({_H4_GUARD: False})["H4_demote_hardcore_unguarded"]
    assert h4["verdict"] != "progressive"
    assert h4["novel"] is False


def test_novel_metric_is_independent_of_improvement_metric():
    """PROM-B: 각 결함의 novel metric != 개선 metric (독립 초과경험내용)."""
    for n in AUDIT_NODES:
        if n.prediction is not None and n.novel_target is not None:
            assert n.novel_target.metric_name != n.prediction.metric_name, n.tag


def test_no_literal_scored_verdict_assigned_in_source():
    import examples.design_audit_20260625_programme as mod
    src = open(mod.__file__, encoding="utf-8").read()
    for bad in ('verdict="progressive"', "verdict='progressive'",
                'verdict="rejected"', 'verdict="partial"', 'verdict="equivalent"'):
        assert bad not in src, f"손입력 verdict: {bad}"
