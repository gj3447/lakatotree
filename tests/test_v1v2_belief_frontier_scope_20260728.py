"""V1/V2 수리 가드 — AGM Belief 트리 스코프 + frontier 재개방·이중close (검증 감사 2026-07-28).

  V1 (DEFECT): Belief MERGE 키가 전역 belief_id 라 두 트리가 같은 id 를 쓰면 한 노드를 공유했다 —
               한 트리의 contraction(abandoned=true)이 다른 트리 base 에서 침묵 소실을 일으킨다.
               2026-07-23 OpenQuestion 트리-스코프 수리(service.py:157-162)와 동일 버그 클래스.
  V2 (DEFECT/GAP): open_question 재-MERGE 가 무가드 status='OPEN' + created_at 덮어쓰기로
               CLOSED→OPEN 침묵 재개방 + 등록시각 파괴. close_question 은 OPEN 가드가 없어
               이중 close 가 n_visits·closed_events 를 계속 부풀렸다(멱등도 거부도 아님).

각 항목은 결함 재현(수리 전 RED)과 정상 경로 무회귀(과잉 차단 금지)를 쌍으로 건다.
# KG: plan-lktadv-v1-agm-belief-tree-scope-20260728 / plan-lktadv-v2-frontier-reopen-guard-20260728
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault('NEO4J_URI', 'bolt://localhost:7687')
os.environ.setdefault('NEO4J_USER', 'neo4j')
os.environ.setdefault('NEO4J_PASSWORD', 'test')

from fastapi import HTTPException  # noqa: E402


# ── V1: Belief MERGE 키가 (belief_id, tree) 복합이어야 ────────────────────────────────

def test_belief_merge_is_tree_scoped():
    """전역 belief_id MERGE 는 트리 간 상태 오염 — OpenQuestion 선례와 같은 복합키여야."""
    import inspect
    from server import app as app_mod
    src = inspect.getsource(app_mod._persist_revision)
    assert 'MERGE (bel:Belief {belief_id: b.belief_id, tree: $tree})' in src, \
        'Belief MERGE 가 전역 belief_id — 다른 트리의 belief 를 덮어쓴다'


def test_belief_load_and_abandon_stay_tree_scoped():
    """읽기·폐기 경로는 이미 트리 스코프였다 — 수리가 그걸 깨지 않아야(무회귀)."""
    import inspect
    from server import app as app_mod
    load_src = inspect.getsource(app_mod._load_belief_base)
    assert '(t:LakatosTree {name:$tree})-[:HAS_BELIEF]->' in load_src
    persist_src = inspect.getsource(app_mod._persist_revision)
    assert '-[:HAS_BELIEF]->(bel:Belief)\n                       WHERE bel.belief_id IN $removed' \
           in persist_src or 'WHERE bel.belief_id IN $removed' in persist_src


# ── V2: frontier 재개방 침묵 금지 + 이중 close 멱등 ───────────────────────────────────

class _StubKg:
    """질문 노드 1개를 흉내내는 최소 KG — 쿼리 텍스트로 분기(test_delete_tree_surface 관례)."""

    def __init__(self, status=None, created_at='2026-07-01T00:00:00+00:00', n_visits=3):
        self.q = None if status is None else dict(
            name='q1', status=status, created_at=created_at, n_visits=n_visits,
            body='원 등록 본문', closed_by=['n1'], closed_events=['e1'])
        self.calls = []

    def __call__(self, query, **params):
        self.calls.append((query, params))
        if 'MERGE (qn:OpenQuestion' in query:
            if self.q is not None and (self.q.get('status') or 'OPEN') == 'CLOSED':
                return []                      # WHERE 가드 미통과 (원자 쿼리 의미론)
            if self.q is None:
                self.q = dict(name=params['qn'], status='OPEN',
                              created_at=params['ts'], n_visits=0, body=params['body'])
            else:
                self.q.update(body=params['body'], status='OPEN')
            return [dict(name=self.q['name'])]
        if "='CLOSED' RETURN q.name" in query:
            return ([dict(name=self.q['name'])]
                    if self.q and (self.q.get('status') or 'OPEN') == 'CLOSED' else [])
        if 'SET q.status=' in query or 'q.status=' in query:
            if self.q is None:
                return []
            self.q['n_visits'] = (self.q.get('n_visits') or 0) + 1
            self.q['status'] = 'CLOSED'
            return [dict(name=self.q['name'])]
        if 'RETURN q.status' in query or 'q.status AS status' in query:
            return [] if self.q is None else [dict(status=self.q['status'],
                                                   created_at=self.q.get('created_at'))]
        return [dict(name='T')]


def _svc(kg):
    from server.contexts.tree.service import TreeService
    return TreeService(kg=kg, kg_tx=lambda ops: [], hist=lambda *a, **k: None, pg=lambda: None)


def _qin(qname='q1', body='새 본문'):
    from server.contexts.tree.schemas import QuestionIn
    return QuestionIn(qname=qname, body=body)


def test_open_question_on_closed_is_rejected_not_silent():
    """CLOSED 질문의 재-open 은 침묵 재개방 대신 409 — 재개방하려면 새 질문으로 분기한다."""
    kg = _StubKg(status='CLOSED')
    with pytest.raises(HTTPException) as ei:
        _svc(kg).open_question('T', _qin())
    assert ei.value.status_code == 409 and 'CLOSED' in str(ei.value.detail)


def test_open_question_on_open_updates_body_but_preserves_created_at():
    """OPEN 질문 갱신은 허용하되 등록 시각은 보존(이력 파괴 금지)."""
    import inspect
    from server.contexts.tree.service import TreeService
    src = inspect.getsource(TreeService.open_question)
    assert 'qn.created_at=coalesce(qn.created_at, $ts)' in src, 'created_at 무조건 덮어쓰기 잔존'
    kg = _StubKg(status='OPEN')
    out = _svc(kg).open_question('T', _qin())
    assert out and kg.q['body'] == '새 본문'


def test_open_question_new_question_still_works():
    """신규 질문 생성은 무회귀(과잉 차단 금지)."""
    kg = _StubKg(status=None)
    out = _svc(kg).open_question('T', _qin())
    assert out and kg.q['status'] == 'OPEN'


def test_close_question_is_idempotent_on_already_closed():
    """이중 close 가 n_visits·closed_events 를 부풀리지 않아야(멱등)."""
    import inspect
    from server.contexts.tree.service import TreeService
    src = inspect.getsource(TreeService.close_question)
    assert "q.status='OPEN'" in src or "coalesce(q.status,'OPEN')='OPEN'" in src, \
        'close 에 OPEN 가드 없음 — 이중 close 가 방문수/이력을 계속 부풀린다'
    assert 'already_closed' in src, '멱등 경로의 응답 표기가 없다(침묵 성공 금지)'


def test_upsert_questions_preserves_created_at_and_status():
    """writer 벌크 경로도 같은 계약 — 한쪽만 고치면 다른 경로로 우회된다."""
    import inspect
    from server.contexts.tree import writer as w
    src = inspect.getsource(w)
    assert 'qn.created_at=coalesce(qn.created_at, row.ts)' in src, 'bulk 경로 created_at 덮어쓰기'
    assert "qn.status=coalesce(qn.status, 'OPEN')" in src, 'bulk 경로가 CLOSED 를 OPEN 으로 되돌림'
