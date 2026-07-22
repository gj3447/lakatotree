"""OOPTDD emit-adapter — EXTAUDIT S6(2026-07-23) 역할분리 layout 을 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 lakatos.layout 순수함수 +
write_cert Ed25519 를 *구동*해:
  ① verb 좁히기(role_allowlist) + owner 서명 검증(functionary 개서 위조 거부)
  ② disjoint 겸직 차단 + Sybil dedup(distinct_signer_count)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): layout 이 verb 를 안 좁히거나 겸직/다중서명을 허용하면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_role_layout.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v25_extaudit_role_layout
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.layout import (canonical_layout_blob, disjoint_violation,          # noqa: E402
                            distinct_signer_count, pubkeys_for_verb, role_allowlist,
                            verify_layout_sig)
from lakatos.write_cert import (did_key_encode, ed25519_public_key, ed25519_sign)   # noqa: E402

_S = {n: bytes([n]) * 32 for n in (1, 2, 3)}
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.role_layout", "event": name, **attrs}


def _layout():
    return {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID[1]], "threshold": 1},
        {"verb": "submit_test_result", "pubkeys": [DID[2]], "threshold": 1},
        {"verb": "set_verdict_canonical", "pubkeys": [DID[2], DID[3]], "threshold": 2}],
        "disjoint_roles": [["register_prediction", "set_verdict_canonical"]]}


def verify(backend, cid):
    """역할분리 구동 — verb 좁히기·owner 서명·disjoint·Sybil 증언."""
    lo = _layout()
    attestors = [DID[1], DID[2], DID[3]]

    # (1) verb 좁히기 + owner 서명 게이팅.
    narrowed = role_allowlist(lo, "submit_test_result", attestors)
    full = role_allowlist(None, "submit_test_result", attestors)   # 미선언 폴백
    assert narrowed == [DID[2]], f"submit verb 가 안 좁혀짐: {narrowed}"
    assert full == attestors, "layout 미선언인데 폴백 아님(라이브 무회귀 위반)"
    sig = ed25519_sign(_S[1], canonical_layout_blob(lo)).hex()
    forged = {**lo, "steps": lo["steps"] + [{"verb": "x", "pubkeys": [DID[3]]}]}
    assert verify_layout_sig(lo, DID[1], sig) is True
    assert verify_layout_sig(forged, DID[1], sig) is False, "functionary 개서 위조가 통과(owner 신뢰 root 붕괴)"
    backend.ship([_ev(cid, "verb_narrowed_and_owner_sig_gated", narrowed=narrowed)])

    # (2) disjoint 겸직 + Sybil.
    collide = {"layout_version": 1, "steps": [
        {"verb": "register_prediction", "pubkeys": [DID[1]]},
        {"verb": "set_verdict_canonical", "pubkeys": [DID[1]]}],
        "disjoint_roles": [["register_prediction", "set_verdict_canonical"]]}
    assert disjoint_violation(collide, DID[1], "set_verdict_canonical") is not None, "겸직 미검출"
    assert disjoint_violation(lo, DID[2], "submit_test_result") is None, "정상 서명이 오검출"
    assert distinct_signer_count([DID[2], DID[2], DID[2]]) == 1, "Sybil 다중서명이 threshold 를 부풀림"
    assert distinct_signer_count([DID[2], DID[3]]) == 2
    backend.ship([_ev(cid, "disjoint_and_sybil_blocked", pubkeys=pubkeys_for_verb(lo, "submit_test_result"))])
