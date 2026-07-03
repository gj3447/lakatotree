"""git-흡수 G10 landed guards — write certificate (push-cert 이식: 서명이 곧 명령, authorship 비위조).

  guard_defect(개선축)     : test_spoofed_actor_write_rejected_at_anchored_tier
        — Sybil 갭(author/by/actor=미인증 client 문자열) 폐쇄: attestor 를 선언한 anchored 트리에선
          서명 cert 없는/서명자 미허용/명령 불일치(sign-X-execute-Y) 판결 쓰기가 거부된다.
          enforcement 발동 조건 = tier 게이트 무장 ∧ attestor allow-list 선언(키 실물) — on/off
          플래그가 아니라 키 선언이 스위치(advisory cert=GIT_PUSH_CERT_STATUS 는 P1 실패라 반전,
          allow-list 없는 트리는 서명자 자체가 없어 잠금 불가 = dead-σ 안전). legacy 거동불변.
  guard_mechanism(novel축) : test_author_derived_from_signature_not_client_string
        — push-cert 메커니즘 실재: RFC-8032 Ed25519 검증(공식 테스트벡터) + did:key 디코더
          (multicodec 0xed01, secp256k1 거부) + 서명 blob 이 곧 명령(내용주소 command, prev_receipt_sha
          CAS 바인딩=replay 봉합) + author 는 client 문자열이 아니라 *서명에서 유도*되어 스탬프.

# KG: LakatosTree_GitAbsorption_20260702 / G10_write_certificates
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from lakatos import write_cert as W
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import CertCommandIn, TestResultIn as Result, WriteCertIn


# ── 테스트 키쌍(RFC 8032 표기: 32B secret → 32B public) — 테스트 전용 고정 시드 ──
_SK_A = bytes(range(32))                    # 허용 attestor A
_SK_B = bytes(range(1, 33))                 # 미허용 서명자 B
_PK_A = W.ed25519_public_key(_SK_A)
_PK_B = W.ed25519_public_key(_SK_B)
_DID_A = W.did_key_encode(_PK_A)
_DID_B = W.did_key_encode(_PK_B)
# 프로덕션 경로가 실시간으로 신선도를 재므로, 테스트 cert 는 실제 현재시각으로 발급(결정론: 창 ±15분 ≫ 실행시간).
_NOW = datetime.now(timezone.utc).isoformat()
_STALE = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


class _SubmitKg:
    """실 submit_test_result 구동 더블(g1/g6 계승) — pred 행에 tier+attestor 를 실어 준다."""

    def __init__(self, pred: dict):
        self.pred = pred
        self.node = {'current_receipt_sha': None}
        self.captured: list = []

    def __call__(self, query, **p):
        if 'pred_metric AS m' in query:
            return [dict(self.pred, prev_receipt_sha=self.node['current_receipt_sha'])]
        return []

    def tx(self, ops):
        self.captured.append(ops)
        return [[{'claimed': params.get('tag')}] for _q, params in ops]


def _svc(tree_props: dict):
    pred = {'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio', 'novel': '',
            'vsrc': None, 'nmet': None, 'ndir': None, 'nthr': None, 'psha': None, 'closes': 'q-x',
            'n_opened': 0, 'pred_registered_at': '2026-07-02', 'node_state': 'PREDICTED',
            'judged_at': None, 'existing_metric_value': None, 'hard_core': '',
            'require_novel_anchor': False, **tree_props}
    kg = _SubmitKg(pred)
    return JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                            foundation=lambda n: None, reproducible_for_node=lambda n, t: None), kg


def _cert(sk: bytes, did: str, *, tag='seam', metric_value=1.0, script_sha='',
          prev=None, issued_at=_NOW, tamper_after_sign=None) -> WriteCertIn:
    command = dict(tree='T', tag=tag, prev_receipt_sha=prev,
                   metric_value=metric_value, script_sha=script_sha,
                   verb='submit_test_result')   # AG5-IDENT: cert 를 submit verb 에 바인딩
    sig = W.ed25519_sign(sk, W.canonical_cert_blob(command, issued_at))
    if tamper_after_sign:
        command.update(tamper_after_sign)   # 서명 후 명령 변조 = sign-X-execute-Y 시도
    return WriteCertIn(signer_did=did, signature=sig.hex(), issued_at=issued_at,
                       command=CertCommandIn(**command))


def _submit(svc, cert=None):
    return svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline', write_cert=cert))


_ANCHORED = {'assurance_tier': 'anchored', 'attestor_dids': [_DID_A]}


# ── guard_defect (개선축, 음성 오라클): 위조/무서명 actor 의 판결 쓰기가 죽었다 ─────────────
def test_spoofed_actor_write_rejected_at_anchored_tier():
    # (1) attestor 선언 anchored 트리: cert 없는 판결 쓰기 = 거부(서명 없인 명령 없음).
    svc, kg = _svc(_ANCHORED)
    with pytest.raises(HTTPException) as ei:
        _submit(svc)
    assert ei.value.status_code in (403, 409), ei.value.status_code
    assert kg.captured == [], '거부됐는데 그래프 쓰기 발생'
    # (2) 미허용 서명자(B, allow-list 밖) = 거부 — 유효 서명이어도 권위 없음.
    svc2, kg2 = _svc(_ANCHORED)
    with pytest.raises(HTTPException):
        _submit(svc2, _cert(_SK_B, _DID_B))
    assert kg2.captured == []
    # (3) sign-X-execute-Y: A 가 metric 0.5 를 서명, 명령을 1.0 으로 변조 = 서명 불일치 거부.
    svc3, kg3 = _svc(_ANCHORED)
    with pytest.raises(HTTPException):
        _submit(svc3, _cert(_SK_A, _DID_A, metric_value=0.5,
                            tamper_after_sign={'metric_value': 1.0}))
    assert kg3.captured == []
    # (4) 남의 did 사칭: B 의 서명에 A 의 did 를 실음 = pubkey 불일치 거부(문자열이 authorship 못 삼).
    svc4, kg4 = _svc(_ANCHORED)
    with pytest.raises(HTTPException):
        _submit(svc4, _cert(_SK_B, _DID_A))
    assert kg4.captured == []
    # (5) stale cert(발급시각 창 초과) = 거부.
    svc5, kg5 = _svc(_ANCHORED)
    with pytest.raises(HTTPException):
        _submit(svc5, _cert(_SK_A, _DID_A, issued_at=_STALE))
    assert kg5.captured == []
    # (6) 거동불변: legacy(무tier·무attestor) 트리는 cert 없이 종전대로 채점.
    svc6, _ = _svc({'assurance_tier': None, 'attestor_dids': None})
    out = _submit(svc6)
    assert out['verdict'] in ('progressive', 'partial', 'equivalent', 'rejected')
    # (7) anchored 여도 attestor 미선언(키 실물 없음) = 잠금 불가(dead-σ 안전) — cert 없이 통과.
    svc7, _ = _svc({'assurance_tier': 'anchored', 'attestor_dids': None})
    assert _submit(svc7)['verdict'] in ('progressive', 'partial', 'equivalent', 'rejected')


# ── guard_mechanism (novel축, 양성 오라클): push-cert 메커니즘 실재 ─────────────────────────
def test_author_derived_from_signature_not_client_string():
    # (1) RFC 8032 공식 테스트벡터(TEST 1·2) — 순수 Ed25519 구현의 현실 앵커.
    sk1 = bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
    pk1 = bytes.fromhex('d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a')
    sig1 = bytes.fromhex('e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155'
                         '5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b')
    assert W.ed25519_public_key(sk1) == pk1
    assert W.ed25519_sign(sk1, b'') == sig1
    assert W.ed25519_verify(pk1, b'', sig1)
    sk2 = bytes.fromhex('4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb')
    pk2 = bytes.fromhex('3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c')
    sig2 = bytes.fromhex('92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da'
                         '085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00')
    assert W.ed25519_sign(sk2, b'\x72') == sig2 and W.ed25519_verify(pk2, b'\x72', sig2)
    assert not W.ed25519_verify(pk2, b'\x73', sig2)   # 메시지 변조 검출
    # (2) did:key 디코더: ed25519 round-trip + secp256k1(0xe701) 거부.
    assert W.did_key_decode(W.did_key_encode(pk1)) == pk1
    secp_did = W._did_key_encode_multicodec(b'\xe7\x01' + b'\x02' + b'\x11' * 32)
    with pytest.raises(W.CertWrongKeyType):
        W.did_key_decode(secp_did)
    # (3) 실 submit 경로: 유효 cert → author 가 *서명에서 유도*되어 스탬프(client 문자열 아님).
    svc, kg = _svc(_ANCHORED)
    out = _submit(svc, _cert(_SK_A, _DID_A))
    assert out['verdict'] in ('progressive', 'partial', 'equivalent', 'rejected')
    _q, params = kg.captured[0][0]
    assert params.get('attested_by_did') == _DID_A, \
        'attested_by_did 가 서명 유도값이 아님(스탬프 부재 = advisory cert 퇴행)'
    assert out.get('attested_by') == _DID_A
    # (4) 명령의 prev_receipt_sha CAS 바인딩 = replay 봉합: 다른 체인 상태를 서명한 cert 는 거부.
    svc2, _ = _svc(_ANCHORED)
    with pytest.raises(HTTPException):
        _submit(svc2, _cert(_SK_A, _DID_A, prev='deadbeef' * 8))   # 실제 포인터는 None
    # (5) 스탬프는 판결 SET 과 *같은 op*(원자) — 별도 후속 write 아님.
    assert 'attested_by_did' in kg.captured[0][0][0], '스탬프가 #M5 원자 op 밖'


# ── 보조 가드 — nonce 헬퍼(무상태 HMAC)·canonical blob 결정론 ──────────────────────────────
def test_nonce_and_blob_are_deterministic_and_constant_time_shaped():
    n1 = W.issue_nonce(b'seed', 'T', '2026-07-02T14:00:00+00:00')
    n2 = W.issue_nonce(b'seed', 'T', '2026-07-02T14:00:00+00:00')
    assert n1 == n2 and W.verify_nonce(b'seed', 'T', '2026-07-02T14:00:00+00:00', n1)
    assert not W.verify_nonce(b'seed2', 'T', '2026-07-02T14:00:00+00:00', n1)   # 다른 seed = 위조
    cmd = dict(tree='T', tag='n', prev_receipt_sha=None, metric_value=1.0, script_sha='s')
    assert W.canonical_cert_blob(cmd, _NOW) == W.canonical_cert_blob(dict(reversed(list(cmd.items()))), _NOW)
