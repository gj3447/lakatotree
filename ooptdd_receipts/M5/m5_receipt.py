"""OOPTDD emit-adapter — LakatoTree 설계감사 M5(재채점 락 원자화 / TOCTOU) 를 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만 — 엔진
server/contexts/tree/judgement_service.py 는 불변. verify 가 *실제* JudgementService.submit_test_result 의
M5 원자 CAS claim 경로를 구동(재구현 금지)하고 관측한 사실을 구조화 이벤트로 ship.
Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트("concurrent_rescore_blocked")를 낸다.

결함(감사 M5)이 있었다면 틀릴 음성 오라클: 동시 submit 으로 원자 CAS claim 이 0행(상대가 이미 점유)일 때,
M5 가드가 *없으면* submit 은 409 를 던지지 않고 조용히 이중채점한다. 그래서 '동시 submit → claim 0행 → 409'
의 *실관측* 자체가 결함 부재 증거다. test_design_audit_m5.py 의 픽스처/패턴을 그대로 차용.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from fastapi import HTTPException                                    # noqa: E402
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import TestResultIn               # noqa: E402


_GUARD = "<> 'scripted'"   # 판결 SET op 의 원자 CAS WHERE 가드 식별 문자열(test_design_audit_m5._GUARD 와 동일)


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.M5", "event": name, **attrs}


def _pred_kg(seen_queries):
    """vsrc=None 미채점 노드의 pred 읽기(test_design_audit_m5._pred_kg 와 동일). 그 외 쿼리는 빈 결과."""
    def kg(q, **kw):
        seen_queries.append(q)
        if "RETURN e.pred_metric" in q:
            return [dict(m="p95", d="lower", b=0.5, nb=0.05, novel=None, vsrc=None,
                         nmet=None, ndir=None, nthr=None, psha=None,
                         closes=None, n_opened=0)]
        return []
    return kg


def _kg_tx(captured, *, claim_wins):
    """원자 CAS 의 KG 트랜잭션 모킹(test_design_audit_m5._kg_tx 와 동일) — per-op 결과 shape(len==ops).
    첫 op(claim)이 이기면 [{tag}], 지면 [] → 동시 submit 이 이미 점유."""
    def kg_tx(ops):
        ops = list(ops)
        captured.append(ops)
        first = [{"claimed": "v"}] if claim_wins else []
        return [first] + [[] for _ in ops[1:]]
    return kg_tx


def _svc(kg, kg_tx):
    return JudgementService(kg=kg, kg_tx=kg_tx,
                            hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                            reproducible_for_node=lambda *a, **k: None)


def verify(backend, cid):
    """M5 원자 CAS 재채점 락 구동 — 실제 JudgementService.submit_test_result 를 호출.

    (1) 음성 오라클(결함이 있었다면 틀릴 케이스): 동시 submit 으로 첫 op(가드된 판결 SET claim)이 0행이면
        submit 이 409 를 던져야 한다 — M5 가드 부재면 던지지 않고 이중채점. raise 를 잡아 이 사실을 ship.
    (2) 구조적 비-vacuous: 판결 SET op 의 cypher 가 WHERE vsrc<>'scripted' 원자 CAS 가드 + RETURN e.tag 를
        *실제로* 포함하는지(빈 채점·동어반복 SET 이 아님)를 확인해 ship.
    (3) 양성 대조: claim 승리(첫 op [{tag}])면 정상 채점(ok=True) + 단일 kg_tx(별개 비원자 write 없음)."""
    # (1) ── 음성 오라클: claim 패배(첫 op 0행) → 409 "동시/재채점 차단". M5 가드 부재면 여기서 raise 안 됨.
    seen, cap = [], []
    svc = _svc(_pred_kg(seen), _kg_tx(cap, claim_wins=False))
    blocked_status = None
    try:
        svc.submit_test_result("T", "v", TestResultIn(metric_value=0.4, script="j.py"))
    except HTTPException as e:
        blocked_status = e.status_code   # HTTPException 직접 raise → .status_code
    if blocked_status is None:
        # raise 가 안 났다 = M5 결함 재발(이중채점). no-fake-green: 명시 실패.
        raise AssertionError("동시 submit claim 0행인데 409 가 안 났다 — M5 원자 CAS 가드 부재(이중채점 재발)")
    assert blocked_status == 409, f"동시 submit 차단은 409 여야 함, got {blocked_status}"
    backend.ship([_ev(cid, "concurrent_rescore_blocked", status=409,
                      mode="claim_lost_zero_rows", node="v")])

    # (2) ── 구조적 비-vacuous 오라클: 판결 SET op 가 원자 CAS WHERE 가드 + RETURN e.tag 를 실제 포함.
    set_cyphers = [c for ops in cap for (c, _) in ops if "e.verdict_source='scripted'" in c]
    assert set_cyphers, "판결 SET op 가 없음 — kg_tx 에 판결 쓰기가 도달 안 함"
    set_op = set_cyphers[0]
    assert _GUARD in set_op, "판결 SET 에 WHERE vsrc<>'scripted' 원자 CAS 가드 누락 → TOCTOU 미봉쇄"
    assert "RETURN e.tag" in set_op, "claim 결과(claimed)를 읽을 RETURN e.tag 누락 → 0행 판정 불가"
    backend.ship([_ev(cid, "atomic_cas_guard_present", guard=_GUARD, returns_claim="RETURN e.tag")])

    # (3) ── 양성 대조: claim 승리(첫 op [{tag}]) → 정상 채점 ok=True, 단일 kg_tx(2차 비원자 write 없음).
    seen2, cap2 = [], []
    svc2 = _svc(_pred_kg(seen2), _kg_tx(cap2, claim_wins=True))
    out = svc2.submit_test_result("T", "v", TestResultIn(metric_value=0.4, script="j.py"))
    assert out["ok"] is True, out
    assert len(cap2) == 1, "판결+claim+PROV 가 단일 kg_tx 여야 함(별개 write 트랜잭션 없음)"
    backend.ship([_ev(cid, "atomic_claim_won_scored", ok=True,
                      verdict=out.get("verdict"), single_tx=True)])
