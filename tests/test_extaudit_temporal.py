"""EXTAUDIT S7 — Temporal witness: 사전등록 벽시계 순서를 외부 증인으로 방전 (rekor/OTS 흡수).

급소 #1: 409 는 DB 순서만 잠금(등록→판정 중앙값 46초). 양끝 앵커(예측 sha=T1, 판정 sha=T2)를 외부
증인이 서명 → T1≤T2 + 해시-인과 = 서버 시계 무신뢰로 백데이트 봉쇄. 증인 substrate=Ed25519 did:key
(write_cert hashlib-only 재사용). VAL L3 이 이 술어로 사상 처음 열린다(전엔 temporal_witness 상수 False).
# KG: q-extaudit-temporal-witness-20260722
"""
import pytest

from lakatos.temporal import (AnchorInvalid, anchor_digest, anchor_ordering_ok,
                              build_temporal_anchor, has_valid_temporal_witness,
                              verify_temporal_anchor)
from lakatos.verdicts import verdict_assurance
from lakatos.write_cert import did_key_encode, ed25519_public_key

_W = bytes([200]) * 32                                       # 증인 시크릿(out-of-band, 연구자와 분리 가정)
WDID = did_key_encode(ed25519_public_key(_W))
_R = bytes([201]) * 32                                       # 연구자(다른 주체)
RDID = did_key_encode(ed25519_public_key(_R))


# ── 앵커 발행/검증 왕복 ───────────────────────────────────────────────────────────────────
def test_anchor_roundtrip_returns_gen_time():
    a = build_temporal_anchor(_W, "rsha1", "2026-07-23T01:00:00+00:00", WDID)
    gt = verify_temporal_anchor(a, expect_receipt_sha="rsha1", witness_allowlist=[WDID])
    assert gt == "2026-07-23T01:00:00+00:00"


# ── 음성: solo box(allow-list 비었거나 증인 밖) → 무증인, L3 불가 ─────────────────────────
def test_empty_allowlist_is_no_witness():
    a = build_temporal_anchor(_W, "rsha1", "2026-07-23T01:00:00+00:00", WDID)
    with pytest.raises(AnchorInvalid):
        verify_temporal_anchor(a, expect_receipt_sha="rsha1", witness_allowlist=[])
    with pytest.raises(AnchorInvalid):
        verify_temporal_anchor(a, expect_receipt_sha="rsha1", witness_allowlist=[RDID])   # 연구자≠증인


# ── 음성: digest 밀반입(다른 receipt 커버 토큰) / 서명 위조 ────────────────────────────────
def test_digest_smuggle_and_forgery_rejected():
    a = build_temporal_anchor(_W, "rshaA", "2026-07-23T01:00:00+00:00", WDID)
    with pytest.raises(AnchorInvalid):
        verify_temporal_anchor(a, expect_receipt_sha="rshaB", witness_allowlist=[WDID])   # 다른 sha
    bad = dict(a, gen_time="2020-01-01T00:00:00+00:00")     # gen_time 개서 → 서명 불일치(gen_time 봉인)
    with pytest.raises(AnchorInvalid):
        verify_temporal_anchor(bad, expect_receipt_sha="rshaA", witness_allowlist=[WDID])


# ── 양끝 순서 부등식 ──────────────────────────────────────────────────────────────────────
def test_ordering_inequality():
    assert anchor_ordering_ok("2026-07-23T01:00:00+00:00", "2026-07-23T01:00:05+00:00") is True
    assert anchor_ordering_ok("2026-07-23T01:00:05+00:00", "2026-07-23T01:00:00+00:00") is False  # 백데이트
    assert anchor_ordering_ok("bad", "2026-07-23T01:00:00+00:00") is False                        # fail-closed


def test_two_ended_witness_predicate():
    pa = build_temporal_anchor(_W, "predsha", "2026-07-23T01:00:00+00:00", WDID)
    va = build_temporal_anchor(_W, "vsha", "2026-07-23T01:00:05+00:00", WDID)
    assert has_valid_temporal_witness(pa, va, pred_receipt_sha="predsha", verdict_receipt_sha="vsha",
                                      witness_allowlist=[WDID]) is True
    # 백데이트(예측 앵커가 판정보다 늦음) → False
    va_early = build_temporal_anchor(_W, "vsha", "2026-07-23T00:59:00+00:00", WDID)
    assert has_valid_temporal_witness(pa, va_early, pred_receipt_sha="predsha",
                                      verdict_receipt_sha="vsha", witness_allowlist=[WDID]) is False
    # 무증인(allow-list 빔) → False (부재≠반증이되 L3 승급 없음)
    assert has_valid_temporal_witness(pa, va, pred_receipt_sha="predsha", verdict_receipt_sha="vsha",
                                      witness_allowlist=[]) is False


# ── VAL L3 이 temporal witness 로 사상 처음 열린다 ───────────────────────────────────────
def test_val_l3_opens_with_temporal_witness():
    row = dict(verdict="progressive", verdict_source="scripted", current_receipt_sha="r1",
               measurement_grade="server_regenerated", replay_status="verified",
               assurance_tier_resolved="anchored", attested_by_did="did:key:zA", engine_rule_sha="e1")
    kw = dict(tree_attestors=["did:key:zA"], engine_rule_floor=frozenset({"e1"}))
    assert verdict_assurance(row, temporal_witness=True, **kw)["val"] == 3    # 증인 있으면 L3
    assert verdict_assurance(row, temporal_witness=False, **kw)["val"] == 2   # 없으면 L2(정직 천장)
