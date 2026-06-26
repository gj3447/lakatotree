"""OOPTDD emit-adapter — LakatoTree 설계감사 M6(사후예측 잠금)을 *구조화 이벤트 trace*(R02)로 영수증화.

결함(감사 M6): register_prediction 이 미채점 노드면 무조건 pred_* SET → 측정값 보고 prediction 재맞춤 가능.
수정: SET 의 WHERE 에 e.pred_registered_at IS NULL 추가 → 이미 등록된 노드 재등록은 0행 → 409.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만. verify 가 실제
server.contexts.tree.judgement_service.JudgementService.register_prediction 를 *구동*(재구현 금지)하고,
관측한 사실을 구조화 이벤트로 ship. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

tests/test_design_audit_m6.py 의 픽스처/패턴(fake kg, _judge, 재등록 시 [] 반환)을 그대로 차용.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from fastapi import HTTPException  # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import PredictionIn  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M6", "event": name, **attrs}


def _judge(kg):
    # tests/test_design_audit_m6.py::_judge 와 동일 — 실제 JudgementService 생성자 구동.
    return JudgementService(
        kg=kg,
        kg_tx=lambda ops: [[{"ok": 1}] for _ in ops],
        hist=lambda *a: None,
        foundation=lambda *a, **k: None,
        reproducible_for_node=lambda *a, **k: None,
    )


def verify(backend, cid):
    """M6 사후예측 잠금 구동 — 실제 register_prediction 경로가
    (1) 측정 후 재등록(re-tune)을 409 로 차단하고
    (2) 그 차단이 동어반복 아니라 SET 쿼리의 pred_registered_at IS NULL 잠금절에서 비롯하며(non-vacuous)
    (3) 미등록 새 노드의 첫 등록은 막지 않음(과잉차단 회귀가드 = 음성 오라클)을 구조화 이벤트로 증언."""

    # ── (A) 행동적 양성 + non-vacuous 구조 검사 ──
    # tests/test_design_audit_m6.py::test_prediction_locked_rejects_post_measurement_edit 와 동일 픽스처.
    queries: list = []
    state = {"registered": False}

    def kg(query, **k):
        queries.append(query)
        if "RETURN t.ontology AS ontology" in query:
            return [{"ontology": None}]            # 온톨로지 미선언 → metric 강제 skip
        if "SET e.pred_metric" in query:
            if state["registered"]:
                return []                          # 이미 등록 → 잠금절이 0행 → 409 경로
            state["registered"] = True
            return [{"tag": "n"}]
        return []

    svc = _judge(kg)
    out = svc.register_prediction("T", "n", PredictionIn(metric_name="m", baseline_value=1.0))
    assert out["ok"] is True, out

    # non-vacuous: 실제 SET 쿼리가 사후수정 잠금절을 *문자열로* 포함해야 한다.
    #   결함(수정 없는) 코드라면 이 절이 부재 → assert 폭발 → 영수증 RED. (음성 오라클#1)
    set_q = next(q for q in queries if "SET e.pred_metric" in q)
    assert "pred_registered_at IS NULL" in set_q, "M6 잠금절 부재 — 사후예측 재맞춤 가능(결함 미수정)"

    # 행동적: 같은 노드 재등록(측정 후 re-tune) → 실제 코드가 HTTPException(409) raise.
    blocked = False
    status = None
    try:
        svc.register_prediction("T", "n", PredictionIn(metric_name="m", baseline_value=0.0))
    except HTTPException as exc:
        blocked = True
        status = exc.status_code
    assert blocked and status == 409, f"재등록이 409 로 차단되지 않음 (blocked={blocked} status={status})"
    backend.ship([_ev(cid, "post_hoc_registration_blocked",
                      status_code=status, lock_clause="pred_registered_at IS NULL",
                      lock_clause_present=True)])

    # ── (B) 음성 오라클#2 — 과잉차단 회귀가드 ──
    # test_register_on_fresh_unregistered_node_still_ok 와 동일: 잠금이 *첫* 등록을 막지 않는다.
    #   만약 잠금이 무조건 모든 등록을 막는(과잉) 결함이라면 여기서 ok 가 아님 → 영수증 RED.
    def kg_fresh(query, **k):
        if "RETURN t.ontology AS ontology" in query:
            return [{"ontology": None}]
        if "SET e.pred_metric" in query:
            return [{"tag": "fresh"}]              # 미등록 새 노드 → 1행 등록 성공
        return []

    fresh = _judge(kg_fresh).register_prediction(
        "T", "fresh", PredictionIn(metric_name="m", baseline_value=1.0))
    assert fresh["ok"] is True, fresh
    backend.ship([_ev(cid, "fresh_registration_allowed", ok=True)])
