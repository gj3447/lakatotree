"""temporal gate reverifier (심화 D2) — 외부 증인 k-of-N 정족수를 봉인 번들에서 독립 재검증.

엔진의 temporal witness 는 예측 spec 을 외부 증인(Ed25519 did:key)이 서명해 백데이트를 막는다.
그 증거 참조는 포인터(노드 pred_anchor_verified)일 뿐 — 외부자가 재확인 불가였다. 이 게이트는
포인터를 재유도로 대체한다: 번들이 앵커들 + 예측 spec_digest + witness allow-list + threshold 를
content-sealed 로 나르고, 이 재검증기가:
  1. 각 앵커의 Ed25519 서명을 *번들 안 공개키(did:key)* 로 재검증(엔진 import 0, 자체 _ed25519);
  2. digest 가 봉인된 spec_digest 와 일치하는지(밀반입 봉쇄);
  3. distinct 유효 증인 ≥ threshold(정족수 — 담합 저항);
  4. max(T1) ≤ verdict_time(백데이트 방전).
어느 하나라도 실패/불명 = REJECT(fail-closed).

열거된 잔여(미해소): 증인 키의 *실세계 소유 독립성* — 이 게이트는 k 개의 서로 다른 did:key 가
서명했음을 증명하지, 그 키들이 서로 다른 주체가 out-of-band 로 쥔 것임을 증명하지 않는다(k-of-N 의
사회적 전제). solo box 가 k 개 키를 자작하면 수학은 통과하나 외부성은 여전히 약하다 — 이는 서명이
아니라 키 배포 거버넌스가 닫는다.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .._decision import ACCEPT, REJECT, gate_decision
from .._ed25519 import (
    KeyTypeError,
    did_key_decode,
    did_key_encode,
    ed25519_public_key_is_strict,
    ed25519_verify,
)

GATE = "temporal"
_ANCHOR_DOMAIN = b"lakatotree-temporal-anchor/v1\n"   # write_cert 도메인과 바이트 동일(엔진-CI 골든 핀)
_MAX_AUTHORITIES = 64
_ANCHOR_FIELDS = {"witness_did", "digest", "gen_time", "signature", "channel"}

_RESIDUAL = ("witness KEY-OWNERSHIP independence is out-of-band: this gate proves k distinct did:keys "
             "signed the same spec_digest before the verdict, NOT that those keys are held by k "
             "separate principals (the social premise of k-of-N). A solo box minting k keys passes the "
             "math; real independence is closed by key-distribution governance, not the signature.")


def _anchor_digest(spec_digest_hex: str) -> str:
    return hashlib.sha256(_ANCHOR_DOMAIN + (spec_digest_hex or "").encode("utf-8")).hexdigest()


def _signed_bytes(digest_hex: str, gen_time_iso: str) -> bytes:
    body = json.dumps({"digest": digest_hex, "gen_time": gen_time_iso},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _ANCHOR_DOMAIN + body.encode("utf-8")


def _parse_iso(ts: str) -> datetime:
    if not isinstance(ts, str) or not ts or ts != ts.strip():
        raise ValueError("canonical timestamp string required")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("timezone-aware timestamp required")
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError, AttributeError, TypeError) as exc:
        raise ValueError("bounded timezone-aware timestamp required") from exc


def _reject(reason: str) -> dict:
    return gate_decision(GATE, REJECT, reason)


def verify_temporal(payload, ctx) -> dict:
    """payload = {anchors:[{witness_did,digest,gen_time,signature}], spec_digest, witness_allowlist,
    threshold, verdict_time}. Total, fail-closed."""
    if not isinstance(payload, dict):
        return _reject("temporal payload 부재/비객체")
    anchors = payload.get("anchors")
    spec_digest = payload.get("spec_digest")
    allow = payload.get("witness_allowlist")
    threshold = payload.get("threshold")
    verdict_time = payload.get("verdict_time")
    if (
        not isinstance(anchors, list)
        or len(anchors) > _MAX_AUTHORITIES
        or not isinstance(spec_digest, str)
        or not spec_digest
        or spec_digest != spec_digest.strip()
        or not isinstance(allow, list)
        or not allow
        or len(allow) > _MAX_AUTHORITIES
        or type(threshold) is not int
        or threshold < 1
        or not isinstance(verdict_time, str)
        or not verdict_time
        or verdict_time != verdict_time.strip()
    ):
        return _reject("temporal payload 필드 부족(anchors/spec_digest/witness_allowlist/threshold/verdict_time)")

    want_digest = _anchor_digest(spec_digest)
    allow_set: set[str] = set()
    try:
        for witness in allow:
            if (
                not isinstance(witness, str)
                or not witness
                or witness != witness.strip()
            ):
                return _reject("witness allow-list 비정규")
            public_key = did_key_decode(witness)
            if (
                did_key_encode(public_key) != witness
                or not ed25519_public_key_is_strict(public_key)
            ):
                return _reject("witness allow-list 비정규")
            if witness in allow_set:
                return _reject("witness allow-list 중복")
            allow_set.add(witness)
        verdict_dt = _parse_iso(verdict_time)
    except (KeyTypeError, ValueError, OverflowError, AttributeError, TypeError):
        return _reject("witness allow-list 또는 verdict_time 파싱 실패(fail-closed)")

    valid: dict[str, tuple[str, datetime]] = {}
    for a in anchors:
        if not isinstance(a, dict) or set(a) != _ANCHOR_FIELDS:
            continue
        w = a.get("witness_did")
        gen_time = a.get("gen_time")
        signature = a.get("signature")
        if (
            not isinstance(w, str)
            or not w
            or w != w.strip()
            or not isinstance(gen_time, str)
            or not gen_time
            or gen_time != gen_time.strip()
            or not isinstance(signature, str)
            or len(signature) != 128
            or any(char not in "0123456789abcdef" for char in signature)
            or a.get("channel") != "ed25519-witness"
        ):
            continue
        if w not in allow_set:                              # 비허가 증인 미계상
            continue
        if a.get("digest") != want_digest:                  # 밀반입 봉쇄
            continue
        try:
            pub = did_key_decode(w)
            if did_key_encode(pub) != w or not ed25519_public_key_is_strict(pub):
                continue
            parsed_time = _parse_iso(gen_time)
            ok = ed25519_verify(
                pub,
                _signed_bytes(want_digest, gen_time),
                bytes.fromhex(signature),
            )
        except (KeyTypeError, ValueError, OverflowError, AttributeError, TypeError):
            continue
        if ok and (w not in valid or parsed_time > valid[w][1]):
            # 같은 증인의 여러 유효 진술 중 가장 늦은 절대시각을 보존한다.
            valid[w] = (gen_time, parsed_time)
    if len(valid) < threshold:
        return _reject(f"증인 정족수 미달: 유효 distinct {len(valid)} < threshold {threshold}")
    max_t1 = max(value[1] for value in valid.values())
    if max_t1 > verdict_dt:
        return _reject("백데이트: max(T1) > verdict_time(예측 앵커가 판정보다 늦음)")
    return gate_decision(GATE, ACCEPT,
                         f"k-of-N 정족수 재검증 통과(distinct {len(valid)} ≥ {threshold}, max T1 ≤ verdict)",
                         residual_trust_surface=_RESIDUAL)
