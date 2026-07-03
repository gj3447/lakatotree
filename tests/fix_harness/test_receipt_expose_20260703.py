"""R5-EXPOSE — 체인 노출·검증 배선 + G10 열쇠공 가드 (후속 PROM 2026-07-03).

  guard_defect(음성)     : test_verify_route_detects_cache_tamper_not_500
        — 라이브 체인 무결성을 HTTP 로 물을 수 있다: 캐시 변조 = ok:false(검출), dangling 포인터
          (변조/부패) = 500 이 아니라 열거 finding(RECEIPT_CHAIN_MISMATCH, G8 SSOT 어휘). 라우트가
          없으면(현행) 404 = 아무도 라이브 원장을 검증 못 함(R4 가 닫은 창의 관측구 부재).
  guard_mechanism(양성)  : test_keysmith_builds_verifiable_cert
        — G10 자물쇠의 열쇠공 실재: keygen(무작위 시드→did:key) → build_write_cert(명령 서명) →
          verify_write_cert 왕복 OK + 서명 후 명령 변조 = CertCommandMismatch. attestor 를 켜는 순간
          전면 403 이던 갭(서명 도구 부재)이 닫힘.

R4 착륙 *후에만* 안전(선배선=정직 승격이 거짓 변조 알람) — R4 가드가 이 파일의 선행 계약.

# KG: LakatosTree_GitAbsorption_20260702 / followup-R5-expose
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import pytest

from lakatos import write_cert as W
from server.contexts.audit import fsck as F
from server.contexts.tree.judgement import create_judgement_router
from server.contexts.tree.judgement_service import JudgementService


class _ChainKg:
    """load_receipt_chain 읽기 계약의 상태형 더블 — 체인/캐시를 시험자가 조작."""

    def __init__(self):
        self.head = 'aa' * 32
        self.cache_verdict = 'progressive'
        self.receipts = [{'receipt_sha': 'aa' * 32, 'prev_receipt_sha': None,
                          'verdict': 'progressive', 'verdict_source': 'scripted'}]

    def __call__(self, query, **p):
        if 'current_receipt_sha AS head' in query:
            return [{'head': self.head, 'cache_verdict': self.cache_verdict,
                     'cache_source': 'scripted'}]
        if 'HAS_RECEIPT' in query:
            return [dict(r) for r in self.receipts]
        return []


def _client(kg) -> TestClient:
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [[{'ok': 1}] for _ in ops],
                           hist=lambda *a, **k: None, foundation=lambda *a, **k: None,
                           reproducible_for_node=lambda *a, **k: None)
    app = FastAPI()
    app.include_router(create_judgement_router(lambda: svc))
    return TestClient(app)


# ── guard_defect (음성): 관측구 실재 — 변조는 검출, 부패는 500 아닌 열거 finding ─────────────
def test_verify_route_detects_cache_tamper_not_500():
    kg = _ChainKg()
    c = _client(kg)
    # (1) 건강 체인: verify 정방향(rederived==cache, ok:true) + receipts GET 이 체인을 공시.
    r = c.get('/api/tree/T/node/n/receipts/verify')
    assert r.status_code == 200 and r.json()['ok'] is True, r.text
    rc = c.get('/api/tree/T/node/n/receipts')
    assert rc.status_code == 200 and rc.json()['head'] == 'aa' * 32
    assert len(rc.json()['receipts']) == 1
    # (2) 캐시 변조(체인 불변) → ok:false + 재유도값 공시.
    kg.cache_verdict = 'CANONICAL'   # 원장 없는 승격 위장
    v = c.get('/api/tree/T/node/n/receipts/verify').json()
    assert v['ok'] is False and v['rederived'] == 'progressive', v
    # (3) dangling 포인터(변조/부패) → 500 금지, G8 SSOT 어휘의 열거 finding.
    kg.head = 'dd' * 32
    r3 = c.get('/api/tree/T/node/n/receipts/verify')
    assert r3.status_code == 200, f'부패가 500 으로 샘(tolerant-reader 위반): {r3.status_code}'
    body = r3.json()
    assert body['ok'] is False and body.get('finding') == 'RECEIPT_CHAIN_MISMATCH', body
    assert 'RECEIPT_CHAIN_MISMATCH' in F._SEVERITY, 'finding 어휘가 fsck SSOT 밖(G8 규율 위반)'


def test_fsck_detects_dangling_pointer_on_enriched_record():
    """감사 스윕용 record-level 검출: receipts 동봉(enriched) 레코드의 head 이탈 = finding.
    비동봉 레코드는 발화 없음(기존 fsck 계약 비파괴)."""
    bad = {'verdict': 'proof', 'current_receipt_sha': 'x1' * 32, 'receipts': []}
    assert 'RECEIPT_CHAIN_MISMATCH' in {f.check_id for f in F.fsck_node(bad)}
    ok = {'verdict': 'proof', 'current_receipt_sha': 'x1' * 32,
          'receipts': [{'receipt_sha': 'x1' * 32}]}
    assert 'RECEIPT_CHAIN_MISMATCH' not in {f.check_id for f in F.fsck_node(ok)}
    plain = {'verdict': 'proof', 'current_receipt_sha': 'x1' * 32}   # 비동봉 = 판단 보류
    assert 'RECEIPT_CHAIN_MISMATCH' not in {f.check_id for f in F.fsck_node(plain)}


# ── guard_mechanism (양성): 열쇠공 — keygen→sign→verify 폐루프 ─────────────────────────────
def test_keysmith_builds_verifiable_cert():
    secret_hex, did = W.keygen()
    assert did.startswith('did:key:z') and len(bytes.fromhex(secret_hex)) == 32
    command = dict(tree='T', tag='n', prev_receipt_sha='aa' * 32,
                   metric_value=1.5, script_sha='s1' * 32, verb='submit_test_result')  # AG5-IDENT verb 바인딩
    cert = W.build_write_cert(bytes.fromhex(secret_hex), command)
    assert cert['signer_did'] == did and cert['command'] == command
    # 왕복: 서버측 검증 통과(allow-list 에 서명자 실재).
    out = W.verify_write_cert(cert, expected_command=command, allowlist=[did])
    assert out['signer_did'] == did
    # sign-X-execute-Y 두 얼굴 모두 거부: ①서명 후 명령 변조 = 서명이 blob 을 못 덮음(SignatureInvalid),
    # ②멀쩡한 cert 로 다른 요청 실행 시도 = 명령 바인딩 불일치(CommandMismatch).
    tampered = dict(cert, command=dict(command, metric_value=9.9))
    with pytest.raises(W.CertSignatureInvalid):
        W.verify_write_cert(tampered, expected_command=dict(command, metric_value=9.9),
                            allowlist=[did])
    with pytest.raises(W.CertCommandMismatch):
        W.verify_write_cert(cert, expected_command=dict(command, metric_value=9.9),
                            allowlist=[did])
    # 미허용 서명자 = 거부(권위 필터는 allow-list).
    _, other_did = W.keygen()
    with pytest.raises(W.CertSignerNotAllowed):
        W.verify_write_cert(cert, expected_command=command, allowlist=[other_did])
