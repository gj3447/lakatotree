"""C1 S3-engine keystone — PredictionReceipt: register_prediction 이 전체 spec 을 내용주소로 봉인한다.

메커니즘(등록-시점 봉인 + 해시-인과 순서):
  register_prediction 이 예측 spec *전체*를 :VerdictReceipt(receipt_kind='prediction') 로 mint 하고
  노드의 current_receipt_sha 포인터를 전진시킨다(genesis 또는 기존 head 에 체인). submit_test_result 는
  이미 e.current_receipt_sha 를 prev 로 봉인하므로(RECEIPT_FIELDS 의 prev_receipt_sha), verdict receipt 가
  prediction receipt 의 sha 를 *내용으로* 커밋 → spec 을 결과에 back-fit 하면 prediction sha 가 바뀌고
  verdict 의 sealed prev 가 끊긴다(ReceiptChainBroken). verdict v1 sha-space 는 불변(인코딩 무변경).

이중가드:
  guard_mechanism (양성) : 등록이 prediction receipt 를 실제로 mint + 포인터 전진 + submit 이 그 위에 체인.
  guard_defect   (음성) : spec 필드 변조 = sha 불일치(tamper self-evident); back-fit spec-swap = 체인 끊김;
                          재등록(409) 경로에서 신규 receipt 0(anti-tuning 가드 보존).

# KG: LakatosTree_C1ExternalVerifier_20260708 / s3-engine-prediction-receipt
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from lakatos.verdicts import (
    PREDICTION_RECEIPT_FIELDS,
    ReceiptChainBroken,
    fold_receipt_chain,
    prediction_content_sha,
)
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn
from server.contexts.tree.schemas import TestResultIn as Result


class _RegKg:
    """register_prediction + submit_test_result 를 실제로 구동하는 stateful KG 더블.

    등록의 guard-WHERE(사후등록 금지·CAS)와 mint(MERGE rec + 포인터 전진)를 충실히 모델 — revert 민감:
    구현이 mint 를 빼먹으면 receipts 가 비고, CAS 를 빼먹으면 stale-prev 등록이 통과해 가드 테스트가 문다.
    """

    def __init__(self):
        self.node = {
            'tag': 'seam', 'verdict': None, 'verdict_source': None, 'node_state': None,
            'pred_registered_at': None, 'current_receipt_sha': None,
        }
        self.receipts: list[dict] = []

    # ── kg() reads/writes (register_prediction 은 self.kg 로 씀) ─────────────────────────
    def __call__(self, query, **p):
        if 't.ontology AS ontology' in query:
            return [{'ontology': None}]
        if 'parent_measured' in query:
            return []
        if 'AS prev_rsha' in query:   # 등록 전 head 읽기(구현이 추가할 read)
            return [{'prev_rsha': self.node['current_receipt_sha']}]
        if 'SET e.pred_metric' in query:   # guarded 등록 write
            n = self.node
            ok = (n.get('verdict_source') != 'scripted'
                  and n.get('pred_registered_at') is None
                  and (n.get('node_state') or 'DRAFT') in p['allowed_from'])
            if 'coalesce(e.current_receipt_sha' in query:   # CAS 절(구현이 추가) 충실 모델
                ok = ok and (n.get('current_receipt_sha') or '') == (p.get('prev_rsha') or '')
            if not ok:
                return []
            n.update(
                pred_metric=p['metric_name'], pred_direction=p['direction'],
                pred_baseline=p['baseline_value'], pred_noise_band=p['noise_band'],
                pred_scale_type=p['scale_type'], pred_novel=p['novel_prediction'],
                pred_closes=p['closes_question'], pred_novel_metric=p['novel_metric'],
                pred_novel_direction=p['novel_direction'], pred_novel_threshold=p['novel_threshold'],
                pred_script_sha=p['judge_script_sha'], pred_credence=p['credence'],
                pred_registered_at=p['ts'], node_state=p['node_state'],
                baseline_lineage=p['baseline_lineage'],
            )
            if 'MERGE (rec:VerdictReceipt' in query and p.get('rsha'):
                rec = {
                    'receipt_sha': p['rsha'], 'receipt_kind': 'prediction',
                    'tree': p['tree'], 'tag': p['tag'],
                    'metric_name': p['metric_name'], 'direction': p['direction'],
                    'baseline_value': p['baseline_value'], 'noise_band': p['noise_band'],
                    'scale_type': p['scale_type'], 'novel_prediction': p['novel_prediction'],
                    'novel_metric': p['novel_metric'], 'novel_direction': p['novel_direction'],
                    'novel_threshold': p['novel_threshold'], 'judge_script_sha': p['judge_script_sha'],
                    'closes_question': p['closes_question'], 'credence': p['credence'],
                    'baseline_lineage': p['baseline_lineage'], 'registered_at': p['ts'],
                    'prev_receipt_sha': p.get('prev_rsha'),
                    'verdict': None, 'verdict_source': None,
                }
                self.receipts.append(rec)
                n['current_receipt_sha'] = p['rsha']
                n['pred_receipt_sha'] = p['rsha']
            return [{'tag': n['tag']}]
        if 'n_visits' in query:
            return []
        if 'pred_metric AS m' in query:   # submit 의 노드 읽기
            n = self.node
            return [{
                'm': n.get('pred_metric'), 'd': n.get('pred_direction'), 'b': n.get('pred_baseline'),
                'nb': n.get('pred_noise_band'), 'scale': n.get('pred_scale_type'),
                'novel': n.get('pred_novel'), 'vsrc': n.get('verdict_source'),
                'nmet': n.get('pred_novel_metric'), 'ndir': n.get('pred_novel_direction'),
                'nthr': n.get('pred_novel_threshold'), 'psha': n.get('pred_script_sha'),
                'pred_registered_at': n.get('pred_registered_at'), 'node_state': n.get('node_state'),
                'judged_at': None, 'existing_metric_value': None,
                'existing_verdict': n.get('verdict'), 'existing_lstat': None,
                'prev_receipt_sha': n.get('current_receipt_sha'),
                'closes': n.get('pred_closes'), 'n_opened': 0, 'hard_core': '',
                'require_novel_anchor': False, 'assurance_tier': None, 'attestor_dids': None,
            }]
        if 'current_receipt_sha AS head' in query:
            return [{'head': self.node['current_receipt_sha'],
                     'cache_verdict': self.node['verdict'],
                     'cache_source': self.node['verdict_source']}]
        if 'HAS_RECEIPT' in query:
            return [dict(r) for r in self.receipts]
        return []

    # ── kg_tx() — submit 의 #M5 CAS op 충실 적용(G1 테스트 _ReceiptKg 동형) ───────────────
    def tx(self, ops):
        q0, params = ops[0]
        if 'MERGE (rec:VerdictReceipt' in q0:
            self.node['verdict'] = params['v']
            self.node['verdict_source'] = 'scripted'
            self.node['current_receipt_sha'] = params['rsha']
            self.receipts.append({'receipt_sha': params['rsha'],
                                  'prev_receipt_sha': params['prev_rsha'],
                                  'verdict': params['v'], 'verdict_source': 'scripted'})
        return [[{'claimed': params.get('tag')}] for _ in ops]


def _svc():
    kg = _RegKg()
    svc = JudgementService(kg=kg, kg_tx=kg.tx, hist=lambda *a, **k: None,
                           foundation=lambda n: None, reproducible_for_node=lambda n, t: None)
    return svc, kg


def _pred(baseline_value: float = 10.0) -> PredictionIn:
    return PredictionIn(metric_name='seam', direction='lower', baseline_value=baseline_value,
                        noise_band=0.0, scale_type='ratio', novel_prediction='novel claim',
                        novel_metric='novelaxis', novel_direction='higher', novel_threshold=1.0,
                        closes_question='q-x')


# ── guard_mechanism (양성 오라클) ─────────────────────────────────────────────────────────
def test_register_prediction_mints_content_addressed_prediction_receipt():
    """등록이 spec 전체를 봉인한 prediction receipt 를 mint 하고 포인터를 전진시킨다(genesis)."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    assert len(kg.receipts) == 1, f'등록이 receipt 를 mint 안 함: {kg.receipts}'
    rec = kg.receipts[0]
    assert rec['receipt_kind'] == 'prediction'
    assert rec['prev_receipt_sha'] is None, 'fresh 노드의 prediction receipt 는 genesis'
    # 내용주소: 저장된 필드에서 sha 재유도 == 저장된 receipt_sha (mint 의식이 아니라 재유도 가능)
    assert prediction_content_sha(rec) == rec['receipt_sha'], 'prediction sha 재유도 불일치'
    assert kg.node['current_receipt_sha'] == rec['receipt_sha'], '포인터 미전진'
    # spec 이 실제로 봉인 필드셋에 들어있다(부분봉인 금지)
    for f in ('metric_name', 'direction', 'baseline_value', 'noise_band', 'scale_type',
              'novel_metric', 'novel_direction', 'novel_threshold', 'closes_question'):
        assert f in PREDICTION_RECEIPT_FIELDS, f'{f} 가 봉인 필드셋에 없음(부분봉인)'


