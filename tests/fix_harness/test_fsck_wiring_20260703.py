"""R6-FSCK — fsck 배선 열차 가드 (후속 PROM 2026-07-03: '순수 모듈 착륙+배선 0' 고아 봉합).

  guard_defect(음성)     : test_forceful_without_receipt_is_audit_finding
        — FORCEFUL source(scripted/engine/…) verdict 인데 :VerdictReceipt 포인터가 없는 레코드
          (라이브 159건 + 333v2 손기록 10건의 장르)가 열거 finding 으로 표면화된다. G1 이전/우회
          write 의 원장 공백이 '존재하지 않는 것처럼' 침묵하지 않는다.
  guard_mechanism(양성)  : test_fsck_verb_same_checker_and_seat_rejects_before_tx
        — ①전수감사 verb 가 fsck_node *같은 callable* 를 쓴다(monkeypatch 센티널 반사 — 재구현 배선
          차단, G8 'audit==ingest' 주장의 실배선) ②submit pre-commit 시트: boundary_fsck 가 거부하면
          kg_tx 호출 0(거부는 쓰기 *전* — 원자성 무훼손; 가치서사는 활성필터가 아닌 '드리프트 보험')
          ③skiplist 는 git-추적 docs/fsck_skiplist.json 에서 로드되어 감사·경계에 동일 주입,
          record content-sha 결정론(1필드 변조=면제 소멸).

# KG: LakatosTree_GitAbsorption_20260702 / followup-R6-fsck-wiring
"""
from __future__ import annotations

import importlib
import json
import os

import pytest
from fastapi import HTTPException

import server.contexts.audit.fsck as F
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import TestResultIn as Result


def load_app():
    os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
    os.environ.setdefault('NEO4J_USER', 'neo4j')
    os.environ.setdefault('NEO4J_PASSWORD', 'test')
    return importlib.import_module('server.app')


_LEGACY_FORCEFUL = {'verdict': 'progressive', 'verdict_source': 'scripted',
                    'pred_registered_at': '2026-06-20', 'judged_at': '2026-06-20T00:00:00Z',
                    'source_trust': 1.0, 'assurance_tier_resolved': 'legacy'}


# ── guard_defect (음성): 원장 공백이 열거 finding 으로 ─────────────────────────────────────
def test_forceful_without_receipt_is_audit_finding():
    ids = {f.check_id for f in F.fsck_node(dict(_LEGACY_FORCEFUL))}
    assert 'FORCEFUL_SOURCE_WITHOUT_RECEIPT' in ids, '원장 공백(무영수증 FORCEFUL)이 침묵'
    # 영수증 포인터 보유 = 발화 없음.
    ok = dict(_LEGACY_FORCEFUL, current_receipt_sha='a1' * 32)
    assert 'FORCEFUL_SOURCE_WITHOUT_RECEIPT' not in {f.check_id for f in F.fsck_node(ok)}
    # 비-FORCEFUL source(draft/conjecture) = 범위 밖(원장 의무 없음).
    draft = {'verdict': 'proof', 'verdict_source': None}
    assert 'FORCEFUL_SOURCE_WITHOUT_RECEIPT' not in {f.check_id for f in F.fsck_node(draft)}


