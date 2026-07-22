"""EXTAUDIT S6 — 역할분리 Research Layout (in-toto 흡수 2026-07-23).

급소 #2: predict=experiment=judge 동일 principal. in-toto 4-키 기하학 이식으로 역할별 다른 열쇠 강제.
순수 로직(layout.py) + submit allow-list 좁히기 배선. layout 미선언 트리는 기존 attestor_dids 폴백
불변(라이브 무회귀).
# KG: q-extaudit-role-separation-20260722
"""
import pytest

from lakatos.layout import (LayoutError, canonical_layout_blob, disjoint_violation,
                            distinct_signer_count, layout_expired, parse_role_layout,
                            pubkeys_for_verb, role_allowlist, threshold_for_verb, verify_layout_sig)
from lakatos.write_cert import did_key_encode, ed25519_public_key, ed25519_sign

_S = {n: bytes([n]) * 32 for n in (1, 2, 3)}                     # 고정 시크릿 3개(결정론 픽스처)
DID = {n: did_key_encode(ed25519_public_key(_S[n])) for n in _S}


def _layout(**kw):
    base = dict(layout_version=1, steps=[
        {"verb": "register_prediction", "pubkeys": [DID[1]], "threshold": 1},
        {"verb": "submit_test_result", "pubkeys": [DID[2]], "threshold": 1},
        {"verb": "set_verdict_canonical", "pubkeys": [DID[2], DID[3]], "threshold": 2},
    ], disjoint_roles=[["register_prediction", "set_verdict_canonical"]])
    base.update(kw)
    return base


# ── 파싱 ────────────────────────────────────────────────────────────────────────────────
def test_parse_none_when_undeclared():
    assert parse_role_layout(None) is None and parse_role_layout("") is None


def test_parse_rejects_malformed():
    with pytest.raises(LayoutError):
        parse_role_layout({"layout_version": 1})            # steps 없음
    with pytest.raises(LayoutError):
        parse_role_layout({"steps": [{"pubkeys": []}]})     # verb 없음


# ── verb 별 pubkeys / threshold ───────────────────────────────────────────────────────────
def test_pubkeys_for_verb_narrows_by_role():
    lo = _layout()
    assert pubkeys_for_verb(lo, "register_prediction") == [DID[1]]
    assert pubkeys_for_verb(lo, "submit_test_result") == [DID[2]]
    assert pubkeys_for_verb(lo, "unknown_verb") is None      # 부재 ≠ 빈목록
    assert threshold_for_verb(lo, "set_verdict_canonical") == 2


# ── R1 급소 재현: 같은 DID 가 predict+attest 겸직 → disjoint 위반 ─────────────────────────
def test_disjoint_violation_catches_role_collision():
    # DID[1] 을 attest step 에도 넣으면 predict 와 disjoint 겹침.
    lo = _layout(steps=[
        {"verb": "register_prediction", "pubkeys": [DID[1]], "threshold": 1},
        {"verb": "set_verdict_canonical", "pubkeys": [DID[1]], "threshold": 1},
    ])
    assert disjoint_violation(lo, DID[1], "set_verdict_canonical") is not None
    assert disjoint_violation(_layout(), DID[2], "submit_test_result") is None   # 겹침 없음


# ── R3 Sybil: 같은 DID 다중서명은 threshold 1 로만 계상 ────────────────────────────────────
def test_distinct_signer_count_dedups():
    assert distinct_signer_count([DID[2], DID[2], DID[2]]) == 1
    assert distinct_signer_count([DID[2], DID[3]]) == 2


# ── R5 layout 위조: owner 서명 불일치 → False ─────────────────────────────────────────────
def test_verify_layout_sig_roundtrip_and_forgery():
    lo = _layout()
    sig = ed25519_sign(_S[1], canonical_layout_blob(lo)).hex()
    assert verify_layout_sig(lo, DID[1], sig) is True
    forged = _layout(steps=lo["steps"] + [{"verb": "x", "pubkeys": [DID[3]]}])   # functionary 가 layout 개서
    assert verify_layout_sig(forged, DID[1], sig) is False
    assert verify_layout_sig(lo, DID[2], sig) is False       # 다른 owner 키


# ── expires ───────────────────────────────────────────────────────────────────────────────
def test_layout_expiration():
    assert layout_expired(_layout()) is False                                    # expires 미선언
    assert layout_expired(_layout(expires="2000-01-01T00:00:00+00:00")) is True
    assert layout_expired(_layout(expires="not-a-date")) is True                 # 파싱 실패=fail-closed


# ── R4 비파괴: layout 미선언 트리는 tree attestors 그대로 (라이브 무회귀) ────────────────────
def test_role_allowlist_falls_back_when_undeclared():
    attestors = [DID[1], DID[2], DID[3]]
    assert role_allowlist(None, "submit_test_result", attestors) == attestors    # layout 없음
    assert role_allowlist(_layout(), "submit_test_result", attestors) == [DID[2]]  # 좁힘
    assert role_allowlist(_layout(), "unknown_verb", attestors) == attestors      # verb step 부재=폴백


# ── submit 배선 앵커 (ag1 장르): role_allowlist 가 프로덕션 경로에 실린다 ─────────────────────
def test_submit_wires_role_allowlist():
    from pathlib import Path
    svc = (Path(__file__).resolve().parents[1] / "server" / "contexts" / "tree"
           / "judgement_service.py").read_text(encoding="utf-8")
    assert "role_allowlist(" in svc and "disjoint_violation(" in svc, \
        "submit 경로에 layout 역할 좁히기/disjoint 미배선(S6 붕괴)"
