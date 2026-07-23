"""심화 D2 — c1verify 독립 temporal 재검증: 외부 검증기가 증인 서명을 실제로 재검증(substrate-B).

c1verify 는 lakatos import 0 의 독립 검증기다. 지금까지 Ed25519 서명 검증 능력이 없어 substrate
게이트가 issuer AUTHENTICITY 를 out-of-band residual 로 남겼고 temporal witness 재검증 불가였다.
D2: c1verify/_ed25519(RFC 8032 독립 재구현, write_cert 와 바이트 동일) + gates/temporal.
이 테스트는 (a) 골든 상호대조(엔진 서명 ↔ c1verify 검증) (b) 게이트 재검증 (c) no-lakatos-import 를 핀.
# KG: q-extaudit-temporal-witness-20260722 (심화 D2)
"""
import hashlib
import json

import c1verify
from c1verify._ed25519 import KeyTypeError, did_key_decode, ed25519_verify
from c1verify.gates.temporal import verify_temporal
# 엔진 측(서명 생성) — 골든 상호대조용. c1verify 는 이걸 import 하지 않는다(아래 테스트가 핀).
from lakatos.write_cert import (did_key_decode as eng_decode, did_key_encode,
                                ed25519_public_key, ed25519_sign)

_W = {n: bytes([245 + n if 245 + n < 256 else 250 + n - 6]) * 32 for n in (1, 2, 3)}
_W = {n: bytes([10 + n]) * 32 for n in (1, 2, 3, 9)}
DID = {n: did_key_encode(ed25519_public_key(_W[n])) for n in _W}
_DOMAIN = b"lakatotree-temporal-anchor/v1\n"


def _anchor(n, spec_digest, gt):
    ad = hashlib.sha256(_DOMAIN + spec_digest.encode()).hexdigest()
    body = json.dumps({"digest": ad, "gen_time": gt}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    sig = ed25519_sign(_W[n], _DOMAIN + body.encode())
    return {"witness_did": DID[n], "digest": ad, "gen_time": gt, "signature": sig.hex()}


# ── (a) 골든 상호대조: 엔진 서명을 c1verify 가 바이트 동일하게 검증 ──────────────────────────
def test_ed25519_golden_cross_check():
    pub = ed25519_public_key(_W[1])
    msg = b"cross-check message"
    sig = ed25519_sign(_W[1], msg)
    assert ed25519_verify(pub, msg, sig) is True                 # c1verify verify(엔진 sign)
    assert ed25519_verify(pub, msg, bytes(64)) is False          # 위조 거부
    # did:key 디코드도 엔진과 동일 결과
    assert did_key_decode(DID[1]) == eng_decode(DID[1]) == pub


def test_did_key_rejects_non_ed25519():
    import pytest
    with pytest.raises(KeyTypeError):
        did_key_decode("did:key:zNotABase58Key!!!")


# ── (b) 게이트 재검증: 정족수 통과 ACCEPT / 위조·백데이트·미달 REJECT ─────────────────────────
def _payload(anchors, threshold, verdict_time="2026-07-23T02:00:00+00:00", sd="specdig"):
    return {"anchors": anchors, "spec_digest": sd, "witness_allowlist": [DID[1], DID[2], DID[3]],
            "threshold": threshold, "verdict_time": verdict_time}


def test_gate_accepts_valid_quorum():
    p = _payload([_anchor(1, "specdig", "2026-07-23T01:00:00+00:00"),
                  _anchor(2, "specdig", "2026-07-23T01:00:03+00:00")], threshold=2)
    d = verify_temporal(p, {})
    assert d["decision"] == "ACCEPT" and d["residual_trust_surface"]   # residual 명시


def test_gate_rejects_sub_threshold():
    p = _payload([_anchor(1, "specdig", "2026-07-23T01:00:00+00:00")], threshold=2)
    assert verify_temporal(p, {})["decision"] == "REJECT"


def test_gate_rejects_digest_smuggle():
    # 다른 spec 을 서명한 앵커(밀반입) — spec_digest 불일치.
    p = _payload([_anchor(1, "OTHER", "2026-07-23T01:00:00+00:00"),
                  _anchor(2, "OTHER", "2026-07-23T01:00:03+00:00")], threshold=2)
    assert verify_temporal(p, {})["decision"] == "REJECT"


def test_gate_rejects_backdated():
    p = _payload([_anchor(1, "specdig", "2026-07-23T03:00:00+00:00"),
                  _anchor(2, "specdig", "2026-07-23T03:00:03+00:00")], threshold=2,
                 verdict_time="2026-07-23T02:00:00+00:00")   # max T1 > verdict
    assert verify_temporal(p, {})["decision"] == "REJECT"


def test_gate_rejects_unauthorized_and_sybil():
    # 허가1 + 비허가9 → distinct 유효 1 < 2.
    p = _payload([_anchor(1, "specdig", "2026-07-23T01:00:00+00:00"),
                  _anchor(9, "specdig", "2026-07-23T01:00:03+00:00")], threshold=2)
    assert verify_temporal(p, {})["decision"] == "REJECT"
    # 같은 증인 2장 → distinct 1 < 2.
    p2 = _payload([_anchor(1, "specdig", "2026-07-23T01:00:00+00:00"),
                   _anchor(1, "specdig", "2026-07-23T01:00:01+00:00")], threshold=2)
    assert verify_temporal(p2, {})["decision"] == "REJECT"


def test_gate_is_total_on_garbage():
    for bad in (None, {}, {"anchors": "x"}, {"anchors": [], "spec_digest": "s"}):
        assert verify_temporal(bad, {})["decision"] == "REJECT"


# ── (c) c1verify 는 여전히 lakatos 를 import 하지 않는다 (독립성 by construction) ─────────────
def test_c1verify_temporal_gate_does_not_import_lakatos():
    import ast
    from pathlib import Path
    for mod in ("_ed25519.py", "gates/temporal.py"):
        src = (Path(c1verify.__file__).parent / mod).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("lakatos"):
                raise AssertionError(f"{mod} imports lakatos.{node.module} — 독립성 위반")
            if isinstance(node, ast.Import):
                for n in node.names:
                    assert not n.name.startswith("lakatos"), f"{mod} imports {n.name}"


# ── temporal 이 c1verify GATES 에 등록됐다 ────────────────────────────────────────────────
def test_temporal_registered_in_gates():
    assert "temporal" in c1verify.GATES
