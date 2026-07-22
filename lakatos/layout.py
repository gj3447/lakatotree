"""Research Layout — 역할분리 정책(EXTAUDIT S6, in-toto 흡수 2026-07-23).

급소 #2: 같은 principal 이 예측등록→실험→결과제출→판정을 전부 수행(judge_script_sha==pred_script_sha
177/177), attestor_dids 는 평평한 단일 목록이라 역할 미분화였다. in-toto 의 4-키 기하학 이식(통째
의존 0 — write_cert 의 did:key/Ed25519 재사용):

  · Layout = owner 가 서명한 정책 문서. owner 키 ≠ functionary(step 수행) 키 (verify_layout_sig).
  · Step = verb 별 {pubkeys, threshold}. 한 verb 에 허용된 서명자를 좁힌다(pubkeys_for_verb).
  · disjoint_roles = 두 역할에 같은 DID 가 겹치면 위반(disjoint_violation) — 급소 #2 의 직접 답.
  · threshold = *서로 다른 DID* 수로 계상(distinct_signer_count) — 같은 DID 다중서명은 1(Sybil 봉쇄,
    in-toto verifylib 의 'subkey 는 main key 로 1회' 정신).
  · expires = layout 신선도 창(in-toto verify_layout_expiration 전사).

전부 순수함수(무 I/O). layout 미선언 트리는 이 모듈이 관여하지 않는다(dead-σ: 기존 attestor_dids
폴백 불변 — 라이브 무회귀). owner 서명 검증은 write_cert 의 Ed25519/did:key 를 그대로 쓴다.
# KG: q-extaudit-role-separation-20260722 / LakatosTree_LakatoTree_SelfDev
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from lakatos.write_cert import CERT_MAX_AGE_SECONDS, did_key_decode, ed25519_verify

LAYOUT_HEADER = b"lakatos-layout\x00v1\n"   # 버전드 타입헤더(write-cert/receipt 인코딩 규율 동일 장르)


class LayoutError(ValueError):
    """layout 파싱/검증 실패의 공통 뿌리 — 호출부가 HTTP 코드로 번역."""


def _jcs(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def canonical_layout_blob(layout: dict) -> bytes:
    """owner 서명 대상 바이트열 = 헤더 + JCS(layout 본문). layout_sig/layout_owner_did 는 봉투라 제외."""
    body = {k: v for k, v in layout.items() if k not in ("layout_sig", "layout_owner_did")}
    return LAYOUT_HEADER + _jcs(body)


def parse_role_layout(raw) -> dict | None:
    """트리의 research_layout(JCS str 또는 dict) → 정규화 dict. 미선언(None/'')=None(관여 안 함).

    구조: {layout_version:1, expires:ISO?, steps:[{verb, pubkeys:[did...], threshold:int}],
           disjoint_roles:[[verb,verb]...]}. 형식 위반 = LayoutError(무음 통과 없음)."""
    if raw is None or raw == "":
        return None
    layout = raw if isinstance(raw, dict) else json.loads(raw)
    if not isinstance(layout, dict) or not isinstance(layout.get("steps"), list):
        raise LayoutError("layout: steps 리스트 필수")
    for s in layout["steps"]:
        if not isinstance(s, dict) or not s.get("verb") or not isinstance(s.get("pubkeys"), list):
            raise LayoutError(f"layout step 형식 오류: {s}")
    return layout


def verify_layout_sig(layout: dict, owner_did: str, sig_hex: str) -> bool:
    """owner DID 의 Ed25519 서명으로 layout 무결성 검증(in-toto: 신뢰 root=owner 키, functionary 아님).

    owner 키는 *번들 밖*(out-of-band)에서 온다 — 검증자가 별도 보유(c1verify witness 모델 정합)."""
    if not owner_did or not sig_hex:
        return False
    try:
        pub = did_key_decode(owner_did)
        return ed25519_verify(pub, canonical_layout_blob(layout), bytes.fromhex(sig_hex))
    except (ValueError, LayoutError):
        return False


def pubkeys_for_verb(layout: dict, verb: str) -> list[str] | None:
    """이 verb 를 수행할 수 있는 서명자 DID 목록. verb step 미선언=None(이 verb 는 layout 이 좁히지 않음).

    None(부재)과 []( 선언됐으나 빈 목록=아무도 못 함)은 다르다 — 호출부가 구분한다."""
    for s in layout.get("steps", []):
        if s.get("verb") == verb:
            return [str(d).strip() for d in s["pubkeys"] if d and str(d).strip()]
    return None


def threshold_for_verb(layout: dict, verb: str) -> int:
    for s in layout.get("steps", []):
        if s.get("verb") == verb:
            return int(s.get("threshold", 1))
    return 1


def distinct_signer_count(signer_dids) -> int:
    """서로 다른 DID 수 — threshold 계상(같은 DID 다중서명=1, Sybil 봉쇄)."""
    return len({str(d).strip() for d in signer_dids if d and str(d).strip()})


def disjoint_violation(layout: dict, signer_did: str, verb: str) -> str | None:
    """signer_did 가 verb 와 disjoint 로 묶인 다른 역할의 pubkeys 에도 있으면 위반 사유 문자열, 없으면 None.

    급소 #2 직접 답: 같은 키가 predict 와 attest 를 겸직하면 여기서 잡힌다(역할=다른 열쇠 강제)."""
    signer = (signer_did or "").strip()
    if not signer:
        return None
    for pair in layout.get("disjoint_roles", []):
        if verb not in pair:
            continue
        for other in pair:
            if other == verb:
                continue
            others = pubkeys_for_verb(layout, other) or []
            if signer in others:
                return f"서명자 {signer[:24]}… 가 disjoint 역할 '{verb}'·'{other}' 를 겸직(역할분리 위반)"
    return None


def layout_expired(layout: dict, now: datetime | None = None,
                   max_age_seconds: float = CERT_MAX_AGE_SECONDS) -> bool:
    """expires(ISO) 경과 여부. 미선언=만료 없음(False). 파싱 실패=만료 취급(True, fail-closed)."""
    exp = layout.get("expires")
    if not exp:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return now > dt
    except (ValueError, AttributeError):
        return True


def role_allowlist(layout: dict | None, verb: str, tree_attestors: list[str]) -> list[str]:
    """이 verb 의 유효 allow-list — layout 이 verb 를 좁히면 그 pubkeys, 아니면 트리 attestor 전체.

    layout None(미선언 트리) 또는 verb step 부재 → tree_attestors 그대로(기존 거동 불변)."""
    if layout is None:
        return tree_attestors
    narrowed = pubkeys_for_verb(layout, verb)
    return narrowed if narrowed is not None else tree_attestors