def test_submit_chains_verdict_receipt_onto_prediction_receipt():
    """submit 의 verdict receipt 가 prediction receipt 를 prev 로 봉인 → 해시-인과 순서(spec ≺ verdict)."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    pred_sha = kg.node['current_receipt_sha']
    out = svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    assert out['verdict'] == 'progressive', out
    heads = [r for r in kg.receipts if r.get('verdict_source') == 'scripted']
    assert len(heads) == 1
    assert heads[0]['prev_receipt_sha'] == pred_sha, 'verdict 가 prediction sha 를 봉인 안 함(back-fit 살아있음)'
    # 체인 fold: head(verdict) → prediction(genesis) 도달 (무결)
    v = svc.verify_verdict_chain('T', 'seam')
    assert v['ok'] and v['from_receipt'] and v['rederived'] == 'progressive', v


def test_registered_unjudged_node_chain_folds_clean():
    """등록만 된(미채점) 노드: head=prediction receipt, fold verdict=None == cache None (거동 보존)."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    v = svc.verify_verdict_chain('T', 'seam')
    assert v['ok'] and v['rederived'] is None, v


def test_golden_cross_check_c1verify_prediction_sha_byte_parity():
    """golden: 엔진 prediction_content_sha == c1verify 재구현(외부검증자 copy-fidelity)."""
    import c1verify.receipts as CR
    base = {k: None for k in PREDICTION_RECEIPT_FIELDS}
    corpus = [
        dict(base, receipt_kind='prediction', tree='T', tag='n', metric_name='m', direction='lower',
             baseline_value=10.0, noise_band=0.0, scale_type='ratio', registered_at='2026-07-10T00:00:00+00:00'),
        dict(base, receipt_kind='prediction', tree='T', tag='n', baseline_value=3),      # int→float 정규화
        dict(base, receipt_kind='prediction', tree='T', tag='n', baseline_value=3.0),    # == 위와 동일 sha 요구
        dict(base, receipt_kind='prediction', tree='T', tag='유니코드', novel_metric='재현율_δ',
             credence=0.7, prev_receipt_sha='a' * 64, registered_at=1720483200),          # 비-str ts 정규화
    ]
    for f in corpus:
        assert prediction_content_sha(f) == CR.prediction_content_sha(f), f'byte-parity 붕괴: {f}'
    assert prediction_content_sha(corpus[1]) == prediction_content_sha(corpus[2]), 'int/float 정규화 발산'