# ── guard_mechanism (양성): verb·시트·skiplist 배선 실재 ───────────────────────────────────
def test_fsck_verb_same_checker_and_seat_rejects_before_tx(monkeypatch, tmp_path):
    app = load_app()
    # (A) verb — callable 동일성: fsck_node 를 센티널로 갈아끼우면 verb 산출이 그대로 반사돼야
    #     (재구현/복사 배선이면 반사 안 됨 = RED).
    monkeypatch.setattr(app, 'kg', lambda q, **p: [{'name': 'T1'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: {'nodes': [{'tag': 'n1', 'verdict': 'proof'}],
                                                     'frontier': []})
    sentinel = F.Finding('SENTINEL_CHECK', F.ERROR, 'callable-identity probe')
    monkeypatch.setattr(F, 'fsck_node', lambda rec, **kw: [sentinel])
    out = app.ops_fsck()
    assert out['findings_count'] == 1 and out['findings'][0]['check_id'] == 'SENTINEL_CHECK', \
        f'verb 가 fsck_node 동일 callable 을 쓰지 않음: {out}'
    assert out['counts'] == {'SENTINEL_CHECK': 1}
    # (B) skiplist 파이프라인: emit → 사람검토 파일 → 재감사 시 해당 레코드만 면제(결정론 sha).
    monkeypatch.undo()
    monkeypatch.setattr(app, 'kg', lambda q, **p: [{'name': 'T1'}])
    monkeypatch.setattr(app, 'tree_data', lambda n: {'nodes': [dict(_LEGACY_FORCEFUL, tag='legacy1')],
                                                     'frontier': []})
    emitted = app.ops_fsck(emit_skiplist=True)
    assert emitted['findings_count'] >= 1 and emitted['skiplist_candidates'], emitted
    cand = emitted['skiplist_candidates'][0]
    skfile = tmp_path / 'fsck_skiplist.json'
    skfile.write_text(json.dumps({'entries': [{'sha': cand['sha'], 'tree': 'T1', 'tag': 'legacy1',
                                               'reason': 'pre-G1 legacy'}]}), encoding='utf-8')
    monkeypatch.setenv('LAKATOS_FSCK_SKIPLIST', str(skfile))
    after = app.ops_fsck()
    assert after['findings_count'] == 0 and after['skiplist_size'] == 1, \
        f'skiplist 면제 미적용(감사 주입 실패): {after}'
    # 결정론/면제소멸: 레코드 1필드 변조 → sha 이탈 → 재발화.
    monkeypatch.setattr(app, 'tree_data',
                        lambda n: {'nodes': [dict(_LEGACY_FORCEFUL, tag='legacy1', verdict='rejected')],
                                   'frontier': []})
    revived = app.ops_fsck()
    assert revived['findings_count'] >= 1, '변조된 레코드가 여전히 면제됨(내용주소 소멸 규율 위반)'
    # (C) submit pre-commit 시트: boundary_fsck 거부 → 422 *그리고* kg_tx 호출 0(쓰기 전 거부).
    calls = {'tx': 0}
    pred = {'m': 'seam', 'd': 'lower', 'b': 10.0, 'nb': 0.0, 'scale': 'ratio', 'novel': '',
            'vsrc': None, 'nmet': None, 'ndir': None, 'nthr': None, 'psha': None, 'closes': None,
            'n_opened': 0, 'pred_registered_at': '2026-07-03', 'node_state': 'PREDICTED',
            'judged_at': None, 'existing_metric_value': None, 'hard_core': '',
            'require_novel_anchor': False, 'assurance_tier': None, 'attestor_dids': None,
            'prev_receipt_sha': None}

    def kg(query, **p):
        return [dict(pred)] if 'pred_metric AS m' in query else []

    def kg_tx(ops):
        calls['tx'] += 1
        return [[{'claimed': 'seam'}] for _ in ops]

    svc = JudgementService(kg=kg, kg_tx=kg_tx, hist=lambda *a, **k: None,
                           foundation=lambda *a, **k: None, reproducible_for_node=lambda *a, **k: None)
    fatal = F.Finding('SENTINEL_FATAL', F.FATAL, 'seat probe')
    monkeypatch.setattr(F, 'boundary_fsck', lambda rec, **kw: [fatal])
    with pytest.raises(HTTPException) as e:
        svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline'))
    assert e.value.status_code == 422 and 'SENTINEL_FATAL' in str(e.value.detail)
    assert calls['tx'] == 0, '거부가 쓰기 *후*(원자성 훼손) — 시트가 kg_tx 앞에 있지 않음'
    # 시트 통과(정상 레코드) 시 제출은 종전대로.
    monkeypatch.setattr(F, 'boundary_fsck', lambda rec, **kw: [])
    out2 = svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline'))
    assert out2['verdict'] in ('progressive', 'partial', 'equivalent', 'rejected')
    assert calls['tx'] == 1
