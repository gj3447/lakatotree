"""R10-s4 + R12 — 캠페인 폐막 가드 (후속 PROM 2026-07-03).

R10-s4 delete_tree 하드가드:
  guard_defect : test_delete_tree_with_receipts_is_blocked
        — engine verdict/:VerdictReceipt 보유 트리 cascade 삭제 = 409(영수증 물리파괴 창 봉합).
          조회 실패 = 409 fail-safe(불확실하면 안 지움). 영수증 없는 빈/draft 트리는 종전대로.

R12 baseline lineage 앵커(ManifestoGap S1 mechanism):
  guard_mechanism : test_baseline_bound_to_parent_measured_or_no_prior
        — 예측 baseline 이 부모의 서버-persist measured 에 앵커된다: 부모 measured 정합=anchored,
          벗어남=unanchored 마크(전략적 부풀림 노출), 부모 없음=no_prior 명시. 비파괴(마크만·강제 아님).

# KG: LakatosTree_ManifestoGap_20260702 / followup-R10s4-R12
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.contexts.tree.judgement_service import JudgementService
from server.contexts.tree.schemas import PredictionIn
from server.contexts.tree.service import TreeService


# ── R10-s4: delete_tree 하드가드 ──────────────────────────────────────────────────────────
class _Repo:
    def __init__(self, nodes):
        self.nodes = nodes

    def load_tree_data(self, name):
        return {'nodes': self.nodes}


class _Mut:
    def __init__(self, *, error=None, deleted_nodes=0):
        self.deleted = False
        self.error = error
        self.deleted_nodes = deleted_nodes
        self.calls = []

    def delete_tree(
        self,
        name,
        *,
        cascade,
        idempotency_key,
        require_empty=False,
        require_incarnation_match=False,
        expected_incarnation_id=None,
    ):
        self.calls.append((
            name,
            cascade,
            idempotency_key,
            require_empty,
            require_incarnation_match,
            expected_incarnation_id,
        ))
        if self.error is not None:
            raise self.error
        self.deleted = True
        return {'deleted_nodes': self.deleted_nodes}


def _svc(kg, nodes, mut=None):
    return TreeService(kg=kg, kg_tx=lambda ops: [[{'ok': 1}] for _ in ops], hist=lambda *a, **k: None,
                       pg=lambda: None, repo=_Repo(nodes), mutations=(mut or _Mut()))


def test_delete_tree_with_receipts_is_blocked():
    # Receipt/history inspection now belongs to the lock-held mutation writer;
    # TreeService must propagate that authoritative decision without a stale
    # pre-read or a second delete.
    protected = _Mut(error=HTTPException(409, '영수증 보유 트리 삭제 차단'))
    with pytest.raises(HTTPException) as e:
        _svc(lambda *_a, **_k: [], [], protected).delete_tree(
            'T', cascade=True, idempotency_key='protected')
    assert e.value.status_code == 409 and '영수증' in str(e.value.detail), e.value.detail
    assert protected.calls == [
        ('T', True, 'protected', False, False, None)
    ] and protected.deleted is False

    # Infrastructure failure remains fail-closed and visible; it is not
    # mislabeled as a semantic 409.
    failed = _Mut(error=RuntimeError('kg down'))
    with pytest.raises(RuntimeError, match='kg down'):
        _svc(lambda *_a, **_k: [], [], failed).delete_tree(
            'T', cascade=True, idempotency_key='failed')
    assert failed.deleted is False

    # An authoritative successful decision is surfaced unchanged.
    mut = _Mut(deleted_nodes=1)
    out = _svc(lambda *_a, **_k: [], [], mut).delete_tree(
        'T', cascade=True, idempotency_key='success')
    assert out['ok'] is True and mut.deleted is True


# ── R12: baseline lineage 앵커 ────────────────────────────────────────────────────────────
class _PredKg:
    """register_prediction 의 부모 measured 조회 + SET 을 충실 적용."""

    def __init__(self, parent_measured):
        self.parent_measured = parent_measured
        self.node = {}
        self.outboxes = {}

    def __call__(self, q, **p):
        if 'ontology' in q:
            return [{'ontology': None}]
        if 'RETURN e.current_receipt_sha AS prev_rsha' in q:
            return [{
                'prev_rsha': None,
                'pred_receipt_sha': None,
                'pred_registered_at': None,
                'pred_prev_receipt_sha': None,
                'pred_baseline_lineage': None,
            }]
        if 'MATCH (o:OutboxEntry {id:$id})' in q:
            row = self.outboxes.get(p['id'])
            return [dict(row)] if row is not None else []
        if 'parent' in q.lower() and 'metric_value' in q:   # R12 부모 measured 조회
            return [{'parent_measured': self.parent_measured}] if self.parent_measured is not None else []
        if 'SET e.pred_metric' in q:
            self.node.update({k: p.get(k) for k in p})
            self.outboxes[p['history_event_id']] = {
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
            }
            return [{'tag': p.get('tag')}]
        return []


def _register(parent_measured, baseline, noise=0.0):
    kg = _PredKg(parent_measured)
    svc = JudgementService(kg=kg, kg_tx=lambda ops: [[{'ok': 1}] for _ in ops], hist=lambda *a, **k: None,
                           foundation=lambda *a, **k: None, reproducible_for_node=lambda *a, **k: None)
    svc.register_prediction('T', 'n', PredictionIn(
        metric_name='m', direction='lower', baseline_value=baseline, noise_band=noise,
        novel_prediction='x'))
    return kg.node


def test_baseline_bound_to_parent_measured_or_no_prior():
    # (1) 부모 measured=10.0, baseline=10.0 정합 → anchored.
    assert _register(10.0, 10.0)['baseline_lineage'] == 'anchored'
    # (2) 부모 measured=10.0 인데 baseline=2.0(전략적 부풀림, 노이즈밴드 밖) → unanchored 마크.
    assert _register(10.0, 2.0, noise=0.5)['baseline_lineage'] == 'unanchored'
    # (3) 부모 measured 없음(콜드스타트) → no_prior 명시(비파괴 — 등록은 성공).
    assert _register(None, 5.0)['baseline_lineage'] == 'no_prior'
    # 공시: repository RETURN 에 baseline_lineage alias(R1 bijection 정합).
    from pathlib import Path
    repo = (Path(__file__).resolve().parents[2] / 'server/contexts/tree/repository.py').read_text()
    assert 'e.baseline_lineage AS baseline_lineage' in repo, 'baseline_lineage 비공시'
