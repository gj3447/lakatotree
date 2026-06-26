"""OOPTDD emit-adapter — LakatoTree 설계감사 H2(human CANONICAL floor 영수증) 를 *구조화 이벤트 trace*(R02)로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만(엔진 server/contexts/tree/judgement_service.py 는 불변).
verify 가 실제 JudgementService.set_verdict(서버측 human-floor 게이트) 를 *구동*(재구현 금지)하고, 관측한 사실을
구조화 이벤트로 ship. Longinus 바인딩(R10): 이 emit site(verify)가 must_emit 이벤트를 낸다.

결함(감사 H2)이 살아있었다면: client v.human_verdict=True 한 비트만으로 영수증 0(internal·재현성 None·human
Argument 없음) 노드가 CANONICAL floor 를 열었을 것 — 그럼 아래 음성 오라클(args=[] → 409)이 실패한다.
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from fastapi import HTTPException  # noqa: E402  (ooptdd-loop env 에 설치됨)
from server.contexts.tree.judgement_service import JudgementService  # noqa: E402
from server.contexts.tree.schemas import VerdictIn  # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.H2", "event": name, **attrs}


def _svc(args):
    """test_design_audit_h2 의 fake kg/kg_tx 픽스처를 그대로 차용.
    internal proof 노드(인터넷관측 0 → credibility None, reproducible None) + 주어진 Argument 목록(args)."""
    def kg(q, **kw):
        if "HAS_RESEARCH_EVENT" in q:                       # 인터넷 관측 없음 → internal 노드
            return []
        if "OPTIONAL MATCH (cur)-[:HAS_ARGUMENT]" in q:     # set_verdict pre-query
            return [dict(verdict="proof", verdict_source=None, source_trust=None,
                         novel_confirmed=False, args=args)]
        if "RETURN e.tag AS tag" in q:                      # promotion 후 최종 read (노드 존재)
            return [dict(tag="n")]
        return []
    return JudgementService(kg=kg, kg_tx=lambda ops: None, hist=lambda *a, **k: None,
                            foundation=lambda n: None,               # foundation 게이트 생략
                            reproducible_for_node=lambda n, t: None)  # 재현성 영수증 없음


def _canon():
    return VerdictIn(verdict="CANONICAL", human_verdict=True, valid_until_rebutted=True)


def verify(backend, cid):
    """H2 human-floor 구동 — 실제 set_verdict 가 (1) human Argument 없으면 client bit True 여도 차단(409),
    (2) 실제 human attestation Argument 있으면 CANONICAL 승격 통과."""

    # (음성 오라클) 영수증 0(internal·재현성 None·human Argument 없음) + client human_verdict=True
    #   → floor 가 client 1비트를 영수증으로 믿으면(H2 결함) 통과해버린다. 고쳐졌다면 409 no_receipt.
    blocked = False
    detail = None
    try:
        _svc(args=[]).set_verdict("T", "n", _canon())
    except HTTPException as e:
        blocked = (e.status_code == 409) and ("no_receipt_for_canonical" in str(e.detail))
        detail = str(e.detail)
    assert blocked, f"H2 결함 미수정: human Argument 없이 CANONICAL floor 가 열렸다 (detail={detail!r})"
    backend.ship([_ev(cid, "human_floor_blocked_without_kg_argument",
                      status=409, detail=detail)])

    # (음성 오라클 보강) 비-human Argument(doubt, by=agent) 만으론 client bit True 여도 floor 안 열린다.
    blocked_nonhuman = False
    try:
        _svc(args=[dict(id="T/doubt1", attacks=None, by="agent:x", kind="doubt")]).set_verdict(
            "T", "n", _canon())
    except HTTPException as e:
        blocked_nonhuman = (e.status_code == 409) and ("no_receipt_for_canonical" in str(e.detail))
    assert blocked_nonhuman, "H2 결함 미수정: 비-human Argument 만으로 CANONICAL floor 가 열렸다"

    # (양성) KG 에 실제 human attestation Argument(kind=evaluation, by=human:gira) 있으면 floor 통과.
    out = _svc(args=[dict(id="T/eval1", attacks=None, by="human:gira", kind="evaluation")]).set_verdict(
        "T", "n", _canon())
    assert out.get("ok") is True, f"실제 human Argument 가 있어도 floor 가 안 열렸다: {out!r}"
    backend.ship([_ev(cid, "human_floor_opens_with_real_argument",
                      ok=True, argument_by="human:gira", argument_kind="evaluation")])
