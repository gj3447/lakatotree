"""OOPTDD emit-adapter — EXTAUDIT S3b(2026-07-22) VAL 표면 확장을 구조화 이벤트 trace 로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제
server.contexts.tree.repository.normalize_node_row / judgement_policy.response_assurance 를 *구동*해:
  ① read-model 부착(비파괴 — bare verdict 불변 + display/assurance 추가, admin 원문 유지)
  ② submit 응답 재도출(armed @L2 vs disarmed @L0)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): bare verdict 를 치환하는 구현(내부 술어 파괴)이나 미부착이면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_val_surfaces.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v22_extaudit_val_surfaces
"""
import os
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.val_surfaces", "event": name, **attrs}


def verify(backend, cid):
    """VAL 표면 확장 구동 — read-model 비파괴 부착 + submit 재도출 증언."""
    from server.contexts.tree.repository import normalize_node_row
    from server.contexts.tree.judgement_policy import response_assurance

    # (1) read-model: 부착 + 비파괴 + admin 원문.
    scored = normalize_node_row(dict(tag="n1", verdict="progressive", verdict_source="scripted",
                                     current_receipt_sha="r1",
                                     measurement_grade="server_regenerated", replay_status="verified"))
    assert scored["verdict_display"] == "progressive@L2(replay_verified)", scored.get("verdict_display")
    assert scored["verdict"] == "progressive", "bare verdict 치환됨 — 내부 술어 파괴(비파괴 계약 위반)"
    admin = normalize_node_row(dict(tag="n2", verdict="proof"))
    assert admin["verdict_display"] == "proof", f"admin 어휘 과잉 포맷: {admin['verdict_display']}"
    backend.ship([_ev(cid, "read_model_attaches_val_nondestructive",
                      scored_display=scored["verdict_display"], bare=scored["verdict"],
                      admin_display=admin["verdict_display"])])

    # (2) submit 응답 재도출: armed vs disarmed 구분.
    d2, a2 = response_assurance(verdict="progressive", current_receipt_sha="r1",
                                measurement_grade="server_regenerated", replay_status="verified",
                                assurance_tier_resolved="anchored", attested_by_did=None)
    d0, a0 = response_assurance(verdict="progressive", current_receipt_sha="r1",
                                measurement_grade="client_asserted", replay_status="not_attempted",
                                assurance_tier_resolved="anchored", attested_by_did=None)
    assert d2 == "progressive@L2(replay_verified)" and a2["val"] == 2, (d2, a2)
    assert "@L0(client_asserted" in d0 and a0["val"] == 0, (d0, a0)
    backend.ship([_ev(cid, "submit_response_assurance_derived", armed=d2, disarmed=d0)])
