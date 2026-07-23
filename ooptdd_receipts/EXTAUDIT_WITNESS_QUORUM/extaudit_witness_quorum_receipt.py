"""OOPTDD emit-adapter — 심화 D1(2026-07-23) k-of-N 증인 정족수를 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 lakatos.temporal.verify_temporal_quorum
을 Ed25519 증인으로 *구동*해:
  ① 정족수 충족(distinct ≥ threshold → max T1) + threshold=1 하위호환
  ② 담합 저항(단일/Sybil 다중서명/비허가 증인은 미달 거부)
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 단일 증인이나 Sybil 다중서명이 threshold 를 채우면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_witness_quorum.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / d1_extaudit_witness_quorum
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.temporal import (AnchorInvalid, build_temporal_anchor,               # noqa: E402
                              has_valid_temporal_quorum, verify_temporal_quorum)
from lakatos.write_cert import did_key_encode, ed25519_public_key                 # noqa: E402

_W = {n: bytes([240 + n]) * 32 for n in (1, 2, 3, 9)}
WDID = {n: did_key_encode(ed25519_public_key(_W[n])) for n in _W}
ALLOW = [WDID[1], WDID[2], WDID[3]]


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.witness_quorum", "event": name, **attrs}


def _a(n, gt, sha="rsha"):
    return build_temporal_anchor(_W[n], sha, gt, WDID[n])


def verify(backend, cid):
    """증인 정족수 구동 — 충족·담합저항 증언."""
    # (1) 정족수 충족 + 하위호환.
    t1 = verify_temporal_quorum([_a(1, "2026-07-23T01:00:00+00:00"), _a(2, "2026-07-23T01:00:03+00:00")],
                                expect_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=2)
    assert t1 == "2026-07-23T01:00:03+00:00", f"max T1 아님: {t1}"
    t1b = verify_temporal_quorum([_a(1, "2026-07-23T01:00:00+00:00")],
                                 expect_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=1)
    assert t1b == "2026-07-23T01:00:00+00:00"
    assert has_valid_temporal_quorum([_a(1, "2026-07-23T01:00:00+00:00"),
                                      _a(2, "2026-07-23T01:00:03+00:00")], "2026-07-23T02:00:00+00:00",
                                     pred_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=2) is True
    backend.ship([_ev(cid, "quorum_met_returns_max_t1", max_t1=t1)])

    # (2) 담합 저항 — 단일 / Sybil / 비허가.
    rejects = 0
    cases = [
        [_a(1, "2026-07-23T01:00:00+00:00")],                                             # 단일
        [_a(1, "2026-07-23T01:00:00+00:00"), _a(1, "2026-07-23T01:00:01+00:00")],         # Sybil 다중서명
        [_a(1, "2026-07-23T01:00:00+00:00"), _a(9, "2026-07-23T01:00:01+00:00")],         # 비허가 증인
    ]
    for anchors in cases:
        try:
            verify_temporal_quorum(anchors, expect_receipt_sha="rsha", witness_allowlist=ALLOW,
                                   threshold=2)
        except AnchorInvalid:
            rejects += 1
    assert rejects == 3, f"담합 3종 중 {rejects}만 거부(나머지 통과=정족수 우회)"
    backend.ship([_ev(cid, "collusion_resisted", rejects=rejects)])
