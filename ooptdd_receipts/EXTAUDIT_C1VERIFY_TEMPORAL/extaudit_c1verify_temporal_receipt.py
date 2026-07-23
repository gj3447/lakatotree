"""OOPTDD emit-adapter — 심화 D2(2026-07-23) c1verify 독립 temporal 재검증을 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 c1verify._ed25519 +
c1verify.gates.temporal 을 *구동*해:
  ① Ed25519 골든 상호대조(엔진 write_cert 서명 ↔ c1verify 독립 검증 바이트 동일)
  ② temporal 게이트 재검증(정족수 ACCEPT + 위조/백데이트/미달 REJECT)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 위조가 ACCEPT 되거나 골든 대조가 어긋나면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_c1verify_temporal.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / d2_extaudit_c1verify_temporal
"""
import hashlib
import json
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from c1verify._ed25519 import did_key_decode, ed25519_verify                       # noqa: E402
from c1verify.gates.temporal import verify_temporal                               # noqa: E402
from lakatos.write_cert import (did_key_encode, ed25519_public_key, ed25519_sign)  # noqa: E402

_W = {n: bytes([20 + n]) * 32 for n in (1, 2, 3, 9)}
DID = {n: did_key_encode(ed25519_public_key(_W[n])) for n in _W}
_DOMAIN = b"lakatotree-temporal-anchor/v1\n"


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.c1verify_temporal", "event": name, **attrs}


def _anchor(n, sd, gt):
    ad = hashlib.sha256(_DOMAIN + sd.encode()).hexdigest()
    body = json.dumps({"digest": ad, "gen_time": gt}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return {"witness_did": DID[n], "digest": ad, "gen_time": gt,
            "signature": ed25519_sign(_W[n], _DOMAIN + body.encode()).hex()}


def _p(anchors, threshold, vt="2026-07-23T02:00:00+00:00", sd="sd"):
    return {"anchors": anchors, "spec_digest": sd, "witness_allowlist": [DID[1], DID[2], DID[3]],
            "threshold": threshold, "verdict_time": vt}


def verify(backend, cid):
    """c1verify temporal 구동 — 골든 대조·게이트 재검증 증언."""
    # (1) Ed25519 골든 상호대조 — 엔진 서명을 독립 검증기가 바이트 동일하게 검증.
    pub = ed25519_public_key(_W[1])
    sig = ed25519_sign(_W[1], b"golden")
    assert ed25519_verify(pub, b"golden", sig) is True, "c1verify 가 엔진 서명 검증 실패(골든 어긋남)"
    assert ed25519_verify(pub, b"golden", bytes(64)) is False, "위조 서명이 통과"
    assert did_key_decode(DID[1]) == pub, "did:key 디코드 불일치"
    backend.ship([_ev(cid, "ed25519_golden_cross_check", did=DID[1][:24])])

    # (2) 게이트 재검증 — 정족수 ACCEPT + 위조/백데이트/미달 REJECT(total).
    ok = verify_temporal(_p([_anchor(1, "sd", "2026-07-23T01:00:00+00:00"),
                             _anchor(2, "sd", "2026-07-23T01:00:03+00:00")], 2), {})
    assert ok["decision"] == "ACCEPT" and ok["residual_trust_surface"], ok
    rejects = 0
    for p in (_p([_anchor(1, "sd", "2026-07-23T01:00:00+00:00")], 2),                        # 미달
              _p([_anchor(1, "OTHER", "2026-07-23T01:00:00+00:00"),
                  _anchor(2, "OTHER", "2026-07-23T01:00:03+00:00")], 2),                     # 밀반입
              _p([_anchor(1, "sd", "2026-07-23T03:00:00+00:00"),
                  _anchor(2, "sd", "2026-07-23T03:00:03+00:00")], 2, vt="2026-07-23T02:00:00+00:00"),  # 백데이트
              _p([_anchor(1, "sd", "2026-07-23T01:00:00+00:00"),
                  _anchor(9, "sd", "2026-07-23T01:00:03+00:00")], 2),                        # 비허가
              None):                                                                          # garbage
        if verify_temporal(p, {})["decision"] == "REJECT":
            rejects += 1
    assert rejects == 5, f"REJECT 5종 중 {rejects}만(나머지 통과=검증기 구멍)"
    backend.ship([_ev(cid, "temporal_gate_reverifies", accept_residual=bool(ok["residual_trust_surface"]),
                      rejects=rejects)])
