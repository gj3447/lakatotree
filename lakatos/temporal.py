"""Temporal witness — 사전등록의 벽시계 순서를 외부 증인으로 방전 (EXTAUDIT S7, 2026-07-23).

급소 #1: 409 락은 DB 내부 순서만 보장 — 결과를 먼저 보고 '예측'을 등록해도 완벽한 novel 적중이
됐다(사전등록→판정 중앙값 46초). verdicts.py:381 자백 "벽시계 순서는 temporal witness 의 몫".

rekor/OTS 흡수 통찰(양끝 앵커): 예측 receipt sha 에 T1, 판정 receipt sha 에 T2 를 *외부 증인*이
서명하면 T1<T2 + 해시-인과 사슬 = 서버 로컬 시각을 전혀 신뢰하지 않아도 백데이트가 불가능하다.

증인 substrate = did:key(Ed25519) — write_cert 의 hashlib-only 경로 재사용(RSA/DER RFC3161 파서를
손으로 굴리지 않는다: q_signer_key_substrate 결정 준수). RFC3161 TSA 는 이 인터페이스의 한 구현이고,
여기 커널은 그 위상(외부 서명자 + gen_time + digest 바인딩)을 순수하게 정의한다.

★정직 경계(c1verify witness 모델 정합): 증인 키가 *연구자와 분리된 별개 주체*(out-of-band k-of-N)일
때만 진짜 외부성이 성립한다. solo box 에서 증인 키를 자기가 쥐면 이 witness 는 약하다 — 그 경우
c1verify README 규율대로 UNSUPPORTED(신뢰 저하)로 읽어야 하며 L3 를 주지 않는다(witness_allowlist 가
비면 검증 실패). digest 도메인 분리 + gen_time 봉인으로 자기위조 재사용은 막지만 시각 자체의 외부성은
키 소유 구조가 결정한다.
# KG: q-extaudit-temporal-witness-20260722 / crit-extaudit 감사
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from lakatos.write_cert import did_key_decode, ed25519_verify

_ANCHOR_DOMAIN = b"lakatotree-temporal-anchor/v1\n"   # 도메인 분리 — verdict/prediction blob 과 sha-space 격리


class AnchorInvalid(ValueError):
    """temporal anchor 검증 실패 — fail-closed(조용한 통과 없음, c1verify REJECT 규율)."""


def anchor_digest(receipt_sha_hex: str) -> str:
    """앵커 대상 다이제스트 = sha256(도메인태그 + receipt_sha). 어느 receipt 를 앵커했는지 못박는다."""
    return hashlib.sha256(_ANCHOR_DOMAIN + (receipt_sha_hex or "").encode("utf-8")).hexdigest()


def _signed_bytes(digest_hex: str, gen_time_iso: str) -> bytes:
    """증인 서명 대상 = 도메인 + JCS({digest, gen_time}). gen_time 을 봉인해 같은 서명을 다른 시각으로
    재사용 못 하게 한다(외부 시각의 무결성)."""
    body = json.dumps({"digest": digest_hex, "gen_time": gen_time_iso},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return _ANCHOR_DOMAIN + body.encode("utf-8")


def build_temporal_anchor(witness_secret32: bytes, receipt_sha_hex: str, gen_time_iso: str,
                          witness_did: str) -> dict:
    """증인(테스트/외부 TSA-역)이 발행하는 anchor. 서버는 verify 만 호출한다.

    {witness_did, digest, gen_time, signature(hex), channel}. gen_time 은 *증인의* 시각(서버 시계 아님)."""
    from lakatos.write_cert import ed25519_sign
    digest = anchor_digest(receipt_sha_hex)
    sig = ed25519_sign(witness_secret32, _signed_bytes(digest, gen_time_iso))
    return {"witness_did": witness_did, "digest": digest, "gen_time": gen_time_iso,
            "signature": sig.hex(), "channel": "ed25519-witness"}


def verify_temporal_anchor(anchor: dict, *, expect_receipt_sha: str,
                           witness_allowlist: list[str]) -> str:
    """anchor 검증 → gen_time(ISO) 반환. 실패는 전부 AnchorInvalid(fail-closed).

    순서: 증인 신원(allow-list — 비면 즉시 실패=solo box 무증인) → digest 바인딩(다른 receipt 커버
    토큰 밀반입 봉쇄) → Ed25519 서명(gen_time 봉인 포함). allow-list 는 out-of-band 로 보유한
    k-of-N 증인 DID — 연구자와 분리돼야 진짜 외부성."""
    if not anchor:
        raise AnchorInvalid("anchor 없음")
    witness = str(anchor.get("witness_did") or "").strip()
    if not witness:
        raise AnchorInvalid("witness_did 없음")
    if not witness_allowlist or witness not in witness_allowlist:
        raise AnchorInvalid(f"증인 {witness[:24]}… 는 witness allow-list 밖(solo box=무증인, L3 불가)")
    want = anchor_digest(expect_receipt_sha)
    if anchor.get("digest") != want:
        raise AnchorInvalid("digest 불일치 — 다른 receipt 를 커버한 토큰(밀반입 봉쇄)")
    gen_time = str(anchor.get("gen_time") or "")
    try:
        pub = did_key_decode(witness)
        ok = ed25519_verify(pub, _signed_bytes(want, gen_time), bytes.fromhex(anchor.get("signature") or ""))
    except ValueError as exc:
        raise AnchorInvalid(f"서명 파싱 실패: {exc}") from exc
    if not ok:
        raise AnchorInvalid("증인 서명 불일치")
    return gen_time


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def anchor_ordering_ok(pred_gen_time: str, verdict_gen_time: str) -> bool:
    """양끝 앵커의 시각 순서 T1 ≤ T2 — 예측 앵커가 판정 앵커보다 앞서야 한다(백데이트 방전).

    파싱 실패 = False(fail-closed). 이것이 '결과 먼저, 예측 나중'을 물리적으로 막는 핵심 부등식."""
    try:
        return _parse_iso(pred_gen_time) <= _parse_iso(verdict_gen_time)
    except (ValueError, AttributeError):
        return False


def has_valid_temporal_witness(pred_anchor: dict | None, verdict_anchor: dict | None, *,
                               pred_receipt_sha: str, verdict_receipt_sha: str,
                               witness_allowlist: list[str]) -> bool:
    """VAL L3 게이트의 temporal_witness 입력 — 양끝 앵커가 다 유효하고 T1≤T2 인가 (순수 술어).

    어느 하나라도 검증 실패/부재면 False(부재≠반증이되 L3 승급은 없음, dead-σ). L3 는 이것이 True 이고
    나머지 조건(role attestation·engine floor·anchored tier)이 다 설 때만 열린다."""
    try:
        t1 = verify_temporal_anchor(pred_anchor, expect_receipt_sha=pred_receipt_sha,
                                    witness_allowlist=witness_allowlist)
        t2 = verify_temporal_anchor(verdict_anchor, expect_receipt_sha=verdict_receipt_sha,
                                    witness_allowlist=witness_allowlist)
    except AnchorInvalid:
        return False
    return anchor_ordering_ok(t1, t2)
