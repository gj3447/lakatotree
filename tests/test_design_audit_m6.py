"""M6 design-audit guard: 사후예측 잠금 — 등록된 prediction 은 채점 전 *재등록*(re-tune)이 막힌다.

결함(감사 M6): register_prediction 이 미채점 노드면 무조건 pred_* SET → 측정값 보고 prediction 재맞춤 가능.
수정: WHERE 에 e.pred_registered_at IS NULL 추가 → 재등록은 0행 → 기존 409. (judge.py 의 dead
PredictionLocked 정신을 서버 경로에 강제.)
이 guard 가 green 으로 착륙하면 examples/design_audit_20260625_programme.py 가 M6 를 progressive 로 자동 채점.
# KG: span_lakatotree_design_audit_20260625
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn


def _judge(kg):
    return JudgementService(kg=kg, kg_tx=lambda ops: [[{"ok": 1}] for _ in ops],
                            hist=lambda *a: None,
                            foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


def test_prediction_locked_rejects_post_measurement_edit():
    queries: list = []
    state = {"registered": False}

    def kg(query, **k):
        queries.append(query)
        if "RETURN t.ontology AS ontology" in query:
            return [{"ontology": None}]              # 온톨로지 미선언 → metric 강제 skip
        if "SET e.pred_metric" in query:
            # 새 WHERE(pred_registered_at IS NULL) 의 의미를 모킹: 이미 등록됐으면 0행
            if state["registered"]:
                return []
            state["registered"] = True
            return [{"tag": "n"}]
        return []

    svc = _judge(kg)
    out = svc.register_prediction("T", "n", PredictionIn(metric_name="m", baseline_value=1.0))
    assert out["ok"] is True

    # ★구조적(non-vacuous): register SET 쿼리가 사후수정 잠금절을 *실제로* 포함해야 한다 (수정 없으면 RED)
    set_q = next(q for q in queries if "SET e.pred_metric" in q)
    assert "pred_registered_at IS NULL" in set_q

    # ★행동적: 같은 노드 재등록(측정 후 re-tune) → 409
    with pytest.raises(HTTPException) as e:
        svc.register_prediction("T", "n", PredictionIn(metric_name="m", baseline_value=0.0))
    assert e.value.status_code == 409


def test_register_on_fresh_unregistered_node_still_ok():
    """과잉차단 회귀가드: 미등록 새 노드는 정상 등록(잠금이 첫 등록을 막지 않는다)."""
    def kg(query, **k):
        if "RETURN t.ontology AS ontology" in query:
            return [{"ontology": None}]
        if "SET e.pred_metric" in query:
            return [{"tag": "fresh"}]
        return []
    assert _judge(kg).register_prediction("T", "fresh", PredictionIn(metric_name="m", baseline_value=1.0))["ok"] is True
