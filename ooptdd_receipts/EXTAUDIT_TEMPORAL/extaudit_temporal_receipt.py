"""OOPTDD emit-adapter — EXTAUDIT S7(2026-07-23) temporal witness 를 구조화 이벤트로 영수증화.

규율(ooptdd): 이벤트 리터럴은 이 adapter 에만. verify 가 실제 lakatos.temporal +
verdicts.verdict_assurance 를 Ed25519 증인으로 *구동*해:
  ① 양끝 앵커 왕복 + 위조(digest 밀반입/gen_time 개서/연구자≠증인/빈 allow-list) 거부
  ② VAL L3 개방이 유효 양끝 증인일 때만, 백데이트/무증인은 L2 천장
을 구조화 이벤트로 ship.

음성 오라클(no-fake-green): 무증인/백데이트가 L3 를 열거나 위조가 통과하면 assert 가 깨진다.
참고 테스트: lakatotree/tests/test_extaudit_temporal.py
# KG: LakatosTree_LakatoTree_SelfDev_20260612 / v26_extaudit_temporal
"""
import sys

_LKT = __import__("pathlib").Path(__file__).resolve().parents[2].as_posix()
if _LKT not in sys.path:
    sys.path.insert(0, _LKT)

from lakatos.temporal import (AnchorInvalid, build_temporal_anchor,             # noqa: E402
                              has_valid_temporal_witness, verify_temporal_anchor)
from lakatos.verdicts import verdict_assurance                                   # noqa: E402
from lakatos.write_cert import did_key_encode, ed25519_public_key               # noqa: E402

_W = bytes([220]) * 32
WDID = did_key_encode(ed25519_public_key(_W))
_R = bytes([221]) * 32
RDID = did_key_encode(ed25519_public_key(_R))


def _ev(cid, name, **attrs):
    return {"cid": cid, "correlation_id": cid, "cycle_id": cid,
            "service": "lakatos.extaudit.temporal", "event": name, **attrs}


def _val(tw):
    row = dict(verdict="progressive", verdict_source="scripted", current_receipt_sha="r1",
               measurement_grade="server_regenerated", replay_status="verified",
               assurance_tier_resolved="anchored", attested_by_did=WDID, engine_rule_sha="e1")
    return verdict_assurance(row, tree_attestors=[WDID], engine_rule_floor=frozenset({"e1"}),
                             temporal_witness=tw)["val"]


def verify(backend, cid):
    """temporal witness 구동 — 앵커 왕복/위조·L3 게이팅 증언."""
    # (1) 왕복 + 위조 거부.
    a = build_temporal_anchor(_W, "rshaA", "2026-07-23T03:00:00+00:00", WDID)
    gt = verify_temporal_anchor(a, expect_receipt_sha="rshaA", witness_allowlist=[WDID])
    assert gt == "2026-07-23T03:00:00+00:00"
    rejects = 0
    for kw, mut in ((dict(expect_receipt_sha="rshaB", witness_allowlist=[WDID]), a),   # digest 밀반입
                    (dict(expect_receipt_sha="rshaA", witness_allowlist=[RDID]), a),   # 연구자≠증인
                    (dict(expect_receipt_sha="rshaA", witness_allowlist=[]), a),       # solo box
                    (dict(expect_receipt_sha="rshaA", witness_allowlist=[WDID]),
                     dict(a, gen_time="2000-01-01T00:00:00+00:00"))):                  # gen_time 개서
        try:
            verify_temporal_anchor(mut, **kw)
        except AnchorInvalid:
            rejects += 1
    assert rejects == 4, f"위조 4종 중 {rejects}만 거부(나머지 통과 = 자기위조 통로)"
    backend.ship([_ev(cid, "anchor_verify_and_forgery_rejected", gen_time=gt, rejects=rejects)])

    # (2) VAL L3 게이팅.
    pa = build_temporal_anchor(_W, "predsha", "2026-07-23T03:00:00+00:00", WDID)
    va = build_temporal_anchor(_W, "vsha", "2026-07-23T03:00:05+00:00", WDID)
    va_back = build_temporal_anchor(_W, "vsha", "2026-07-23T02:59:00+00:00", WDID)
    valid = has_valid_temporal_witness(pa, va, pred_receipt_sha="predsha",
                                       verdict_receipt_sha="vsha", witness_allowlist=[WDID])
    back = has_valid_temporal_witness(pa, va_back, pred_receipt_sha="predsha",
                                      verdict_receipt_sha="vsha", witness_allowlist=[WDID])
    none = has_valid_temporal_witness(pa, va, pred_receipt_sha="predsha",
                                      verdict_receipt_sha="vsha", witness_allowlist=[])
    assert valid and _val(valid) == 3, "유효 양끝 증인인데 L3 안 열림"
    assert not back and _val(back) == 2, "백데이트(T1>T2)가 L3 를 염(백데이트 방전 실패)"
    assert not none and _val(none) == 2, "무증인(solo box)이 L3 를 염(외부성 없이 승급)"
    backend.ship([_ev(cid, "val_l3_gated_by_witness", valid_val=_val(valid),
                      backdated_val=_val(back), no_witness_val=_val(none))])
