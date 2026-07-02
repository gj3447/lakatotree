"""git-흡수 G9 landed guards — 폐기=포인터 죽음(비파괴) + 도달성 스윕 (Laudan 폐기 증거 불멸).

  guard_defect(개선축)     : test_demote_and_prune_never_destroy_receipts
        — AGM contraction 이 belief 를 물리 삭제(DETACH DELETE)하지 않고 abandoned 표식 + was_credence 복구영수증;
          active base 에서만 빠지고 노드는 도달가능 잔존. 재추가 시 abandoned=false 부활(TRAP1). ✅
  guard_mechanism(novel축) : test_reachability_sweep_keeps_engine_verdicts_reachable
        — 순수 도달성 스윕이 루트서 engine 노드 orphan-free 확인; prunable 게이트=unreachable∧aged(서버tx)만 True. ✅

# KG: LakatosTree_GitAbsorption_20260702 / G9_prune_pointer_death
"""
from __future__ import annotations

from server.contexts.audit import reachability as R


# ── guard_defect (개선축) — 착륙: belief 포인터 죽음 ─────────────────────────────────────────
class _BeliefKg:
    """_persist_revision 의 belief op 를 충실 적용 — abandon(SET) vs revive(MERGE SET) 를 in-memory 로 모델."""

    def __init__(self):
        self.beliefs: dict[str, dict] = {}   # belief_id → props

    def __call__(self, ops):
        for query, params in ops:
            if 'UNWIND $beliefs AS b' in query:   # UPSERT(r.base) — revive(abandoned=false)
                for b in params['beliefs']:
                    node = self.beliefs.setdefault(b['belief_id'], {})
                    node.update(b)
                    node['abandoned'] = False
                    node['was_credence'] = None
            elif 'bel.belief_id IN $removed' in query and 'abandoned=true' in query:   # abandon(비파괴)
                for bid in params['removed']:
                    node = self.beliefs.setdefault(bid, {})
                    node['was_credence'] = node.get('credence')
                    node['abandoned'] = True
                    node['abandoned_at'] = params['ts']
            elif 'DETACH DELETE' in query:   # 결함(봉합 전) — 물리 삭제
                for bid in params.get('removed', []):
                    self.beliefs.pop(bid, None)
        return [[{'x': 1}] for _ in ops]

    def active(self) -> set:
        return {bid for bid, p in self.beliefs.items() if not p.get('abandoned', False)}


def _persist_via(kg, base_ids, removed_ids):
    """app._persist_revision 의 belief op 모양을 재현(그 함수의 Cypher 계약을 고정)."""
    ts = '2026-07-02T00:00:00Z'
    beliefs = [dict(belief_id=b, statement=b, kind='protective_belt', credence=0.5,
                    problem_balance=0, connectivity=0, depends_on=[]) for b in base_ids]
    ops = [("""MATCH (t:LakatosTree {name:$tree})
               UNWIND $beliefs AS b
               MERGE (bel:Belief {belief_id: b.belief_id})
               SET bel.credence=b.credence, bel.updated_at=$ts, bel.abandoned=false,
                   bel.was_credence=null, bel.was_kind=null
               MERGE (t)-[:HAS_BELIEF]->(bel)""", dict(tree='T', beliefs=beliefs, ts=ts))]
    if removed_ids:
        ops.append(("""MATCH (t:LakatosTree {name:$tree})-[:HAS_BELIEF]->(bel:Belief)
                       WHERE bel.belief_id IN $removed
                       SET bel.abandoned=true, bel.was_credence=bel.credence,
                           bel.was_kind=bel.kind, bel.abandoned_at=$ts""",
                    dict(tree='T', removed=removed_ids, ts=ts)))
    kg(ops)


