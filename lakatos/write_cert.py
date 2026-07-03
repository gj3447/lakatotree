"""write certificate — 판결 쓰기의 서명 명령화 (git-흡수 G10, push-cert 이식).

git push cert(builtin/receive-pack.c:2179-2199): 서명된 blob 이 *곧 명령 목록*이라 sign-X-execute-Y
가 프로토콜에서 표현 불가하고, author 는 client 문자열이 아니라 서명에서 유도된다. 이식:

  · 서명 대상 = canonical command blob(버전드 헤더 + JCS canonical JSON) — {tree, tag,
    prev_receipt_sha, metric_value, script_sha}. prev_receipt_sha 가 G1 영수증 체인 포인터에
    CAS 바인딩되어 replay 가 구조적으로 죽는다(재제출=옛 포인터 서명=불일치; 같은 노드 재채점은
    어차피 409 — git 의 HMAC nonce 가 막던 창을 내용주소 체인이 대신 막는다).
  · 신원 = did:key(Ed25519, multicodec 0xed01). 검증은 순수 파이썬 RFC 8032(외부 의존 0 —
    q_signer_key_substrate 결정: cryptography vendor 불가 → hashlib 만). secp256k1(0xe701) 등
    타 키타입은 명시 거부. p333 DID==PeerId 와 포맷 동형(코드 공유 아님).
  · 강제는 G6 tier 체인 안에서(assurance.GATE_WRITE_CERT): anchored tier ∧ 트리가 attestor
    allow-list(=키 실물)를 선언했을 때 무조건. on/off 플래그가 아니다 — advisory cert
    (GIT_PUSH_CERT_STATUS, export-and-hope)는 정확히 P1 실패라 반전. allow-list 없는 트리는
    서명자가 존재하지 않아 잠글 수 없다(dead-σ 안전: 키 없는 배포를 409 로 잠그지 않는다).
  · issue_nonce/verify_nonce: 서버발행 무상태 HMAC(발급 seed 재계산+상수시간 비교,
    receive-pack.c:644-670) — 세션형 클라이언트용 신선도 보조(선택). 판결 쓰기의 주 replay 방어는
    위의 prev_receipt_sha CAS 바인딩.

서명(sign)도 제공한다 — 클라이언트/테스트가 쓰는 순수 수학이고, 서버는 verify 만 호출한다.

# KG: LakatosTree_GitAbsorption_20260702 / G10_write_certificates
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

CERT_HEADER = b"lakatos-write-cert\x00v1\n"   # 버전드 타입헤더(G1 영수증 인코딩 규율과 동일 장르)
CERT_MAX_AGE_SECONDS = 900.0                  # 발급시각 신선도 창(±) — 코드 상수(요청 가변 금지, G9 규율)

# command 의 고정 필드셋 — 서명이 덮는 범위가 곧 명령의 전부(필드 추가 = 인코딩 버전 bump).
COMMAND_FIELDS = ("tree", "tag", "prev_receipt_sha", "metric_value", "script_sha")


class CertError(ValueError):
    """write-cert 검증 실패의 공통 뿌리 — 호출부가 HTTP 코드로 번역."""


class CertMissing(CertError):
    pass


class CertSignatureInvalid(CertError):
    pass


class CertSignerNotAllowed(CertError):
    pass


class CertWrongKeyType(CertError):
    pass


class CertStale(CertError):
    pass


class CertCommandMismatch(CertError):
    pass


# ── canonical 직렬화 — 결정론(JCS 장르: 정렬 키·최소 구분자) ────────────────────────────────
def _jcs(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def canonical_cert_blob(command: dict, issued_at: str) -> bytes:
    """서명 대상 바이트열 = 헤더 + JCS({command(고정 필드셋), issued_at}). 필드 과부족 = 에러."""
    unknown = set(command) - set(COMMAND_FIELDS)
    if unknown:
        raise CertCommandMismatch(f"command 미지 필드 {sorted(unknown)} — 고정 필드셋 밖(서명 범위 불명)")
    body = {k: command.get(k) for k in COMMAND_FIELDS}
    return CERT_HEADER + _jcs({"command": body, "issued_at": issued_at})


# ── 순수 Ed25519 (RFC 8032) — hashlib 만 사용, 외부 의존 0 ──────────────────────────────────
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_BY = (4 * pow(5, _P - 2, _P)) % _P


def _sha512(msg: bytes) -> bytes:
    return hashlib.sha512(msg).digest()


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
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
assert _BX is not None
_B = (_BX, _BY, 1, _BX * _BY % _P)   # extended homogeneous (X, Y, Z, T)
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


def _point_compress(p) -> bytes:
    z_inv = _inv(p[2])
    x = p[0] * z_inv % _P
    y = p[1] * z_inv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


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


def _secret_expand(secret32: bytes) -> tuple[int, bytes]:
    if len(secret32) != 32:
        raise CertError("Ed25519 secret 은 32바이트")
    h = _sha512(secret32)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public_key(secret32: bytes) -> bytes:
    a, _ = _secret_expand(secret32)
    return _point_compress(_point_mul(a, _B))


def ed25519_sign(secret32: bytes, msg: bytes) -> bytes:
    a, prefix = _secret_expand(secret32)
    pub = _point_compress(_point_mul(a, _B))
    r = int.from_bytes(_sha512(prefix + msg), "little") % _L
    rp = _point_compress(_point_mul(r, _B))
    k = int.from_bytes(_sha512(rp + pub + msg), "little") % _L
    s = (r + k * a) % _L
    return rp + s.to_bytes(32, "little")


def ed25519_verify(public32: bytes, msg: bytes, sig64: bytes) -> bool:
    if len(public32) != 32 or len(sig64) != 64:
        return False
    a = _point_decompress(public32)
    if a is None:
        return False
    rp = _point_decompress(sig64[:32])
    if rp is None:
        return False
    s = int.from_bytes(sig64[32:], "little")
    if s >= _L:                      # malleability 거부(RFC 8032 §5.1.7)
        return False
    k = int.from_bytes(_sha512(sig64[:32] + public32 + msg), "little") % _L
    return _point_equal(_point_mul(s, _B), _point_add(rp, _point_mul(k, a)))


# ── did:key (multicodec) — ed25519(0xed01) 만, 타 키타입 명시 거부 ──────────────────────────
_B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ED25519_PREFIX = b"\xed\x01"
_KNOWN_OTHER_PREFIXES = {b"\xe7\x01": "secp256k1", b"\x80\x24": "p256", b"\xeb\x01": "x25519"}


def _b58encode(data: bytes) -> str:
    n = int.from_bytes(data, "big")
    out = ""
    while n:
        n, rem = divmod(n, 58)
        out = _B58_ALPHABET[rem] + out
    pad = 0
    for byte in data:
        if byte == 0:
            pad += 1
        else:
            break
    return "1" * pad + out


def _b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        idx = _B58_ALPHABET.find(ch)
        if idx < 0:
            raise CertError(f"base58 밖 문자: {ch!r}")
        n = n * 58 + idx
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def _did_key_encode_multicodec(prefixed: bytes) -> str:
    return "did:key:z" + _b58encode(prefixed)


def did_key_encode(public32: bytes) -> str:
    if len(public32) != 32:
        raise CertError("ed25519 공개키는 32바이트")
    return _did_key_encode_multicodec(_ED25519_PREFIX + public32)


def did_key_decode(did: str) -> bytes:
    """did:key → ed25519 공개키 32B. 타 키타입(secp256k1 등)은 CertWrongKeyType 로 명시 거부."""
    if not did.startswith("did:key:z"):
        raise CertError(f"did:key(base58btc, z-prefix) 아님: {did[:32]}")
    raw = _b58decode(did[len("did:key:z"):])
    if raw[:2] == _ED25519_PREFIX:
        key = raw[2:]
        if len(key) != 32:
            raise CertError(f"ed25519 키 길이 {len(key)} ≠ 32")
        return key
    kind = _KNOWN_OTHER_PREFIXES.get(raw[:2], f"multicodec {raw[:2].hex()}")
    raise CertWrongKeyType(f"미지원 키타입 {kind} — write-cert 는 ed25519(0xed01) 전용")


# ── 무상태 HMAC nonce(보조 신선도) — 발급 seed 재계산 + 상수시간 비교 ────────────────────────
def issue_nonce(seed: bytes, tree: str, ts_iso: str) -> str:
    return hmac.new(seed, f"{tree}:{ts_iso}".encode(), hashlib.sha256).hexdigest()


def verify_nonce(seed: bytes, tree: str, ts_iso: str, nonce: str) -> bool:
    return hmac.compare_digest(issue_nonce(seed, tree, ts_iso), nonce or "")


# ── 열쇠공(클라이언트 조성) — keygen / cert 조립 (R5: 자물쇠만 있고 열쇠공 없던 갭 봉합) ──────
def keygen() -> tuple[str, str]:
    """새 Ed25519 키쌍 → (secret_hex 64자, did:key). 시드는 os.urandom(비결정 — 서버 검증엔 무관)."""
    import os
    secret = os.urandom(32)
    return secret.hex(), did_key_encode(ed25519_public_key(secret))


def build_write_cert(secret32: bytes, command: dict, issued_at: str | None = None) -> dict:
    """명령을 서명해 WriteCertIn 형태 dict 조성 — 서명 대상은 canonical_cert_blob(고정 필드셋).
    CLI cert-sign / MCP write_cert_json 의 공용 조성기(순수: HTTP 없음, prev 회수는 호출자 몫)."""
    ts = issued_at or datetime.now(timezone.utc).isoformat()
    sig = ed25519_sign(secret32, canonical_cert_blob(command, ts))
    return {
        'signer_did': did_key_encode(ed25519_public_key(secret32)),
        'signature': sig.hex(),
        'issued_at': ts,
        'command': {k: command.get(k) for k in COMMAND_FIELDS},
    }


# ── cert 검증(서버 경계) — 서명·신원·명령 바인딩·신선도를 한 곳에서 ─────────────────────────
def _parse_iso(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError) as e:
        raise CertStale(f"issued_at 파싱 불가: {ts!r} ({e})")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def verify_write_cert(cert: dict, *, expected_command: dict, allowlist: list[str],
                      now: datetime | None = None,
                      max_age_seconds: float = CERT_MAX_AGE_SECONDS) -> dict:
    """cert = {signer_did, signature(hex), issued_at, command(dict)}. 전부 통과 시
    {'signer_did': ..., 'command': ...} 반환 — author 는 이 signer_did 에서 유도한다.

    순서: 신원(allow-list, 정확 문자열) → 키타입 → 명령 바인딩(JCS 바이트 동일 — sign-X-execute-Y
    불가) → 신선도 → 서명. 실패는 전부 typed CertError(조용한 통과 없음)."""
    signer = (cert.get("signer_did") or "").strip()
    if not signer:
        raise CertMissing("signer_did 없음")
    if signer not in allowlist:
        raise CertSignerNotAllowed(f"서명자 {signer[:24]}… 는 트리 attestor allow-list 밖")
    public = did_key_decode(signer)
    command = dict(cert.get("command") or {})
    if _jcs({k: command.get(k) for k in COMMAND_FIELDS}) != \
            _jcs({k: expected_command.get(k) for k in COMMAND_FIELDS}):
        raise CertCommandMismatch(
            f"서명된 명령 ≠ 실제 요청 (sign-X-execute-Y 거부): cert={command} req={expected_command}")
    issued_at = cert.get("issued_at") or ""
    now_dt = now or datetime.now(timezone.utc)
    age = abs((now_dt - _parse_iso(issued_at)).total_seconds())
    if age > max_age_seconds:
        raise CertStale(f"cert 발급시각 창({max_age_seconds:.0f}s) 초과: age={age:.0f}s")
    try:
        sig = bytes.fromhex(cert.get("signature") or "")
    except ValueError:
        raise CertSignatureInvalid("signature hex 파싱 불가")
    if not ed25519_verify(public, canonical_cert_blob(command, issued_at), sig):
        raise CertSignatureInvalid("Ed25519 서명 검증 실패 — 명령 위조 또는 did 사칭")
    return {"signer_did": signer, "command": command}
