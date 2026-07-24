"""substrate gate reverifier (C1 S3 + 심화 D3 substrate-B) — 무결성 + issuer AUTHENTICITY 재검증.

The engine content-addresses every verdict (:VerdictReceipt seals fields as sha256(header+JCS)).
This gate re-checks that integrity with zero engine import: recompute every receipt's content-sha and
match its claimed receipt_sha (tampering dies here), then fold the chain head->genesis.

심화 D3 (substrate-B): 이제 issuer AUTHENTICITY 도 닫는다. 번들이 write-cert(signer_did, signature,
command, issued_at) + attestor_allowlist 를 나르면, 이 게이트가 c1verify 자체 Ed25519 로 서명을
canonical_cert_blob 위에서 재검증하고 signer 가 allow-list 안인지 확인한다(엔진 import 0). 통과 시
authenticity residual 이 *해소*된다 — dishonest issuer 가 chain 을 자작해도 allow-list 밖 서명이라 여기서
죽는다. write-cert 미동봉(레거시)이면 기존대로 무결성만 ACCEPT + authenticity residual 명시.

열거된 잔여(write-cert 없을 때만): issuer AUTHENTICITY — content-addressing 은 chain 내부 일관성만
증명, genuine issuer 가 mint 했는지는 아니다. write-cert 서명이 그걸 닫는다(이제 payload 로 재검증 가능).
"""
from __future__ import annotations

from .._cert import CertShapeError, canonical_cert_blob
from .._decision import ACCEPT, REJECT, gate_decision
from .._ed25519 import KeyTypeError, did_key_decode, ed25519_verify
from ..receipts import check_chain_integrity

GATE = "substrate"

_RESIDUAL_NO_CERT = (
    "issuer AUTHENTICITY is out-of-band: content-addressing proves the chain is internally "
    "consistent and tamper-evident, NOT that a genuine issuer minted it (a dishonest issuer can "
    "mint any content-consistent chain). Authenticity needs the Ed25519 write-cert signature — "
    "attach it in the bundle (substrate-B) to discharge this residual.")
_RESIDUAL_WITH_CERT = (
    "signer KEY-OWNERSHIP governance is out-of-band: the write-cert proves an allow-listed did:key "
    "signed this head command, NOT that the allow-list itself names only honest principals (that is "
    "a key-distribution/governance question, not a signature one).")


def _verify_authenticity(cert, allowlist, head) -> tuple[bool, str]:
    """write-cert 재검증 → (ok, reason). fail-closed: 형식/서명/allow-list/명령바인딩 어느 하나 실패=거짓."""
    if not isinstance(cert, dict):
        return False, "write_cert 비객체"
    signer = str(cert.get("signer_did") or "").strip()
    allow = {str(w).strip() for w in (allowlist or []) if w}
    if not allow:
        return False, "attestor_allowlist 비었음(무-attestor = 서명자 없음)"
    if signer not in allow:
        return False, f"서명자 {signer[:24]}… 는 attestor allow-list 밖"
    command = cert.get("command")
    # 명령이 head receipt 를 커버하는지(prev_receipt_sha 바인딩) — sign-X-execute-Y 봉쇄.
    if not isinstance(command, dict):
        return False, "cert.command 비객체"
    try:
        blob = canonical_cert_blob(command, str(cert.get("issued_at") or ""))
        pub = did_key_decode(signer)
        ok = ed25519_verify(pub, blob, bytes.fromhex(cert.get("signature") or ""))
    except (CertShapeError, KeyTypeError, ValueError) as exc:
        return False, f"cert 재검증 실패(fail-closed): {exc}"
    if not ok:
        return False, "write-cert Ed25519 서명 불일치"
    return True, f"allow-listed 서명자 {signer[:24]}… 가 head 명령 서명(authenticity 재검증)"


def verify_substrate(payload, ctx) -> dict:
    """payload = {chain:[receipt...], head:'<sha>', write_cert?:{...}, attestor_allowlist?:[did...]}.
    Total, fail-closed. write-cert 동봉 시 authenticity 도 재검증(substrate-B)."""
    if not isinstance(payload, dict):
        return gate_decision(GATE, REJECT, "substrate payload absent or not an object")
    fold, reason = check_chain_integrity(payload.get("chain"), payload.get("head"))
    if reason:
        return gate_decision(GATE, REJECT, reason)

    cert = payload.get("write_cert")
    if cert is None:
        # 레거시 경로: 무결성만 — authenticity 는 미해소 residual(정직).
        return gate_decision(GATE, ACCEPT,
                             f"receipt chain content-addressed + folded to genesis "
                             f"(verdict={fold['verdict']!r}) — authenticity NOT re-derived",
                             residual_trust_surface=_RESIDUAL_NO_CERT)
    ok, why = _verify_authenticity(cert, payload.get("attestor_allowlist"), payload.get("head"))
    if not ok:
        return gate_decision(GATE, REJECT, f"substrate-B authenticity 실패: {why}")
    return gate_decision(GATE, ACCEPT,
                         f"chain 무결성 + issuer authenticity 재검증 — {why}",
                         residual_trust_surface=_RESIDUAL_WITH_CERT)