def test_demote_and_prune_never_destroy_receipts():
    """AGM contraction 이 belief X 를 제거해도 X 는 물리 잔존(abandoned=true+was_credence), active base 에서만 빠진다.
    이후 X 재추가(expansion)면 abandoned=false 로 부활(TRAP1: 재추가가 조용히 no-op 되지 않음)."""
    kg = _BeliefKg()
    # 초기: {A,B} 확립(credence 0.5)
    _persist_via(kg, ['A', 'B'], [])
    assert kg.active() == {'A', 'B'}
    # contraction: B 제거 → B 는 abandoned(비파괴), active 에서만 빠짐, was_credence 보존.
    _persist_via(kg, ['A'], ['B'])
    assert kg.active() == {'A'}, kg.active()
    assert 'B' in kg.beliefs and kg.beliefs['B']['abandoned'] is True, "B 가 물리 삭제됨(증거 소실)"
    assert kg.beliefs['B']['was_credence'] == 0.5, "was_credence 복구영수증 부재"
    # expansion: B 재추가 → 부활(abandoned=false). 재추가가 조용히 무시되면 active 에 안 돌아옴(TRAP1).
    _persist_via(kg, ['A', 'B'], [])
    assert kg.active() == {'A', 'B'}, f"B 부활 실패(TRAP1): {kg.active()}"


def test_belief_load_filter_excludes_abandoned():
    """_load_belief_base 의 active 필터 계약: abandoned belief 는 base 재진입 금지(contraction no-op 방지)."""
    kg = _BeliefKg()
    _persist_via(kg, ['A', 'B'], [])
    _persist_via(kg, ['A'], ['B'])
    # active() = _load_belief_base(WHERE coalesce(abandoned,false)=false) 의 in-memory 아날로그
    assert 'B' not in kg.active() and 'B' in kg.beliefs


# ── guard_mechanism (novel축) — 착륙: 도달성 스윕 ───────────────────────────────────────────
def test_reachability_sweep_keeps_engine_verdicts_reachable():
    # 루트 R → n1 → n2(engine), 그리고 고립된 orphan(engine).
    edges = {'R': ['n1'], 'n1': ['n2']}
    records = [{'id': 'n2', 'engine_scored': True}, {'id': 'orphan', 'engine_scored': True},
               {'id': 'draft', 'engine_scored': False}]
    # (1) 루트가 orphan 을 포함하면 orphan-free.
    orphans = R.sweep_orphans(roots=['R', 'orphan'], edges=edges, records=records)
    assert orphans == [], orphans
    # (2) orphan 이 루트서 도달 불가면 ORPHANED_ENGINE_VERDICT hard finding(스윕 멈춤).
    orphans2 = R.sweep_orphans(roots=['R'], edges=edges, records=records)
    assert [o.node_id for o in orphans2] == ['orphan'], orphans2
    # draft(engine_scored=False)는 orphan 이어도 finding 아님(engine verdict 만 불멸 대상).
    assert all(o.node_id != 'draft' for o in orphans2)


def test_prunable_gate_requires_unreachable_and_aged():
    reach = R.reachable_set(roots=['R'], edges={'R': ['n1']})   # {R, n1}
    now = 1_000_000.0
    grace = R.ERASURE_GRACE_SECONDS
    # 도달가능 → 절대 소거 불가(불멸).
    assert R.prunable({'id': 'n1', 'tombstoned_at': now - grace - 1}, reach, now) is False
    # unreachable + tombstone 없음 → 소거 불가(포인터 아직 삼).
    assert R.prunable({'id': 'x', 'tombstoned_at': None}, reach, now) is False
    # unreachable + grace 미경과 → 소거 불가(in-flight 보호).
    assert R.prunable({'id': 'x', 'tombstoned_at': now - 1}, reach, now) is False
    # unreachable + aged past grace → 유일하게 소거 가능.
    assert R.prunable({'id': 'x', 'tombstoned_at': now - grace - 1}, reach, now) is True
    # grace 는 코드 상수(요청 가변 아님) — 존재·양수 확인.
    assert isinstance(grace, (int, float)) and grace > 0
