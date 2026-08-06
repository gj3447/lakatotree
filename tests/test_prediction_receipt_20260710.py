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

import server.contexts.tree.judgement_service as judgement_module
from lakatos.io.replay import ProducerReplayVerdict
from lakatos.verdicts import (
    PREDICTION_RECEIPT_FIELDS,
    RECEIPT_FIELDS,
    ReceiptChainBroken,
    fold_receipt_chain,
    prediction_content_sha,
)
from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn
from server.contexts.tree.schemas import TestResultIn as Result
from server.ports import GuardedKgOps, KgTxGuardFailed


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
        self.outboxes: dict[str, dict] = {}
        self.questions = {
            'q-x': {
                'status': 'OPEN', 'n_visits': 0, 'closed_by': [], 'closed_events': [],
            }
        }

    # ── kg() reads/writes (register_prediction 은 self.kg 로 씀) ─────────────────────────
    def __call__(self, query, **p):
        if 'properties(head_receipt) AS head_receipt' in query:
            receipt_sha = self.node.get('current_receipt_sha')
            receipt = next(
                (r for r in self.receipts if r.get('receipt_sha') == receipt_sha),
                None,
            )
            direct = self.outboxes.get(f'ob-verdict-{receipt_sha}')
            predecessors = [
                dict(row)
                for row in self.outboxes.values()
                if row.get('status') == 'pending'
                and row.get('demoted_receipt_sha') == receipt_sha
            ]
            return [{
                'head_receipt': (dict(receipt) if receipt is not None else None),
                'direct_outbox': (dict(direct) if direct is not None else None),
                'pending_predecessors': predecessors,
            }]
        if 't.ontology AS ontology' in query:
            return [{'ontology': None}]
        if 'parent_measured' in query:
            return []
        if 'AS prev_rsha' in query:   # 등록 전 head 읽기(구현이 추가할 read)
            pred_sha = self.node.get('pred_receipt_sha')
            pred = next(
                (r for r in self.receipts if r.get('receipt_sha') == pred_sha),
                {},
            )
            return [{
                'prev_rsha': self.node['current_receipt_sha'],
                'pred_receipt_sha': pred_sha,
                'pred_registered_at': pred.get('registered_at'),
                'pred_prev_receipt_sha': pred.get('prev_receipt_sha'),
                'pred_baseline_lineage': pred.get('baseline_lineage'),
                'pred_anchor_bundle_sha256': pred.get('anchor_bundle_sha256'),
                'pred_anchor_bundle_json': pred.get('anchor_bundle_json'),
                'pred_history_payload_sha256': pred.get('history_payload_sha256'),
                'pred_history_payload': (
                    self.outboxes.get(f'ob-prediction-register-{pred_sha}', {})
                    .get('payload')
                ),
                'pred_anchor_verified': self.node.get('pred_anchor_verified'),
            }]
        if 'SET e.pred_metric' in query:   # guarded 등록 write
            n = self.node
            target = p.get('closes_question') or ''
            question = self.questions.get(target) if target else None
            ok = (n.get('verdict_source') != 'scripted'
                  and n.get('pred_registered_at') is None
                  and (n.get('node_state') or 'DRAFT') in p['allowed_from'])
            prior = self.outboxes.get(p.get('history_event_id'))
            if prior is not None:
                ok = ok and (
                    prior.get('tree') == p['tree']
                    and prior.get('op') == 'prediction_register'
                    and prior.get('node_tag') == p['tag']
                    and prior.get('payload') == p['history_payload_json']
                    and prior.get('reason') == 'prediction_register_commit_intent'
                    and prior.get('receipt_sha') == p['rsha']
                    and prior.get('created_at') is not None
                    and prior.get('adopted_by') is None
                    and prior.get('adopted_at') is None
                    and prior.get('causal_group') is None
                    and prior.get('causal_index') is None
                    and prior.get('request_sha256') is None
                    and prior.get('demoted_tag') is None
                    and prior.get('demoted_receipt_sha') is None
                    and (
                        (prior.get('status') == 'pending'
                         and prior.get('applied_at') is None)
                        or (prior.get('status') == 'applied'
                            and prior.get('applied_at') is not None)
                    )
                )
            if 'coalesce(e.current_receipt_sha' in query:   # CAS 절(구현이 추가) 충실 모델
                ok = ok and (n.get('current_receipt_sha') or '') == (p.get('prev_rsha') or '')
            if target:
                ok = ok and question is not None and question['status'] == 'OPEN'
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
                pred_question_bound=(not target or question is not None),
            )
            if question is not None:
                question['n_visits'] += 1
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
                    'anchor_bundle_sha256': p.get('anchor_bundle_sha256'),
                    'anchor_bundle_json': p.get('anchor_bundle_json'),
                    'history_payload_sha256': p.get('prediction_payload_sha256'),
                    'verdict': None, 'verdict_source': None,
                }
                self.receipts.append(rec)
                n['current_receipt_sha'] = p['rsha']
                n['pred_receipt_sha'] = p['rsha']
            if p.get('anchor_rows'):
                n.update(
                    pred_anchor_verified=True,
                    pred_anchor_gen_time=p.get('anchor_gen_time'),
                    pred_anchor_quorum=p.get('anchor_quorum'),
                    pred_anchor_threshold=p.get('anchor_threshold'),
                )
            if 'MERGE (o:OutboxEntry' in query:
                self.outboxes.setdefault(p['history_event_id'], {
                    'id': p['history_event_id'],
                    'tree': p['tree'],
                    'op': 'prediction_register',
                    'node_tag': p['tag'],
                    'payload': p['history_payload_json'],
                    'status': 'pending',
                    'created_at': p['ts'],
                    'reason': 'prediction_register_commit_intent',
                    'applied_at': None,
                    'receipt_sha': p['rsha'],
                })
            return [{'tag': n['tag']}]
        if 'MATCH (o:OutboxEntry {id:$id})' in query:
            entry = self.outboxes.get(p['id'])
            return [dict(entry)] if entry is not None else []
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
        if 'test_o:OutboxEntry' in query:
            receipt_sha = self.node.get('current_receipt_sha')
            test_o = self.outboxes.get(f'ob-test-result-{receipt_sha}', {})
            close_o = self.outboxes.get(f'ob-question-close-{receipt_sha}', {})
            receipt = next(
                (row for row in self.receipts if row.get('receipt_sha') == receipt_sha),
                {},
            )
            question = self.questions.get(receipt.get('target_id') or 'q-x', {})
            return [{
                'receipt_sha': receipt_sha,
                'verdict_source': self.node.get('verdict_source'),
                'verdict': self.node.get('verdict'),
                'lakatos_status': self.node.get('lakatos_status'),
                'metric_value': self.node.get('metric_value'),
                'measurement_grade': self.node.get('measurement_grade'),
                'replay_status': self.node.get('replay_status'),
                'assurance_tier_resolved': self.node.get('assurance_tier_resolved'),
                'attested_by_did': self.node.get('attested_by_did'),
                'measurement_lock_sha': self.node.get('measurement_lock_sha'),
                'eureka_felt': self.node.get('eureka_felt'),
                'eureka_true': self.node.get('eureka_true'),
                'eureka_hallucinated': self.node.get('eureka_hallucinated'),
                'eureka_reasons': self.node.get('eureka_reasons'),
                'eureka_bf': self.node.get('eureka_bf'),
                'bound_receipt_sha': receipt.get('receipt_sha'),
                'receipt_kind': receipt.get('receipt_kind'),
                **{f'receipt_{key}': receipt.get(key) for key in RECEIPT_FIELDS},
                'target_id': receipt.get('target_id'),
                'engine_rule_sha': receipt.get('engine_rule_sha'),
                'attestor_dids': [],
                'question_state': question.get('status'),
                'question_closed_by': question.get('closed_by'),
                'question_closed_events': question.get('closed_events'),
                'closure_id': (receipt_sha if close_o else None),
                'closure_closed_by': ('seam' if close_o else None),
                'closure_at': (receipt.get('judged_at') if close_o else None),
                'closure_tree': ('T' if close_o else None),
                'closure_question': (receipt.get('target_id') if close_o else None),
                'closure_trigger': ('ADJUDICATED' if close_o else None),
                'closure_verdict': (receipt.get('verdict') if close_o else None),
                'closure_receipt_sha': (receipt_sha if close_o else None),
                'closure_bound_count': (1 if close_o else 0),
                'closure_global_count': (1 if close_o else 0),
                'closes_rel_count': (1 if close_o else 0),
                'closes_rel_receipt_sha': (receipt_sha if close_o else None),
                'closes_rel_verdict': (receipt.get('verdict') if close_o else None),
                'closes_rel_at': (receipt.get('judged_at') if close_o else None),
                'group_outboxes': [
                    dict(row)
                    for row in sorted(
                        self.outboxes.values(),
                        key=lambda entry: (
                            entry.get('causal_index', -1), entry.get('id', '')
                        ),
                    )
                    if row.get('causal_group') == receipt_sha
                ],
                **{f'test_{key}': value for key, value in test_o.items()
                   if key in {'event_id'}},
                'test_event_id': test_o.get('id'),
                'test_tree': test_o.get('tree'),
                'test_op': test_o.get('op'),
                'test_tag': test_o.get('node_tag'),
                'test_payload': test_o.get('payload'),
                'test_status': test_o.get('status'),
                'test_created_at': test_o.get('created_at'),
                'test_reason': test_o.get('reason'),
                'test_applied_at': test_o.get('applied_at'),
                'test_receipt_sha': test_o.get('receipt_sha'),
                'test_causal_group': test_o.get('causal_group'),
                'test_causal_index': test_o.get('causal_index'),
                'request_sha256': test_o.get('request_sha256'),
                'close_event_id': close_o.get('id'),
                'close_tree': close_o.get('tree'),
                'close_op': close_o.get('op'),
                'close_tag': close_o.get('node_tag'),
                'close_payload': close_o.get('payload'),
                'close_status': close_o.get('status'),
                'close_created_at': close_o.get('created_at'),
                'close_reason': close_o.get('reason'),
                'close_applied_at': close_o.get('applied_at'),
                'close_receipt_sha': close_o.get('receipt_sha'),
                'close_causal_group': close_o.get('causal_group'),
                'close_causal_index': close_o.get('causal_index'),
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
        first = {'claimed': params.get('tag')}
        if 'MERGE (rec:VerdictReceipt' in q0:
            question = self.questions.get(params.get('target_id'))
            if params.get('has_target') and question is None:
                return [[] if index == 0 else [] for index, _ in enumerate(ops)]
            before_state = (question or {}).get('status')
            if params.get('has_target') and before_state not in {'OPEN', 'CLOSED'}:
                # Production Cypher guards this after locking q and before any verdict/receipt write.
                return [[] if index == 0 else [] for index, _ in enumerate(ops)]
            self.node['verdict'] = params['v']
            self.node['verdict_source'] = 'scripted'
            self.node['current_receipt_sha'] = params['rsha']
            self.node.update(
                lakatos_status=params.get('lstat'),
                metric_value=params.get('mv'),
                measurement_grade=params.get('mg'),
                replay_status=params.get('replay_status'),
                assurance_tier_resolved=params.get('atier'),
                attested_by_did=params.get('attested_by_did'),
                measurement_lock_sha=params.get('lsha'),
                eureka_felt=(params.get('eu_closed_felt') if first.get('question_closed')
                             else params.get('eu_open_felt')),
                eureka_true=(params.get('eu_closed_true') if first.get('question_closed')
                             else params.get('eu_open_true')),
                eureka_hallucinated=(params.get('eu_closed_hall') if first.get('question_closed')
                                     else params.get('eu_open_hall')),
                eureka_reasons=(params.get('eu_closed_reasons') if first.get('question_closed')
                                else params.get('eu_open_reasons')),
                eureka_bf=(params.get('eu_closed_bf') if first.get('question_closed')
                           else params.get('eu_open_bf')),
            )
            self.receipts.append({
                'receipt_sha': params['rsha'],
                'tree': params['tree'], 'tag': params['tag'],
                'target_id': params.get('target_id'),
                'verdict': params['v'], 'verdict_source': 'scripted',
                'metric_name': params.get('mn'), 'metric_value': params.get('mv'),
                'novel_confirmed': params.get('novel'),
                'lakatos_status': params.get('lstat'), 'judged_at': params.get('ts'),
                'judge_script_sha': params.get('sha'),
                'prev_receipt_sha': params.get('prev_rsha'),
                'measurement_grade': params.get('mg'),
                'engine_rule_sha': params.get('engine_rule_sha'),
                'comment_sha': params.get('csha'),
                'replay_status': params.get('replay_status'),
                'replay_reason': params.get('replay_reason'),
                'regenerated_metric': params.get('regenerated_metric'),
                'judge_script_path': params.get('script'),
                'result_path': params.get('rp'),
                'result_sha256': params.get('result_sha256'),
                'measurement_lock_sha': params.get('lsha'),
                'source_script_path': params.get('source_script'),
                'source_result_path': params.get('source_rp'),
                'history_payload_sha256': params.get('history_payload_sha256'),
            })
            closure_query_complete = all(token in q0 for token in (
                'QuestionClosure', 'CLOSES_QUESTION', 'question_before_state',
                'CAUSED_BY', 'SET q._cas',
            ))
            if (closure_query_complete and params.get('close_question')
                    and question and question['status'] == 'OPEN'):
                question['status'] = 'CLOSED'
                question['n_visits'] += 1
                question['closed_by'].append(params['tag'])
                question['closed_events'].append(params['closure_id'])
                first.update(question_before_state=before_state,
                             question_closed=True, question_state='CLOSED')
            else:
                first.update(question_before_state=before_state, question_closed=False,
                             question_state=(question or {}).get('status'))
            if params.get('test_result_event_id'):
                self.outboxes[params['test_result_event_id']] = {
                    'id': params['test_result_event_id'],
                    'tree': params['tree'],
                    'op': 'test_result',
                    'node_tag': params['tag'],
                    'payload': params['test_result_payload'],
                    'status': 'pending',
                    'created_at': params['ts'],
                    'reason': 'test_result_commit_intent',
                    'applied_at': None,
                    'receipt_sha': params['rsha'],
                    'causal_group': params['rsha'],
                    'causal_index': 0,
                    'request_sha256': params['submit_request_sha256'],
                }
            if first.get('question_closed') and params.get('question_close_event_id'):
                self.outboxes[params['question_close_event_id']] = {
                    'id': params['question_close_event_id'],
                    'tree': params['tree'],
                    'op': 'question_close',
                    'node_tag': params['tag'],
                    'payload': params['question_close_payload'],
                    'status': 'pending',
                    'created_at': params['ts'],
                    'reason': 'question_close_commit_intent',
                    'applied_at': None,
                    'receipt_sha': params['rsha'],
                    'causal_group': params['rsha'],
                    'causal_index': 1,
                }
        return [[first] if index == 0 else [] for index, _ in enumerate(ops)]


class _ConcurrentExactPredictionKg(_RegKg):
    """Commit an identical winner at the registration CAS, then report a miss."""

    def __init__(self):
        super().__init__()
        self.raced = False

    def __call__(self, query, **params):
        if 'SET e.pred_metric' in query and not self.raced:
            self.raced = True
            committed = super().__call__(query, **params)
            assert committed
            return []
        return super().__call__(query, **params)


def _svc(hist=None, *, producer=None):
    kg = _RegKg()
    svc = JudgementService(
        kg=kg,
        kg_tx=kg.tx,
        hist=hist or (lambda *a, **k: None),
        foundation=lambda n: None,
        reproducible_for_node=lambda n, t: None,
        producer_replay_submit=producer,
    )
    return svc, kg


def _verified_progressive_result(tmp_path):
    script = tmp_path / "score.py"
    result = tmp_path / "result.json"
    novel = tmp_path / "novel.py"
    script.write_text("print(1.0)\n", encoding="utf-8")
    result.write_text('{"metric":1.0}\n', encoding="utf-8")
    novel.write_text("print(1.0)\n", encoding="utf-8")
    payload = Result(
        metric_value=1.0,
        script=str(script),
        result_path=str(result),
        novel_measured=1.0,
        novel_script=str(novel),
        lakatos_anomaly=True,
        lakatos_consequence=True,
        lakatos_excess=True,
        lakatos_hardcore=True,
        ce_novel_corroborated=True,
    )
    producer = lambda *_args: ProducerReplayVerdict(  # noqa: E731
        True, 1.0, 1.0, "externally_verified"
    )
    return payload, producer


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
    projected = svc.load_receipt_chain('T', 'seam')['receipts'][0]
    assert prediction_content_sha(projected) == projected['receipt_sha']
    # spec 이 실제로 봉인 필드셋에 들어있다(부분봉인 금지)
    for f in ('metric_name', 'direction', 'baseline_value', 'noise_band', 'scale_type',
              'novel_metric', 'novel_direction', 'novel_threshold', 'closes_question'):
        assert f in PREDICTION_RECEIPT_FIELDS, f'{f} 가 봉인 필드셋에 없음(부분봉인)'


def test_concurrent_identical_prediction_cas_loser_adopts_winner_receipt():
    kg = _ConcurrentExactPredictionKg()
    svc = JudgementService(
        kg=kg,
        kg_tx=kg.tx,
        hist=lambda *args, **kwargs: None,
        foundation=lambda name: None,
        reproducible_for_node=lambda name, tag: None,
    )

    out = svc.register_prediction('T', 'seam', _pred())

    assert out['idempotent'] is True
    assert out['pred_receipt_sha'] == kg.node['pred_receipt_sha']
    assert len(kg.receipts) == 1
    assert len(kg.outboxes) == 1


class _PoisonedPredictionIntentKg(_RegKg):
    def __call__(self, query, **params):
        if (
            'SET e.pred_metric' in query
            and params.get('history_event_id') not in self.outboxes
        ):
            self.registration_query = query
            self.outboxes[params['history_event_id']] = {
                'id': params['history_event_id'],
                'tree': params['tree'],
                'op': 'prediction_register',
                'node_tag': params['tag'],
                'payload': params['history_payload_json'],
                'status': 'pending',
                'created_at': params['ts'],
                'reason': 'prediction_register_commit_intent',
                'applied_at': None,
                'receipt_sha': '0' * 64,
            }
        return super().__call__(query, **params)


def test_poisoned_same_id_prediction_intent_cannot_mutate_domain_state():
    kg = _PoisonedPredictionIntentKg()
    service = JudgementService(
        kg=kg,
        kg_tx=lambda ops: [[] for _ in ops],
        hist=lambda *args, **kwargs: None,
        foundation=lambda _name: None,
        reproducible_for_node=lambda _name, _tag: None,
    )

    with pytest.raises(HTTPException) as error:
        service.register_prediction('T', 'seam', _pred())

    assert error.value.status_code == 409
    assert kg.node.get('pred_registered_at') is None
    assert kg.node.get('pred_receipt_sha') is None
    assert kg.receipts == []
    assert 'prior_outboxes[0].receipt_sha=$rsha' in kg.registration_query
    assert 'prior_outboxes[0].request_sha256 IS NULL' in kg.registration_query


def test_live_ledger_empty_projection_uses_transaction_rollback_guard():
    captured = []

    def reject(ops):
        captured.append(ops)
        raise KgTxGuardFailed('guarded first statement matched no row')

    service = JudgementService(
        kg=lambda _query, **_params: [],
        kg_tx=lambda _ops: [],
        ledger_kg_tx=reject,
        hist=lambda *args, **kwargs: None,
        foundation=lambda _name: None,
        reproducible_for_node=lambda _name, _tag: None,
    )

    assert service._ledger_write('RETURN null AS rejected') == []
    assert len(captured) == 1
    assert isinstance(captured[0], GuardedKgOps)


def test_submit_chains_verdict_receipt_onto_prediction_receipt():
    """submit 의 verdict receipt 가 prediction receipt 를 prev 로 봉인 → 해시-인과 순서(spec ≺ verdict)."""
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    pred_sha = kg.node['current_receipt_sha']
    out = svc.submit_test_result('T', 'seam', Result(metric_value=1.0, script='inline', novel_measured=1.0))
    assert out['verdict'] == 'progressive_unverified', out
    heads = [r for r in kg.receipts if r.get('verdict_source') == 'scripted']
    assert len(heads) == 1
    assert heads[0]['prev_receipt_sha'] == pred_sha, 'verdict 가 prediction sha 를 봉인 안 함(back-fit 살아있음)'
    # 체인 fold: head(verdict) → prediction(genesis) 도달 (무결)
    v = svc.verify_verdict_chain('T', 'seam')
    assert v['ok'] and v['from_receipt'] and v['rederived'] == 'progressive_unverified', v
    assert out['question'] == {
        'target': 'q-x', 'closed': False, 'state': 'OPEN',
        'transition': 'adjudication-retain-open',
    }
    assert kg.questions['q-x']['status'] == 'OPEN'
    assert out['eureka']['true'] is False


def test_direct_submit_history_crash_retries_without_second_verdict():
    calls = []

    def crash_test_history_once(*args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == 'test_result' and sum(
            call[0][1] == 'test_result' for call in calls
        ) == 1:
            raise RuntimeError('test history projection crash')

    svc, kg = _svc(hist=crash_test_history_once)
    svc.register_prediction('T', 'seam', _pred())
    result = Result(metric_value=1.0, script='inline', novel_measured=1.0)

    with pytest.raises(RuntimeError, match='test history projection crash'):
        svc.submit_test_result('T', 'seam', result)
    committed_receipts = list(kg.receipts)

    replayed = svc.submit_test_result('T', 'seam', result)
    assert replayed['ok'] is True and replayed['idempotent'] is True
    assert replayed['verdict'] == 'progressive_unverified'
    assert kg.receipts == committed_receipts
    test_calls = [call for call in calls if call[0][1] == 'test_result']
    assert test_calls[0][1]['event_id'] == test_calls[1][1]['event_id']


def test_historical_absolute_artifact_exact_retry_precedes_portability_gate(
    tmp_path, monkeypatch
):
    """A committed historical request repairs its history before new path policy runs."""
    calls = []

    def crash_test_history_once(*args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == 'test_result' and sum(
            call[0][1] == 'test_result' for call in calls
        ) == 1:
            raise RuntimeError('test history projection crash')

    result, producer = _verified_progressive_result(tmp_path)
    svc, kg = _svc(hist=crash_test_history_once, producer=producer)
    svc.register_prediction('T', 'seam', _pred())
    with pytest.raises(RuntimeError, match='test history projection crash'):
        svc.submit_test_result('T', 'seam', result)
    committed_receipts = list(kg.receipts)

    def path_policy_must_not_run(*_args, **_kwargs):
        raise AssertionError('exact replay crossed the fresh portability boundary')

    monkeypatch.setattr(
        judgement_module,
        'isolate_portable_replay_file',
        path_policy_must_not_run,
        raising=False,
    )
    replayed = svc.submit_test_result('T', 'seam', result)
    assert replayed['ok'] is True and replayed['idempotent'] is True
    assert kg.receipts == committed_receipts


def test_question_close_history_crash_replays_causal_intents_without_rejudge(
    tmp_path,
):
    calls = []

    def crash_close_once(*args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == 'question_close' and sum(
            call[0][1] == 'question_close' for call in calls
        ) == 1:
            raise RuntimeError('question close projection crash')

    result, producer = _verified_progressive_result(tmp_path)
    svc, kg = _svc(hist=crash_close_once, producer=producer)
    svc.register_prediction('T', 'seam', _pred())

    with pytest.raises(RuntimeError, match='question close projection crash'):
        svc.submit_test_result('T', 'seam', result)
    committed_receipts = list(kg.receipts)

    replayed = svc.submit_test_result('T', 'seam', result)
    assert replayed['idempotent'] is True
    assert replayed['question']['closed'] is True
    assert kg.receipts == committed_receipts
    close_calls = [call for call in calls if call[0][1] == 'question_close']
    assert close_calls[0][1]['event_id'] == close_calls[1][1]['event_id']


def test_replay_verified_progressive_submit_atomically_closes_bound_question(
    tmp_path,
):
    result, producer = _verified_progressive_result(tmp_path)
    svc, kg = _svc(producer=producer)
    svc.register_prediction('T', 'seam', _pred())

    out = svc.submit_test_result('T', 'seam', result)

    assert out['verdict'] == 'progressive', out
    assert out['question'] == {
        'target': 'q-x', 'closed': True, 'state': 'CLOSED',
        'transition': 'adjudication-close',
    }
    assert kg.questions['q-x']['status'] == 'CLOSED'
    assert kg.questions['q-x']['closed_by'] == ['seam']
    verdict_receipt = next(r for r in kg.receipts if r.get('verdict_source') == 'scripted')
    assert kg.questions['q-x']['closed_events'] == [verdict_receipt['receipt_sha']]


def test_receipted_submit_against_preclosed_question_reports_duplicate_not_close():
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    kg.questions['q-x']['status'] = 'CLOSED'

    out = svc.submit_test_result(
        'T', 'seam',
        Result(metric_value=1.0, script='inline', novel_measured=1.0,
               lakatos_anomaly=True, lakatos_consequence=True,
               lakatos_excess=True, lakatos_hardcore=True),
    )

    assert out['question'] == {
        'target': 'q-x', 'closed': False, 'state': 'CLOSED',
        'transition': 'duplicate-adjudication',
    }
    assert kg.questions['q-x']['closed_by'] == []
    assert out['eureka']['true'] is False


def test_submit_against_unknown_question_state_rolls_back_before_receipt_write():
    svc, kg = _svc()
    svc.register_prediction('T', 'seam', _pred())
    prediction_receipt_count = len(kg.receipts)
    prediction_head = kg.node['current_receipt_sha']
    kg.questions['q-x']['status'] = 'CORRUPT'

    with pytest.raises(HTTPException) as exc:
        svc.submit_test_result(
            'T', 'seam',
            Result(metric_value=1.0, script='inline', novel_measured=1.0,
                   lakatos_anomaly=True, lakatos_consequence=True,
                   lakatos_excess=True, lakatos_hardcore=True),
        )

    assert exc.value.status_code == 409
    assert len(kg.receipts) == prediction_receipt_count
    assert kg.node['current_receipt_sha'] == prediction_head
    assert kg.node.get('verdict_source') is None


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
        dict(base, receipt_kind='prediction', tree='T', tag='anchored-v2',
             registered_at='2026-07-10T00:00:00+00:00',
             anchor_bundle_sha256='b' * 64),
        dict(base, receipt_kind='prediction', tree='T', tag='history-bound-v3',
             registered_at='2026-07-10T00:00:00+00:00',
             anchor_bundle_sha256='b' * 64,
             history_payload_sha256='d' * 64),
    ]
    for f in corpus:
        assert prediction_content_sha(f) == CR.prediction_content_sha(f), f'byte-parity 붕괴: {f}'
    assert prediction_content_sha(corpus[1]) == prediction_content_sha(corpus[2]), 'int/float 정규화 발산'
    changed_bundle = dict(corpus[-2], anchor_bundle_sha256='c' * 64)
    assert prediction_content_sha(changed_bundle) != prediction_content_sha(corpus[-2])
    changed_history = dict(corpus[-1], history_payload_sha256='e' * 64)
    assert prediction_content_sha(changed_history) == CR.prediction_content_sha(changed_history)
    assert prediction_content_sha(changed_history) != prediction_content_sha(corpus[-1])
    assert CR.prediction_content_sha(changed_history) != CR.prediction_content_sha(corpus[-1])


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


def test_exact_retry_repairs_post_receipt_history_without_reminting():
    """Receipt mint 뒤 history crash도 동일 요청 재시도로 수렴한다."""

    calls = []

    def crash_once(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise RuntimeError("crash after prediction receipt mint")

    svc, kg = _svc(hist=crash_once)
    prediction = _pred()
    with pytest.raises(RuntimeError, match="after prediction receipt"):
        svc.register_prediction('T', 'seam', prediction)

    minted = list(kg.receipts)
    repaired = svc.register_prediction('T', 'seam', prediction)

    assert repaired['ok'] is True and repaired['idempotent'] is True
    assert repaired['pred_receipt_sha'] == minted[0]['receipt_sha']
    assert repaired['pred_anchor_verified'] is False
    assert repaired['question_bound'] is True
    assert kg.receipts == minted
    assert calls[0][1]['event_id'] == calls[1][1]['event_id']


def test_exact_retry_precedes_current_layout_ontology_and_witness_policy(monkeypatch):
    svc, kg = _svc()
    prediction = _pred()
    first = svc.register_prediction('T', 'seam', prediction)
    meta_reads_before = sum(
        't.ontology AS ontology' in query for query, _params in kg.calls
    ) if hasattr(kg, 'calls') else None

    def stale_policy_must_not_be_read(_meta):
        raise AssertionError('mutable role layout preempted immutable receipt replay')

    monkeypatch.setattr(judgement_module, 'resolve_role_layout', stale_policy_must_not_be_read)
    retried = svc.register_prediction('T', 'seam', prediction)

    assert retried['ok'] is True and retried['idempotent'] is True
    assert retried['pred_receipt_sha'] == first['pred_receipt_sha']
    if meta_reads_before is not None:
        assert sum('t.ontology AS ontology' in q for q, _p in kg.calls) == meta_reads_before
