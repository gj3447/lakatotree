"""OOPTDD emit-adapter — EXTAUDIT S3(2026-07-22) VAL 등급 표면 동봉을 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 엔진이 아니라 이 adapter 에만. verify 가 실제
lakatos.verdicts.verdict_assurance / format_verdict_with_val 과 evidence_claim_service.standing
(스텁 kg 주입)을 *구동*해:
  ① parity gap 봉합 — armed vs disarmed progressive 표면 구분
  ② 결함주입 — 위조 grade 라벨은 replay 반증에 L0 하드캡 / 부재는 무강등(dead-σ)
  ③ standing 표면 — 채점 어휘 @L 동봉 + admin 어휘 원문 유지
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 라벨-신뢰 장르(mismatch 인데 L2)나 bare 방출이 살아있으면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_val.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v21_extaudit_val
"""
import os
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")

from lakatos.verdicts import format_verdict_with_val, verdict_assurance   # noqa: E402


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.val", "event": name, **attrs}


def _row(**kw):
    base = dict(verdict="progressive", verdict_source="scripted", current_receipt_sha="r1")
    base.update(kw)
    return base


def verify(backend, cid):
    """VAL 도출·표면 동봉 구동 — parity·결함주입·standing 배선 증언."""
    # (1) parity gap: armed vs disarmed 가 표면에서 달라야 한다.
    armed = format_verdict_with_val("progressive", verdict_assurance(
        _row(measurement_grade="server_regenerated", replay_status="verified")))
    disarmed = format_verdict_with_val("progressive", verdict_assurance(
        _row(measurement_grade="client_asserted", replay_status="not_attempted")))
    assert armed != disarmed, f"armed/disarmed 표면 동일(급소 #5 잔존): {armed}"
    assert "@L2(replay_verified" in armed and "@L0(client_asserted" in disarmed
    backend.ship([_ev(cid, "parity_gap_closed", armed=armed, disarmed=disarmed)])

    # (2) 결함주입: 위조 grade 라벨 + replay 반증 → L0 하드캡. 부재는 무강등(이중가드).
    forged = verdict_assurance(_row(measurement_grade="server_regenerated", replay_status="mismatch"))
    assert forged["val"] == 0 and forged["basis"] == ("replay_refuted",), \
        f"grade 라벨만 믿고 L2 부여(위조 통과): {forged}"
    ok2 = verdict_assurance(_row(measurement_grade="server_regenerated", replay_status="verified"),
                            chain_ok=None)
    assert ok2["val"] == 2, f"부재(chain 미대조)가 강등을 일으킴(dead-σ 위반): {ok2}"
    backend.ship([_ev(cid, "forged_grade_capped_l0", forged_val=forged["val"], unknown_keeps=ok2["val"])])

    # (3) standing 표면 배선 — 스텁 kg 로 실제 service 코드 경로 구동.
    from server.contexts.tree.evidence_claim_service import EvidenceClaimService
    svc = object.__new__(EvidenceClaimService)
    svc.kg = lambda q, **p: [{"verdict": "progressive", "verdict_source": "scripted",
                              "current_receipt_sha": "r1", "measurement_grade": "client_asserted",
                              "replay_status": "not_attempted", "args": []}]
    scored = svc.standing("t", "n")
    assert "@L0(client_asserted" in scored["verdict"] and scored["assurance"]["val"] == 0, scored
    svc.kg = lambda q, **p: [{"verdict": "proof", "verdict_source": None, "current_receipt_sha": None,
                              "measurement_grade": None, "replay_status": None, "args": []}]
    admin = svc.standing("t", "n")
    assert admin["verdict"] == "proof", f"admin 어휘 과잉 포맷: {admin['verdict']}"
    backend.ship([_ev(cid, "standing_surface_embeds_val",
                      scored=scored["verdict"], admin=admin["verdict"])])
