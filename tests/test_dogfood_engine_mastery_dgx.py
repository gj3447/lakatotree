"""dogfood: engine-mastery DGX(vLLM 흡수) 프로그램이 엔진 규율을 지키는지 — verdict 손입력 0, judge 생성.

hermetic: 실제 디스크 로그/GitHub 대신 *합성 Receipt* 를 run() 에 주입(빠름·결정론·네트워크 무관).
실 영수증 경로(vLLM /metrics 로그 + GitHub Actions check-runs)는 register_to_server() 가 쓴다.
# KG: LakatosTree_EngineMastery_Absorption_20260618
"""
from __future__ import annotations

from examples.engine_mastery_dgx_programme import NODES, Receipt, run

# 실제 외부 영수증을 반영한 합성값: saturation peak=24, preempt=0, CI all-green=1.0,
# LB 최대 동시 OK=32, reset 카운트=0.
_GREEN = Receipt(sat_peak=24.0, sat_preempt=0.0, ci_green=1.0, lb_ok=32.0, lb_resets=0.0)


def _by_tag(rc):
    return {r["tag"]: r for r in run(rc)}


def test_absorption_branches_score_progressive_from_external_receipt():
    """saturation·lb 가지는 judge 가 외부 영수증에서 progressive 를 *생성* (novel 독립 확증)."""
    out = _by_tag(_GREEN)
    for tag in ("vllm-continuous-batching-saturation", "vllm-lb-backlog-ceiling"):
        assert out[tag]["verdict"] == "progressive", out[tag]
        assert out[tag]["novel"] is True
        assert out[tag]["improved"] is True
        assert out[tag].get("retroactive") is True   # post-hoc 정직 표기 보존


def test_root_is_canonical_stage_not_scored():
    """하드코어 추측 루트는 채점 대상 아님(canonical_stage) — 진보성 손입력 금지."""
    out = _by_tag(_GREEN)
    assert out["vllm-absorption-hardcore"]["verdict"] == "canonical_stage"
    assert out["vllm-absorption-hardcore"]["status"] == "ROOT"


def test_pending_when_external_receipt_absent():
    """외부 store 부재(로그/CI 없음) → pending(no-receipt). '영수증 없는 green 은 거짓말'."""
    out = _by_tag(Receipt(sat_peak=None, sat_preempt=None, ci_green=None,
                          lb_ok=None, lb_resets=None))
    for tag in ("vllm-continuous-batching-saturation", "vllm-lb-backlog-ceiling"):
        assert out[tag]["verdict"] == "pending(no-receipt)", out[tag]
        assert out[tag]["status"] == "PENDING"


def test_verdict_is_judge_generated_not_hand_entered():
    """novel 가드 실패(CI 미green 또는 preempt>0)면 progressive 가 *안* 나온다 = judge 산출이지 손입력 아님."""
    # CI 가 전부 green 이 아니거나 preemption 발생 → saturation novel 미확증
    rc = Receipt(sat_peak=24.0, sat_preempt=5.0, ci_green=0.0, lb_ok=32.0, lb_resets=0.0)
    out = _by_tag(rc)
    sat = out["vllm-continuous-batching-saturation"]
    assert sat["verdict"] != "progressive"   # 개선됐어도 독립 novel 미확증 → partial
    assert sat["novel"] is False
    # LB 가지: reset 이 생기면 novel(=reset 0) 미확증
    rc2 = Receipt(sat_peak=24.0, sat_preempt=0.0, ci_green=1.0, lb_ok=32.0, lb_resets=3.0)
    lb = _by_tag(rc2)["vllm-lb-backlog-ceiling"]
    assert lb["verdict"] != "progressive"
    assert lb["novel"] is False


def test_novel_metric_is_independent_of_improvement_metric():
    """PROM-B 독립성: novel metric != 개선 metric (독립 초과경험내용; 가짜 재활용 금지)."""
    for n in NODES:
        if n.prediction is not None and n.novel_target is not None:
            assert n.novel_target.metric_name != n.prediction.metric_name, (
                f"{n.tag}: novel 이 개선과 같은 metric — 재활용(PROM-B 위반)")


def test_no_literal_scored_verdict_assigned_in_source():
    """소스에 scored verdict 문자열 손입력이 없다(judge 만 생성). 표시/critique 문자열은 예외."""
    import examples.engine_mastery_dgx_programme as mod
    src = open(mod.__file__, encoding="utf-8").read()
    for bad in ('verdict="progressive"', "verdict='progressive'",
                'verdict="rejected"', 'verdict="partial"'):
        assert bad not in src, f"손입력 verdict 발견: {bad}"
