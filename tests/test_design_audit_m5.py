"""M5 design-audit guard: 재채점 락 원자화 — 동시 submit 이중채점 차단 (TOCTOU).

결함(감사 M5): submit_test_result 의 read(self.kg, vsrc 확인)와 write(self.kg_tx)가 별개 트랜잭션 →
사이에 끼어든 동시 submit 이 둘 다 vsrc=NULL 을 보고 통과해 이중채점. register_prediction 은 이미
원자 write-WHERE 가드(pred_registered_at IS NULL)가 있는데 submit 만 비일관.
수정: 판결 SET op 의 *첫 절* 을 원자 CAS 가드로 — WHERE (vsrc IS NULL OR vsrc<>'scripted') ... RETURN e.tag.
  단일 managed-write tx 안에서 동시 submit 중 한쪽만 SET 매칭 → 진 쪽은 0행(claimed 없음) → 409.
  claim 은 judge() 검증을 다 통과한 *뒤* 의 SET 이라, 거부되면 노드가 빈 scripted 로 잠기지 않는다.

이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 가 M5 를 progressive 로 자동 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as _TestResultIn  # noqa: N814 (pytest collection 회피)


_GUARD = "<> 'scripted'"   # 판결 SET op 의 원자 CAS WHERE 가드 식별 문자열


def _pred_kg(seen_queries):
    """vsrc=None 미채점 노드의 pred 읽기. 그 외 쿼리는 빈 결과."""
    def kg(q, **kw):
        seen_queries.append(q)
        if "RETURN e.pred_metric" in q:
            return [dict(m="p95", d="lower", b=0.5, nb=0.05, novel=None, vsrc=None,
                         nmet=None, ndir=None, nthr=None, psha=None,
                         closes=None, n_opened=0)]
        return []
    return kg


def _kg_tx(captured, *, claim_wins: bool):
    """원자 CAS 의 KG 트랜잭션 모킹 — per-op 결과 shape(len==ops). 첫 op(claim)이 이기면 [{tag}], 지면 []."""
    def kg_tx(ops):
        ops = list(ops)
        captured.append(ops)
        first = [{"claimed": "v"}] if claim_wins else []   # claim 0행 = 동시 submit 이 이미 점유
        return [first] + [[] for _ in ops[1:]]
    return kg_tx


def test_concurrent_submit_does_not_double_score():
    """원자 CAS claim 이 0행(동시 submit 이 이미 점유)이면 submit → 409. claim 승리 시 정상."""
    # ★행동적: claim 패배(첫 op 0행) → 409
    seen: list = []
    cap: list = []
    svc = JudgementService(kg=_pred_kg(seen), kg_tx=_kg_tx(cap, claim_wins=False),
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    with pytest.raises(HTTPException) as e:
        svc.submit_test_result("T", "v", _TestResultIn(metric_value=0.4, script="j.py"))
    assert e.value.status_code == 409

    # ★구조적(non-vacuous): 판결 SET op 가 WHERE vsrc<>'scripted' 원자가드를 *실제로* 포함
    set_cyphers = [c for ops in cap for (c, _) in ops if "e.verdict_source='scripted'" in c]
    assert set_cyphers, "판결 SET op 가 없음"
    assert _GUARD in set_cyphers[0], "판결 SET 에 WHERE vsrc<>'scripted' 원자 CAS 가드 누락 → TOCTOU 미봉쇄"
    assert "RETURN e.tag" in set_cyphers[0], "claim 결과를 읽을 RETURN e.tag 누락"

    # ★claim 승리(첫 op [{tag}]) → 정상 채점
    seen2: list = []
    cap2: list = []
    svc2 = JudgementService(kg=_pred_kg(seen2), kg_tx=_kg_tx(cap2, claim_wins=True),
                            hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)
    out = svc2.submit_test_result("T", "v", _TestResultIn(metric_value=0.4, script="j.py"))
    assert out["ok"] is True
    assert cap2, "claim 승리 후 kg_tx 가 상세를 채워야 함"


def test_claim_is_a_single_atomic_kg_tx_no_second_nonatomic_write():
    """원자성: 판결 SET(=claim) + PROV 가 단일 kg_tx — read↔write 분리 TOCTOU 가 닫혔다(2차 비원자 쓰기 없음)."""
    cap: list = []
    svc = JudgementService(kg=_pred_kg([]), kg_tx=_kg_tx(cap, claim_wins=True),
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    svc.submit_test_result("T", "v", _TestResultIn(metric_value=0.4, script="j.py"))
    assert len(cap) == 1, "판결+claim+PROV 가 단일 kg_tx 여야 함(별개 write 트랜잭션 없음)"
    cyphers = [c for c, _ in cap[0]]
    assert any("e.verdict_source='scripted'" in c and _GUARD in c for c in cyphers)
