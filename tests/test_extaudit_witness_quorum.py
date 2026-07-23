"""심화 D1 — k-of-N 증인 정족수: 단일 증인 → threshold 로 담합 저항 강화.

L3 은 지금까지 증인 1명이면 성립 → 단일 증인 담합/키탈취가 백데이트 가능. c1verify 가 규정한
'k-of-N witness quorum' 을 실현: 서로 다른 증인 threshold 명이 각각 같은 예측 spec 을 서명해야
temporal witness 성립. 같은 증인 다중서명은 1로 계상(Sybil 봉쇄). 기본 threshold=1 은 하위호환.
# KG: q-extaudit-temporal-witness-20260722 (심화)
"""
import pytest

from lakatos.temporal import (AnchorInvalid, build_temporal_anchor, has_valid_temporal_quorum,
                              verify_temporal_quorum)
from lakatos.write_cert import did_key_encode, ed25519_public_key

# 3 증인(1,2,3) + 1 비허가(9)
_W = {n: bytes([230 + n]) * 32 for n in (1, 2, 3, 9)}
WDID = {n: did_key_encode(ed25519_public_key(_W[n])) for n in _W}
ALLOW = [WDID[1], WDID[2], WDID[3]]


def _a(n, gt, sha="rsha"):
    return build_temporal_anchor(_W[n], sha, gt, WDID[n])


# ── 정족수 충족: distinct 증인 ≥ threshold ────────────────────────────────────────────────
def test_quorum_met_returns_max_gen_time():
    anchors = [_a(1, "2026-07-23T01:00:00+00:00"), _a(2, "2026-07-23T01:00:03+00:00")]
    t1 = verify_temporal_quorum(anchors, expect_receipt_sha="rsha", witness_allowlist=ALLOW,
                                threshold=2)
    assert t1 == "2026-07-23T01:00:03+00:00"        # max(T1) — 전원이 그 시각 이전 커밋 동의


def test_threshold_1_backward_compatible():
    t1 = verify_temporal_quorum([_a(1, "2026-07-23T01:00:00+00:00")],
                                expect_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=1)
    assert t1 == "2026-07-23T01:00:00+00:00"


# ── 정족수 미달: distinct 증인 < threshold (담합 저항) ─────────────────────────────────────
def test_single_witness_fails_threshold_2():
    with pytest.raises(AnchorInvalid):
        verify_temporal_quorum([_a(1, "2026-07-23T01:00:00+00:00")],
                               expect_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=2)


def test_same_witness_multisig_counts_as_one():
    # 같은 증인 3장 서명 = distinct 1 → threshold 2 미달(Sybil 봉쇄).
    dup = [_a(1, "2026-07-23T01:00:00+00:00"), _a(1, "2026-07-23T01:00:01+00:00"),
           _a(1, "2026-07-23T01:00:02+00:00")]
    with pytest.raises(AnchorInvalid):
        verify_temporal_quorum(dup, expect_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=2)


def test_unauthorized_witness_not_counted():
    # 허가 증인 1 + 비허가 증인 9 → distinct 유효 1 → threshold 2 미달.
    mixed = [_a(1, "2026-07-23T01:00:00+00:00"), _a(9, "2026-07-23T01:00:01+00:00")]
    with pytest.raises(AnchorInvalid):
        verify_temporal_quorum(mixed, expect_receipt_sha="rsha", witness_allowlist=ALLOW, threshold=2)


# ── L3 정족수 게이트 + 순서 ───────────────────────────────────────────────────────────────
def test_has_valid_quorum_gate():
    anchors = [_a(1, "2026-07-23T01:00:00+00:00"), _a(2, "2026-07-23T01:00:03+00:00")]
    # max T1 = 01:00:03 ≤ T2 01:00:10 → True
    assert has_valid_temporal_quorum(anchors, "2026-07-23T01:00:10+00:00",
                                     pred_receipt_sha="rsha", witness_allowlist=ALLOW,
                                     threshold=2) is True
    # 백데이트: max T1 = 01:00:03 > T2 01:00:01 → False
    assert has_valid_temporal_quorum(anchors, "2026-07-23T01:00:01+00:00",
                                     pred_receipt_sha="rsha", witness_allowlist=ALLOW,
                                     threshold=2) is False
    # 정족수 미달(1명) → False
    assert has_valid_temporal_quorum([_a(1, "2026-07-23T01:00:00+00:00")],
                                     "2026-07-23T01:00:10+00:00", pred_receipt_sha="rsha",
                                     witness_allowlist=ALLOW, threshold=2) is False


# ── 배선 앵커 (ag1 장르): register 가 정족수를 소비한다 ────────────────────────────────────
def test_register_wires_quorum():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server" / "contexts" / "tree"
           / "judgement_service.py").read_text(encoding="utf-8")
    assert "verify_temporal_quorum(" in src and "witness_threshold" in src, \
        "register 가 증인 정족수 미배선(D1 붕괴)"