# ── guard_defect (음성 오라클) ────────────────────────────────────────────────────────────
def test_tampering_sealed_spec_field_breaks_content_sha():
    """봉인 후 spec 필드 변조 = sha 재유도 불일치(tamper self-evident — 정책이 아니라 표현 불가능)."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    rec = dict(kg.receipts[0])
    rec['baseline_value'] = 0.001   # 결과를 보고 baseline 을 back-fit
    assert prediction_content_sha(rec) != rec['receipt_sha'], '변조가 sha 에 안 잡힘'


def test_spec_swap_after_verdict_breaks_the_chain():
    """back-fit 공격: verdict 이후 prediction receipt 를 갈아끼우면(자기정합 sha 라도) 체인이 끊긴다."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    pred = next(r for r in kg.receipts if r.get('receipt_kind') == 'prediction')
    swapped = dict(pred, baseline_value=0.001)
    swapped['receipt_sha'] = prediction_content_sha(swapped)   # 자기정합으로 재발행
    chain = [swapped if r is pred else r for r in kg.receipts]
    with pytest.raises(ReceiptChainBroken):
        fold_receipt_chain(chain, kg.node['current_receipt_sha'])


def test_re_registration_still_409_and_mints_nothing():
    """anti-tuning 보존: 재등록은 409 그대로 + 신규 receipt 0(mint 가 가드 밖으로 새지 않음)."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    n_before = len(kg.receipts)
    with pytest.raises(HTTPException) as ei:
        svc.register_prediction('T', 'seam', _pred(baseline_value=99.0))
    assert ei.value.status_code == 409
    assert len(kg.receipts) == n_before, '409 경로가 receipt 를 mint 함(가드 누수)'
