"""V5 수리 가드 — 논증 파이프라인 무결성 (검증 감사 2026-07-28, OSS:argumentation GAP).

  결함 ①: attack 타깃이 검증되지 않아 오타/오배치 doubt 가 침묵 드롭됐다 — 제기자는 등재
          성공(200)을 받지만 AF 에 엣지가 안 생겨 판결이 그대로 선다(막힌 줄 아는데 안 막힘).
  결함 ②: Argument 가 가변이라 같은 arg_id 로 타인의 doubt 를 덮어쓸 수 있었다 —
          doubt 를 rebuttal 로 개서하면 standing 이 침묵 복원된다.

계약: 타깃은 노드 tag(=verdict 직접공격) 또는 그 노드에 이미 등재된 argument 여야 하고(아니면
422), 기존 argument 는 불변이다(동일 내용 재등재만 멱등, 변경 시 409 — 새 id 로 등재하라).
# KG: plan-lktadv-v5-argumentation-pipeline-20260728
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from fastapi import HTTPException  # noqa: E402

from server.contexts.tree.evidence_claim_service import EvidenceClaimService  # noqa: E402
from server.contexts.tree.schemas import CritiqueIn  # noqa: E402


class _Kg:
    """노드 1개 + 기존 argument 목록을 흉내내는 최소 KG."""

    def __init__(self, existing=()):
        self.existing = {a['id']: a for a in existing}
        self.written = []

    def __call__(self, query, **p):
        if 'RETURN e.tag AS tag, collect' in query:
            return [dict(tag=p.get('tag'), args=list(self.existing.values()))]
        if 'RETURN e.verdict AS verdict' in query:       # 후속 standing 재계산 경로
            return [dict(verdict='proof', vur=True, prev_receipt_sha=None,
                         args=list(self.existing.values()))]
        if 'MERGE (a:Argument' in query:
            self.written.append(p)
            return [dict(tag=p.get('tag'))]
        return []


def _svc(kg):
    svc = object.__new__(EvidenceClaimService)
    svc.kg = kg
    svc.hist = lambda *a, **k: None
    return svc


def _c(arg_id='d1', attacks='n', by='alice', kind='doubt', body='의문'):
    return CritiqueIn(arg_id=arg_id, attacks=attacks, by=by, kind=kind, body=body)


def test_attack_on_node_tag_is_accepted():
    """verdict 직접공격(attacks == tag)은 정상 — 무회귀."""
    kg = _Kg()
    out = _svc(kg).add_critique('T', 'n', _c(attacks='n'))
    assert out['ok'] and kg.written


def test_attack_on_existing_argument_is_accepted():
    """다른 argument 공격(rebuttal)도 그 argument 가 실재하면 정상."""
    kg = _Kg(existing=[dict(id='T/d1', attacks='n', by='alice', kind='doubt')])
    out = _svc(kg).add_critique('T', 'n', _c(arg_id='r1', attacks='d1', by='bob', kind='rebuttal'))
    assert out['ok']


def test_attack_on_unknown_target_is_rejected_not_silent():
    """오타 타깃은 422 — 종전엔 200 을 받고 AF 에서 침묵 소실했다(제기자는 막았다고 오인)."""
    kg = _Kg(existing=[dict(id='T/d1', attacks='n', by='alice', kind='doubt')])
    with pytest.raises(HTTPException) as ei:
        _svc(kg).add_critique('T', 'n', _c(arg_id='r1', attacks='d1-typo', by='bob'))
    assert ei.value.status_code == 422 and 'attacks' in str(ei.value.detail)


def test_existing_argument_is_immutable_across_actors():
    """타인 논증 덮어쓰기 금지 — doubt 를 rebuttal 로 개서해 standing 을 침묵 복원할 수 없다."""
    kg = _Kg(existing=[dict(id='T/d1', attacks='n', by='alice', kind='doubt', body='의문')])
    with pytest.raises(HTTPException) as ei:
        _svc(kg).add_critique('T', 'n', _c(arg_id='d1', attacks='n', by='mallory',
                                           kind='rebuttal', body='사실 괜찮음'))
    assert ei.value.status_code == 409 and '불변' in str(ei.value.detail)


def test_identical_reregistration_is_idempotent():
    """동일 내용 재등재는 멱등 — 네트워크 재시도를 깨뜨리지 않는다."""
    same = dict(id='T/d1', attacks='n', by='alice', kind='doubt', body='의문')
    kg = _Kg(existing=[same])
    out = _svc(kg).add_critique('T', 'n', _c(arg_id='d1', attacks='n', by='alice',
                                             kind='doubt', body='의문'))
    assert out['ok'] and out.get('idempotent') is True
    assert not kg.written, '멱등 경로는 재기록하지 않는다'
