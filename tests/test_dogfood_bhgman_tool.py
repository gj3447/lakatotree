"""dogfood: bhgman_tool governance/audit 프로그램이 엔진 규율을 지키는지 — verdict 손입력 0, judge 생성.

hermetic: 실제 bhgman-tool subprocess oracle 대신 *합성 receipt* 를 monkeypatch 로 주입
(빠름·결정론·인프라 무관). 실 oracle(ABSOLUTE venv bhgman-tool)은 run() 이 직접 호출.
검증 대상은 judge() 배선: receipt → measured/novel 파생 → verdict 를 judge 가 *생성*(손입력 아님).
# KG: LakatosTree_BhgmanGovernance_20260624
"""
from __future__ import annotations

import examples.bhgman_tool_programme as mod

# 실 oracle 을 반영한 합성 receipt:
#   drift honest = 현재 KG↔code drift 436(passed=false) → 정직한 비진보 receipt.
#   lean green   = self-contained .lean closed-goal 8 + proof-checker exit-0(passed=true).
_DRIFT_HONEST = {"score": -436, "passed": False}            # measured drift count = 436
_LEAN_GREEN = {"score": 8.0, "passed": True}
_LEAN_CHECKER_FAIL = {"score": 8.0, "passed": False}        # count 8 이나 proof-checker exit!=0
_LEAN_TOOLCHAIN_FAIL = {"score": mod._LEAN_FAIL_SENTINEL, "passed": False}


def _run(monkeypatch, drift, lean, idem):
    """receipt 함수를 합성값으로 갈아끼우고 run() 실행 → {tag: row}. subprocess 미발생."""
    monkeypatch.setattr(mod, "drift_receipt", lambda: drift)
    monkeypatch.setattr(mod, "lean_receipt", lambda: lean)
    monkeypatch.setattr(mod, "drift_idempotent", lambda: idem)
    return {r["tag"]: r for r in mod.run()}


def test_root_is_canonical_stage_not_scored(monkeypatch):
    """하드코어 추측 루트(bhgman=거버넌스 substrate, NOT capability multiplier)는 채점 대상 아님."""
    out = _run(monkeypatch, _DRIFT_HONEST, _LEAN_GREEN, 1.0)
    assert out["hard_core"]["verdict"] == "canonical_stage"
    assert out["hard_core"]["status"] == "ROOT"


def test_lean_gate_scores_progressive_from_oracle_receipt(monkeypatch):
    """lean_proof_gate: closed-goal 8 + proof-checker exit-0 → judge 가 progressive 를 *생성*(novel 독립 확증)."""
    g = _run(monkeypatch, _DRIFT_HONEST, _LEAN_GREEN, 1.0)["lean_proof_gate"]
    assert g["verdict"] == "progressive", g
    assert g["status"] == "SCORED"
    assert g["improved"] is True
    assert g["novel"] is True            # proof_checker_exit0 (개선 metric closed_lean_goals 와 독립)


def test_drift_governance_honestly_non_progressive(monkeypatch):
    """★핵심 정직성: 현재 436 drift receipt 를 judge 가 *비진보*(rejected)로 채점 — 가짜 green 금지.

    capability-multiplier 를 대담한 예측으로 등록하지 않고, drift 가지는 자신의 oracle 이 반증한다."""
    d = _run(monkeypatch, _DRIFT_HONEST, _LEAN_GREEN, 1.0)["drift_governance"]
    assert d["status"] == "SCORED"
    assert d["verdict"] == "rejected"    # 436 > baseline 0 (lower=better) → 반증
    assert d["improved"] is False
    assert d["drift_count"] == 436
    assert d["oracle_passed"] is False   # bhgman 자신의 게이트가 정직하게 false


def test_pending_when_oracle_receipt_absent(monkeypatch):
    """oracle/인프라 미가용(receipt None) → pending(no-receipt). '영수증 없는 green 은 거짓말'.

    NaN/미가용을 judge 에 먹이지 않는다(숫자만 채점)."""
    out = _run(monkeypatch, None, None, None)
    for tag in ("drift_governance", "lean_proof_gate"):
        assert out[tag]["verdict"] == "pending(no-receipt)", out[tag]
        assert out[tag]["status"] == "PENDING"
        assert out[tag]["measured"] is None


def test_lean_toolchain_fail_is_pending_not_scored(monkeypatch):
    """lean 툴체인 부재(score=-1000 sentinel) → pending. sentinel/NaN 을 채점하지 않는다."""
    g = _run(monkeypatch, _DRIFT_HONEST, _LEAN_TOOLCHAIN_FAIL, 1.0)["lean_proof_gate"]
    assert g["verdict"] == "pending(no-receipt)"
    assert g["status"] == "PENDING"


def test_verdict_is_judge_generated_not_hand_entered(monkeypatch):
    """novel 가드 실패(proof-checker exit!=0)면 progressive 가 *안* 나온다 = judge 산출이지 손입력 아님.

    closed-goal count(8)는 개선됐지만 독립 novel(exit-0)이 미확증 → partial."""
    g = _run(monkeypatch, _DRIFT_HONEST, _LEAN_CHECKER_FAIL, 1.0)["lean_proof_gate"]
    assert g["verdict"] == "partial"     # 개선 O·novel X → progressive 아님
    assert g["improved"] is True
    assert g["novel"] is False


def test_novel_metric_is_independent_of_improvement_metric():
    """PROM-B 독립성: 각 가지의 novel metric != 개선 metric (독립 초과경험내용, 가짜 재활용 금지)."""
    for n in mod.GOV_NODES:
        if n.prediction is not None and n.novel_target is not None:
            assert n.novel_target.metric_name != n.prediction.metric_name, (
                f"{n.tag}: novel 이 개선과 같은 metric — 재활용(PROM-B 위반)")


def test_no_literal_scored_verdict_assigned_in_source():
    """소스에 scored verdict 문자열 손입력이 없다(judge 만 생성). 스테이지 라벨/산문은 예외."""
    src = open(mod.__file__, encoding="utf-8").read()
    for bad in ('verdict="progressive"', "verdict='progressive'",
                'verdict="rejected"', "verdict='rejected'",
                'verdict="partial"', 'verdict="equivalent"'):
        assert bad not in src, f"손입력 verdict 발견: {bad}"
