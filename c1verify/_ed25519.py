"""Ed25519 (RFC 8032) + did:key — 독립 재구현 (심화 D2, c1verify substrate-B).

c1verify 는 lakatos 를 import 하지 않는 독립 외부 검증기다(clean env 테스트). 지금까지 서명 검증
능력이 없어 substrate 게이트가 issuer AUTHENTICITY 를 'out-of-band residual'로 남겼고, temporal
witness 를 재검증할 수 없었다. 이 모듈이 그 공백을 메운다: write_cert 의 hashlib-only Ed25519 를
*바이트 동일*하게 재구현(엔진-CI 골든이 상호 대조로 핀). 이로써 c1verify 가 witness 서명·write-cert
서명을 봉인 번들에서 독립 재검증할 수 있다.

정직 경계: 이 코드는 write_cert 와 같은 순수 수학이므로 '독립 재구현'이지 '독립 알고리즘'은 아니다
(같은 RFC 8032). 진짜 독립성은 서로 다른 키를 서로 다른 주체가 쥐는 데서 온다(k-of-N).
# KG: q-extaudit-temporal-witness-20260722 (심화 D2)
"""
from __future__ import annotations

import hashlib

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_BY = (4 * pow(5, _P - 2, _P)) % _P


def _sha512(msg: bytes) -> bytes:
    return hashlib.sha512(msg).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * pow(2, (_P - 1) // 4, _P) % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_BX = _recover_x(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % _P)
_IDENT = (0, 1, 1, 0)


def _point_add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _point_mul(s: int, p):
    q = _IDENT
    while s > 0:
        if s & 1:
            q = _point_add(q, p)
        p = _point_add(p, p)
        s >>= 1
    return q


def _point_equal(p, q) -> bool:
    return ((p[0] * q[2] - q[0] * p[2]) % _P == 0
            and (p[1] * q[2] - q[1] * p[2]) % _P == 0)


def _point_decompress(b: bytes):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def ed25519_verify(public32: bytes, msg: bytes, sig64: bytes) -> bool:
    """RFC 8032 verify — malleability 거부(s < L). write_cert.ed25519_verify 와 바이트 동일 결과."""
    if len(public32) != 32 or len(sig64) != 64:
        return False
    a = _point_decompress(public32)
    if a is None:
        return False
    rp = _point_decompress(sig64[:32])
    if rp is None:
        return False
    s = int.from_bytes(sig64[32:], "little")
    if s >= _L:
        return False
    k = int.from_bytes(_sha512(sig64[:32] + public32 + msg), "little") % _L
    return _point_equal(_point_mul(s, _B), _point_add(rp, _point_mul(k, a)))


# ── did:key (multicodec ed25519 0xed01) ────────────────────────────────────────────────────
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ED25519_PREFIX = b"\xed\x01"


class KeyTypeError(ValueError):
    pass


def _b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        idx = _B58_ALPHABET.find(ch)
        if idx < 0:
            raise KeyTypeError(f"base58 밖 문자: {ch!r}")
        n = n * 58 + idx
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def did_key_decode(did: str) -> bytes:
    """did:key → ed25519 공개키 32B. 타 키타입은 KeyTypeError(명시 거부, fail-closed)."""
    if not did.startswith("did:key:z"):
        raise KeyTypeError(f"did:key(z-prefix) 아님: {did[:24]}")
    raw = _b58decode(did[len("did:key:z"):])
    if raw[:2] != _ED25519_PREFIX:
        raise KeyTypeError(f"미지원 키타입 multicodec {raw[:2].hex()} — ed25519 전용")
    key = raw[2:]
    if len(key) != 32:
        raise KeyTypeError(f"ed25519 키 길이 {len(key)} ≠ 32")
    return key
