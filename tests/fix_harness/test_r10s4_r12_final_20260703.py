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
    def __init__(self):
        self.deleted = False

    def delete_tree(self, name):
        self.deleted = True


def _svc(kg, nodes, mut=None):
    return TreeService(kg=kg, kg_tx=lambda ops: [[{'ok': 1}] for _ in ops], hist=lambda *a, **k: None,
                       pg=lambda: None, repo=_Repo(nodes), mutations=(mut or _Mut()))


def test_delete_tree_with_receipts_is_blocked():
    def receipted(q, **p):
        return [{'n': 3}] if ('current_receipt_sha' in q or 'verdict_source IN' in q) else []
    # (1) 영수증 보유 + cascade → 409 하드가드(현행: 통과=RED).
    with pytest.raises(HTTPException) as e:
        _svc(receipted, [{'tag': 'a', 'verdict': 'CANONICAL', 'verdict_source': 'admin'}]).delete_tree('T', cascade=True)
    assert e.value.status_code == 409 and '영수증' in str(e.value.detail), e.value.detail
    # (2) 조회 실패 = fail-safe 409(불확실하면 안 지움).
    def _boom(q, **p):
        raise RuntimeError('kg down')
    with pytest.raises(HTTPException) as e2:
        _svc(_boom, [{'tag': 'a'}]).delete_tree('T', cascade=True)
    assert e2.value.status_code == 409
    # (3) 영수증 없는 트리 → 종전대로 삭제 성공.
    mut = _Mut()
    out = _svc(lambda q, **p: [{'n': 0}], [{'tag': 'draft', 'verdict': 'proof'}], mut).delete_tree('T', cascade=True)
    assert out['ok'] is True and mut.deleted is True


# ── R12: baseline lineage 앵커 ────────────────────────────────────────────────────────────
class _PredKg:
    """register_prediction 의 부모 measured 조회 + SET 을 충실 적용."""

    def __init__(self, parent_measured):
        self.parent_measured = parent_measured
        self.node = {}

    def __call__(self, q, **p):
        if 'ontology' in q:
            return [{'ontology': None}]
        if 'parent' in q.lower() and 'metric_value' in q:   # R12 부모 measured 조회
            return [{'parent_measured': self.parent_measured}] if self.parent_measured is not None else []
        if 'SET e.pred_metric' in q:
            self.node.update({k: p.get(k) for k in p})
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
